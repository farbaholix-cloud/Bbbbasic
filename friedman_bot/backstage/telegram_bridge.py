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
import i18n  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [tg] %(message)s")
log = logging.getLogger("backstage.tg")

API = "https://api.telegram.org"
_threads = {}  # client_id → (token, thread, stop_event)
_agent_of = {}  # client_id → текущий агент в Telegram
_bad_tokens = set()  # отвергнутые Telegram токены — не перезапускаем их каждую минуту

TG = {
    "help": {
        "en": "This is your Backstage team behind the scenes. Send a task, a question, numbers — Maya replies and calls in "
              "specialists when needed. You can send a photo or a PDF (contract, estimate, poster).\n\n"
              "/team — the team\n/agent <name> — write to a specialist directly (e.g. /agent konrad)\n"
              "/maya — back to Maya\n/deep <text> — deep analysis with the most powerful model (slower)\n"
              "/budget — AI usage this month",
        "de": "Das ist dein Backstage-Team hinter den Kulissen. Schick eine Aufgabe, eine Frage, Zahlen — Maya antwortet "
              "und holt bei Bedarf Spezialist:innen dazu. Du kannst ein Foto oder PDF schicken (Vertrag, Kalkulation, Plakat).\n\n"
              "/team — das Team\n/agent <Name> — direkt an eine:n Spezialist:in schreiben (z. B. /agent konrad)\n"
              "/maya — zurück zu Maya\n/deep <Text> — Tiefenanalyse mit dem stärksten Modell (dauert länger)\n"
              "/budget — KI-Verbrauch diesen Monat",
        "uk": "Це твоя закулісна команда Backstage. Пиши завдання, питання, цифри — відповідає Майя "
              "і за потреби кличе фахівців. Можна надіслати фото або PDF (договір, кошторис, афішу).\n\n"
              "/team — склад команди\n/agent <ім'я> — писати фахівцю напряму (наприклад /agent konrad)\n"
              "/maya — повернутися до Майї\n/deep <текст> — глибокий аналіз найпотужнішою моделлю (довше)\n"
              "/budget — витрати ШІ цього місяця"},
    "need_start": {"en": "Send /start to link this bot to your Backstage.",
                   "de": "Schick /start, um diesen Bot mit deinem Backstage zu verbinden.",
                   "uk": "Напиши /start, щоб прив'язати цього бота до свого Backstage."},
    "bound": {"en": "Hi {name}! The bot is now linked to your Backstage.", "de": "Hallo {name}! Der Bot ist jetzt mit deinem Backstage verbunden.",
              "uk": "Привіт, {name}! Бота прив'язано до твого Backstage."},
    "budget": {"en": "Spent ${a} of ${b} this month.", "de": "Diesen Monat ${a} von ${b} verbraucht.",
               "uk": "Витрачено ${a} з ${b} цього місяця."},
    "unknown_agent": {"en": "I don't know this agent. /team shows the list.", "de": "Diese:n Agent:in kenne ich nicht. /team zeigt die Liste.",
                      "uk": "Не знаю такого агента. /team — список."},
    "now": {"en": "Now writing to: {name}, {role}.", "de": "Du schreibst jetzt an: {name}, {role}.",
            "uk": "Тепер пишеш: {name}, {role}."},
    "photo": {"en": "photo.jpg", "de": "foto.jpg", "uk": "фото.jpg"},
    "file_type": {"en": "I can't read this file type yet — send a PDF, a photo or text.",
                  "de": "Diesen Dateityp kann ich noch nicht lesen — schick ein PDF, ein Foto oder Text.",
                  "uk": "Цей тип файлу поки не читаю: надішли PDF, фото або текст."},
    "dl_fail": {"en": "Couldn't download the file, please try again.", "de": "Die Datei ließ sich nicht laden, versuch es noch einmal.",
                "uk": "Не вдалося завантажити файл, спробуй ще раз."},
    "voice": {"en": "I can't handle voice messages yet — please type.", "de": "Sprachnachrichten verstehe ich noch nicht — bitte schreib.",
              "uk": "Голосові поки не розбираю — напиши текстом."},
    "look": {"en": "Take a look at the attachment and tell me what to do with it.",
             "de": "Schau dir den Anhang an und sag mir, was ich damit machen soll.",
             "uk": "Подивись вкладення і скажи, що з ним робити."},
    "consulted": {"en": "asked: ", "de": "hinzugezogen: ", "uk": "покликала: "},
    "changed": {"en": "dashboard updated", "de": "Dashboard aktualisiert", "uk": "дашборд оновлено"},
    "stumbled": {"en": "The team stumbled: {e}", "de": "Das Team ist gestolpert: {e}", "uk": "Команда спіткнулася: {e}"},
}


