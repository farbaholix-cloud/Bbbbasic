"""
Команда работает сама, без вопросов клиента.

  • Радар возможностей: раз в неделю Рубен ищет конкурсы, гранты, open calls и
    резиденции — не для каждого клиента отдельно, а для связки «ремесло + страна»
    (dance+de, mural+any…). Найденное ложится в общий каталог (таблица
    opportunities): один поиск обслуживает всех похожих клиентов.
  • Подборка: раз в неделю каждому активному клиенту — новые подходящие
    возможности из каталога: в дашборд (список «Радар возможностей»), в чат от
    Майи и в его Telegram-бот. Без вызовов модели — шаблоном, бесплатно.
  • Напоминания: каждый день — дедлайны из списков дашборда за 14, 7 и 2 дня.

Всё это крутит фоновый поток сервера (start()); вручную — из админки.
"""

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import brain
import i18n
import plans
import store

log = logging.getLogger("backstage.proactive")

RADAR_PER_DAY = int(os.environ.get("BACKSTAGE_RADAR_PER_DAY", "4"))   # поисков в день — потолок расхода
RADAR_EVERY_DAYS = 7
DIGEST_EVERY_DAYS = 6.5
DIGEST_SIZE = 5
REMIND_DAYS = (14, 7, 2)
RUN_HOUR = int(os.environ.get("BACKSTAGE_PROACTIVE_HOUR", "7"))
_lock = threading.Lock()


def prefs(c):
    try:
        p = json.loads(c.get("prefs") or "{}")
    except Exception:
        p = {}
    return {"radar": p.get("radar", True), "reminders": p.get("reminders", True)}


def country(c):
    try:
        v = json.loads(c.get("survey") or "{}").get("answers", {}).get("practice", {}).get("country")
    except Exception:
        v = None
    return v if v in ("de", "at", "ch", "ua", "eu") else "any"


def regions(cn):
    return {"any": ["intl", "eu"], "ua": ["ua", "eu", "intl"]}.get(cn, [cn, "eu", "intl"])


def crafts(c):
    return [x for x in (c.get("craft") or "").split(",") if x][:2] or ["other"]


def _eligible(c):
    return not plans.status(c)["expired"]


# ─── радар ───────────────────────────────────────────────────────────────────

def clusters_due(force=False):
    """Связки «ремесло + страна» активных клиентов, которые пора обновить."""
    seen = {}
    for c in store.active_clients():
        if not _eligible(c) or not prefs(c)["radar"]:
            continue
        for cr in crafts(c):
            seen[(cr, country(c))] = True
    due = []
    for cr, cn in seen:
        last = float(store.meta_get(f"radar:{cr}:{cn}", "0") or 0)
        if force or time.time() - last > RADAR_EVERY_DAYS * 86400:
            due.append((cr, cn, last))
    due.sort(key=lambda x: x[2])  # давно не обновлявшиеся — первыми
    return [(cr, cn) for cr, cn, _ in due]


def run_radar(limit=RADAR_PER_DAY, force=False):
    done = 0
    for cr, cn in clusters_due(force)[:limit]:
        try:
            items = brain.radar_search(cr, cn)
            for it in items:
                store.add_opportunity(it, cr, "intl" if cn == "any" else cn)
            store.meta_set(f"radar:{cr}:{cn}", str(time.time()))
            log.info("radar %s/%s: %d возможностей", cr, cn, len(items))
            done += 1
        except Exception as e:  # noqa: BLE001 — одна связка не должна ронять остальные
            log.error("radar %s/%s: %s", cr, cn, e)
    return done


# ─── подборка клиенту ────────────────────────────────────────────────────────

def _radar_widget(c):
    for w in store.list_widgets(c["id"]):
        if w["kind"] == "list" and w["config"].get("radar"):
            return w
    wid = store.add_widget(c["id"], "list", i18n.t(c["lang"], "radar_title"), {"radar": True}, {"items": []}, "m")
    return store.get_widget(c["id"], wid)


def tg_send(c, text):
    if not (c.get("tg_token") and c.get("tg_chat_id")):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": c["tg_chat_id"], "text": text.replace("**", ""),
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{c['tg_token']}/sendMessage", data=data, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("tg notify %s: %s", c["slug"], e)


