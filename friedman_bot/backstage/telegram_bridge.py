"""
Telegram-мост Backstage: у каждого клиента может быть свой бот (токен от @BotFather
вводится в настройках панели), и этот бот пишет той же команде, что и веб-чат.
Переписка, дашборд и бюджет — общие с панелью.

Один процесс обслуживает всех клиентов: на каждый токен — поток с long polling
(getUpdates). Список ботов перечитывается из базы раз в минуту, поэтому новый
клиент подключается без перезапуска.

Защита: бот привязывается к первому чату, написавшему /start. Остальным он
не отвечает — иначе любой нашедший бота тратил бы бюджет клиента. Чтобы
перепривязать, клиент заново вводит токен в настройках панели.
"""
import os
import json
import time
import base64
import logging
import threading
import urllib.error
import urllib.request
import urllib.parse

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import store  # noqa: E402
import brain  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [tg] %(message)s")
log = logging.getLogger("backstage.tg")

API = "https://api.telegram.org"
_threads = {}  # client_id → (token, thread, stop_event)
_agent_of = {}  # client_id → текущий агент в Telegram
_bad_tokens = set()  # отвергнутые Telegram токены — не перезапускаем их каждую минуту

HELP = ("Это твоя закулисная команда Backstage. Пиши задачу, вопрос, цифры — отвечает Майя "
        "и при необходимости зовёт специалистов. Можно прислать фото или PDF (договор, смету, афишу).\n\n"
        "/team — состав команды\n/agent <имя> — писать специалисту напрямую (например /agent konrad)\n"
        "/maya — вернуться к Майе\n/deep <текст> — глубокий анализ самой мощной моделью (дольше и дороже)\n"
        "/budget — расход ИИ в этом месяце")


def tg(token, method, timeout=70, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                   for k, v in params.items()}).encode()
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send(token, chat_id, text):
    for i in range(0, len(text), 3900):  # лимит Telegram 4096 символов
        try:
            tg(token, "sendMessage", chat_id=chat_id, text=text[i:i + 3900], disable_web_page_preview="true")
        except Exception as e:  # noqa: BLE001
            log.warning("sendMessage: %s", e)


def download(token, file_id):
    info = tg(token, "getFile", file_id=file_id)["result"]
    with urllib.request.urlopen(f"{API}/file/bot{token}/{info['file_path']}", timeout=60) as r:
        return r.read(), info["file_path"]


def handle(c, token, msg):
    cid = c["id"]
    chat_id = str(msg["chat"]["id"])
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if not c["tg_chat_id"]:
        if not text.startswith("/start"):
            return send(token, chat_id, "Напиши /start, чтобы привязать этого бота к своей панели.")
        store.update_client(cid, tg_chat_id=chat_id)
        c["tg_chat_id"] = chat_id
        return send(token, chat_id, f"Привет, {c['name']}! Бот привязан к твоей панели Backstage.\n\n{HELP}")
    if chat_id != c["tg_chat_id"]:
        return  # чужой чат — молчим

    if text in ("/start", "/help"):
        return send(token, chat_id, HELP)
    if text == "/team":
        return send(token, chat_id, "\n".join(f"{a['emoji']} {a['name']} — {a['role']} (/agent {k})"
                                              for k, a in brain.AGENTS.items()))
    if text == "/budget":
        return send(token, chat_id, f"Потрачено ${store.spent_this_month(cid):.2f} из ${c['monthly_budget']:.2f} в этом месяце.")
    if text == "/maya" or text.startswith("/agent"):
        want = "maya" if text == "/maya" else (text.split(maxsplit=1)[1:] or [""])[0].strip().lower()
        if want not in brain.AGENTS:
            return send(token, chat_id, "Не знаю такого агента. /team — список.")
        _agent_of[cid] = want
        a = brain.AGENTS[want]
        return send(token, chat_id, f"{a['emoji']} Теперь пишешь: {a['name']}, {a['role']}.")

    deep = False
    if text.startswith("/deep"):
        deep, text = True, text[5:].strip()

    atts = []
    try:
        if msg.get("photo"):
            raw, _ = download(token, msg["photo"][-1]["file_id"])
            atts.append({"name": "фото.jpg", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()})
        doc = msg.get("document")
        if doc:
            mt = doc.get("mime_type", "")
            raw, _ = download(token, doc["file_id"])
            if mt == "application/pdf" or mt.startswith("image/"):
                atts.append({"name": doc.get("file_name", "файл"), "media_type": mt, "data": base64.b64encode(raw).decode()})
            elif mt.startswith("text/") or mt in ("application/json",):
                atts.append({"name": doc.get("file_name", "файл"), "media_type": "text/plain",
                             "text": raw.decode("utf-8", "replace")})
            else:
                return send(token, chat_id, "Этот тип файла пока не читаю: пришли PDF, фото или текст.")
    except Exception as e:  # noqa: BLE001
        log.warning("download: %s", e)
        return send(token, chat_id, "Не получилось скачать файл, попробуй ещё раз.")
    if msg.get("voice") or msg.get("audio"):
        return send(token, chat_id, "Голосовые пока не разбираю — напиши текстом.")
    if not text and not atts:
        return
    if not text:
        text = "Посмотри вложение и скажи, что с ним делать."

    tg(token, "sendChatAction", chat_id=chat_id, action="typing")
    try:
        res = brain.chat(cid, _agent_of.get(cid, "maya"), text, attachments=atts, deep=deep)
        tail = []
        if res["consulted"]:
            tail.append("позвала: " + ", ".join(brain.AGENTS[a]["name"] for a in res["consulted"]))
        if res["changed"]:
            tail.append("дашборд обновлён")
        send(token, chat_id, res["text"] + (f"\n\n— {' · '.join(tail)}" if tail else ""))
    except brain.BudgetExceeded as e:
        send(token, chat_id, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("chat")
        send(token, chat_id, f"Команда споткнулась: {e}")


def poll(client_id, token, stop):
    offset = 0
    while not stop.is_set():
        try:
            r = tg(token, "getUpdates", offset=offset, timeout=50, allowed_updates=["message"])
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                c = store.get_client(client_id)
                if msg and c and c["active"] and c["tg_token"] == token:
                    # отдельный поток: длинный ответ одному сообщению не держит остальные
                    threading.Thread(target=handle, args=(c, token, msg), daemon=True).start()
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                log.error("клиент %s: Telegram отверг токен, бот остановлен", client_id)
                _bad_tokens.add(token)
                return
            time.sleep(5)
        except Exception as e:  # noqa: BLE001
            log.warning("poll %s: %s", client_id, e)
            time.sleep(5)


def sync():
    with store.db() as conn:
        rows = conn.execute("SELECT id, tg_token FROM clients WHERE active=1 AND tg_token != ''").fetchall()
    want = {r["id"]: r["tg_token"] for r in rows}
    for cid, (tok, th, stop) in list(_threads.items()):
        if want.get(cid) != tok or not th.is_alive():
            stop.set()
            _threads.pop(cid)
    for cid, tok in want.items():
        if cid not in _threads and tok not in _bad_tokens:
            stop = threading.Event()
            th = threading.Thread(target=poll, args=(cid, tok, stop), daemon=True)
            th.start()
            _threads[cid] = (tok, th, stop)
            log.info("клиент %s: бот запущен", cid)


def main():
    store.init()
    while True:
        try:
            sync()
        except Exception:  # noqa: BLE001
            log.exception("sync")
        time.sleep(60)


if __name__ == "__main__":
    main()