def tr(c, key, **kw):
    s = TG[key][i18n.norm(c.get("lang"))]
    return s.format(**kw) if kw else s


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
            return send(token, chat_id, tr(c, "need_start"))
        store.update_client(cid, tg_chat_id=chat_id)
        c["tg_chat_id"] = chat_id
        return send(token, chat_id, tr(c, "bound", name=c["name"]) + "\n\n" + tr(c, "help"))
    if chat_id != c["tg_chat_id"]:
        return  # чужой чат — молчим

    team = i18n.agents(c.get("lang"), brain.AGENTS)
    if text in ("/start", "/help"):
        return send(token, chat_id, tr(c, "help"))
    if text == "/team":
        return send(token, chat_id, "\n".join(f"{a['emoji']} {a['name']} — {a['role']} (/agent {k})"
                                              for k, a in team.items()))
    if text == "/budget":
        return send(token, chat_id, tr(c, "budget", a=f"{store.spent_this_month(cid):.2f}", b=f"{c['monthly_budget']:.2f}"))
    if text == "/maya" or text.startswith("/agent"):
        want = "maya" if text == "/maya" else (text.split(maxsplit=1)[1:] or [""])[0].strip().lower()
        if want not in brain.AGENTS:
            return send(token, chat_id, tr(c, "unknown_agent"))
        _agent_of[cid] = want
        a = team[want]
        return send(token, chat_id, f"{a['emoji']} " + tr(c, "now", name=a["name"], role=a["role"]))

    deep = False
    if text.startswith("/deep"):
        deep, text = True, text[5:].strip()

    atts = []
    try:
        if msg.get("photo"):
            raw, _ = download(token, msg["photo"][-1]["file_id"])
            atts.append({"name": tr(c, "photo"), "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()})
        doc = msg.get("document")
        if doc:
            mt = doc.get("mime_type", "")
            raw, _ = download(token, doc["file_id"])
            if mt == "application/pdf" or mt.startswith("image/"):
                atts.append({"name": doc.get("file_name", "file"), "media_type": mt, "data": base64.b64encode(raw).decode()})
            elif mt.startswith("text/") or mt in ("application/json",):
                atts.append({"name": doc.get("file_name", "file"), "media_type": "text/plain",
                             "text": raw.decode("utf-8", "replace")})
            else:
                return send(token, chat_id, tr(c, "file_type"))
    except Exception as e:  # noqa: BLE001
        log.warning("download: %s", e)
        return send(token, chat_id, tr(c, "dl_fail"))
    if msg.get("voice") or msg.get("audio"):
        return send(token, chat_id, tr(c, "voice"))
    if not text and not atts:
        return
    if not text:
        text = tr(c, "look")

    tg(token, "sendChatAction", chat_id=chat_id, action="typing")
    try:
        res = brain.chat(cid, _agent_of.get(cid, "maya"), text, attachments=atts, deep=deep)
        tail = []
        if res["consulted"]:
            tail.append(tr(c, "consulted") + ", ".join(team[a]["name"] for a in res["consulted"]))
        if res["changed"]:
            tail.append(tr(c, "changed"))
        send(token, chat_id, res["text"] + (f"\n\n— {' · '.join(tail)}" if tail else ""))
    except brain.BudgetExceeded as e:
        send(token, chat_id, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("chat")
        send(token, chat_id, tr(c, "stumbled", e=e))


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