def digest(c, force=False):
    """Отправить клиенту новые подходящие возможности. Возвращает, сколько отправлено."""
    if not prefs(c)["radar"] or not _eligible(c):
        return 0
    last = float(store.meta_get(f"digest:{c['id']}", "0") or 0)
    if not force and time.time() - last < DIGEST_EVERY_DAYS * 86400:
        return 0
    soon = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")  # с дедлайном через день-два уже не успеть
    opps = store.match_opportunities(c["id"], crafts(c), regions(country(c)), DIGEST_SIZE, soon)
    if not opps:
        return 0
    L = i18n.norm(c["lang"])
    w = _radar_widget(c)
    items = w["data"].get("items") or []
    nid = max([i.get("id", 0) for i in items] or [0])
    lines = []
    for k, o in enumerate(opps, 1):
        label = f"[{o['title']}]({o['url']})" if o["url"] else o["title"]
        items.append({"id": nid + k, "text": label + (f" — {o['org']}" if o["org"] else ""),
                      "date": o["deadline"], "done": False})
        bits = [x for x in (o["org"], o["amount"], i18n.t(L, "deadline_on", d=o["deadline"]) if o["deadline"] else "") if x]
        lines.append(f"- **{label}**" + (f" · {' · '.join(bits)}" if bits else "")
                     + (f"\n  {o['summary']}" if L == "en" and o["summary"] else ""))
    store.update_widget(c["id"], w["id"], data={**w["data"], "items": items[-40:]})
    text = i18n.t(L, "radar_intro", n=len(opps)) + "\n\n" + "\n".join(lines) + "\n\n" + i18n.t(L, "radar_outro")
    store.add_message(c["id"], "maya", "assistant", text, {"kind": "radar", "changed": True})
    store.mark_delivered(c["id"], [o["id"] for o in opps])
    store.meta_set(f"digest:{c['id']}", str(time.time()))
    tg_send(c, text)
    return len(opps)


# ─── напоминания о дедлайнах ─────────────────────────────────────────────────

def reminders(c):
    if not prefs(c)["reminders"]:
        return 0
    today = datetime.now().date()
    L = i18n.norm(c["lang"])
    lines = []
    for w in store.list_widgets(c["id"]):
        if w["kind"] != "list" or w["config"].get("radar"):
            continue  # находки радара — не обязательства, по ним не дёргаем
        for it in w["data"].get("items") or []:
            if it.get("done") or not it.get("date"):
                continue
            try:
                left = (datetime.strptime(it["date"], "%Y-%m-%d").date() - today).days
            except ValueError:
                continue
            hit = next((d for d in REMIND_DAYS if left == d), None)
            if hit and store.notice_once(c["id"], f"{w['id']}:{it.get('id')}:{hit}"):
                lines.append(f"- **{it['text']}** — {i18n.t(L, 'in_days', n=left, d=it['date'])}")
    for a in store.list_apps(c["id"]):
        if a["status"] not in ("idea", "preparing") or not a["deadline"]:
            continue
        try:
            left = (datetime.strptime(a["deadline"], "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        hit = next((d for d in REMIND_DAYS if left == d), None)
        if hit and store.notice_once(c["id"], f"app:{a['id']}:{hit}"):
            lines.append(f"- **{a['title']}** — {i18n.t(L, 'in_days', n=left, d=a['deadline'])}")
    if not lines:
        return 0
    text = i18n.t(L, "remind_intro") + "\n\n" + "\n".join(lines) + "\n\n" + i18n.t(L, "remind_outro")
    store.add_message(c["id"], "maya", "assistant", text, {"kind": "reminder"})
    tg_send(c, text)
    return len(lines)


# ─── расписание ──────────────────────────────────────────────────────────────

def daily(force=False):
    """Раз в день: радар → подборки → напоминания. Возвращает короткий отчёт."""
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    try:
        n_radar = run_radar(force=force)
        n_dig = n_rem = 0
        for c in store.active_clients():
            if not _eligible(c):
                continue
            try:
                n_dig += digest(c, force=force)
                n_rem += reminders(c)
            except Exception as e:  # noqa: BLE001
                log.error("proactive %s: %s", c["slug"], e)
        log.info("proactive: радар %d, в подборках %d, напоминаний %d", n_radar, n_dig, n_rem)
        return {"radar": n_radar, "digest": n_dig, "reminders": n_rem}
    finally:
        _lock.release()


def _loop():
    time.sleep(60)
    while True:
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            if datetime.now().hour >= RUN_HOUR and store.meta_get("proactive_day") != day:
                store.meta_set("proactive_day", day)
                daily()
        except Exception as e:  # noqa: BLE001
            log.error("proactive loop: %s", e)
        time.sleep(1200)


def start():
    if os.environ.get("BACKSTAGE_PROACTIVE", "1") == "1":
        threading.Thread(target=_loop, daemon=True, name="proactive").start()
