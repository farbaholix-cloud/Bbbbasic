"""Telegram-бот Inspire: связь руководителя со 110 танцорами, учёт и файлы проектов.

    python bot.py

Руководитель (ADMIN_IDS в .env):
  /svodka            сводка JPEG размером с экран iPhone (каждый день приходит сама в DAILY_AT)
  /dash              ссылка на пульт
  /plus 1200 Свадьба Мюллер     поступление        /minus 300 аренда зала     расход
  /projects          ближайшие проекты              /newproject 24.10.2026; Шоу в Alte Oper; 3500; 8
  /call 42           собрать состав на проект 42 (кнопки «Буду / Не буду / Не знаю» танцорам Pro и Show)
  /note Skyline: обсудили тайминг, ждут КП    запись в CRM
  /debts             кто не доплатил             /invites    файл со ссылками для неподключённых
  /all текст         рассылка всем               /group Pro текст   рассылка группе
  Любой файл (фото, видео, PDF, аудио, голос) → бот спросит, к какому проекту его прикрепить.
  Ответ (reply) на пересланное сообщение танцора → уходит этому танцору.

Танцор:
  /start <код>  подключение по личной ссылке      /me  мой профиль, посещаемость, гонорары
  /schedule     расписание моей группы           /absent причина   предупредить о пропуске
  Любой текст или файл → руководителю.
"""
import asyncio
import io
import logging
import os
import re
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters)

import db
import stats
import summary
from config import ADMIN_IDS, BOT_TOKEN, BOT_USERNAME, CURRENCY, DAILY_AT, PUBLIC_URL, STORAGE, TIMEZONE, DASH_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inspire")
TZ = ZoneInfo(TIMEZONE)
HTML = ParseMode.HTML

INC_WORDS = {"абонем": "Абонементы", "мастер": "Мастер-классы", "грант": "Гранты", "förder": "Гранты"}
EXP_WORDS = {"аренд": "Аренда зала", "зал": "Аренда зала", "костюм": "Костюмы", "такси": "Транспорт",
             "транспорт": "Транспорт", "бенз": "Транспорт", "реклам": "Реклама", "таргет": "Реклама",
             "музык": "Музыка и лицензии", "хореограф": "Хореографы", "гонорар танц": "Выплаты танцорам",
             "выплат": "Выплаты танцорам", "свет": "Оборудование", "колонк": "Оборудование"}


def is_admin(u):
    return u and u.id in ADMIN_IDS


def money(x):
    return stats.money(x, CURRENCY)


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def dancer_by_tg(tg_id):
    return db.one("SELECT * FROM dancers WHERE tg_id=?", (tg_id,))


def esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── старт и подключение танцоров ─────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if is_admin(u):
        return await update.message.reply_text(
            "👋 Пульт руководителя <b>Inspire</b>.\n\n"
            "/svodka — сводка картинкой\n/dash — веб-пульт\n/plus, /minus — деньги\n/projects, /newproject — проекты\n"
            "/call — собрать состав\n/note — запись в CRM\n/all, /group — рассылки\n/debts — должники\n"
            "/invites — ссылки для неподключённых\n\n📎 Пришлите любой файл — прикреплю к проекту.", parse_mode=HTML)
    code = ctx.args[0] if ctx.args else None
    d = dancer_by_tg(u.id)
    if not d and code:
        d = db.one("SELECT * FROM dancers WHERE invite_code=?", (code,))
        if d and d["tg_id"] and d["tg_id"] != u.id:
            return await update.message.reply_text("Эта ссылка уже привязана к другому аккаунту. Напишите руководителю.")
        if d:
            db.execute("UPDATE dancers SET tg_id=?, tg_username=? WHERE id=?", (u.id, u.username, d["id"]))
            for a in ADMIN_IDS:
                await ctx.bot.send_message(a, f"✅ Подключился(лась): <b>{esc(d['name'])}</b> · {d['group_name']}", parse_mode=HTML)
    if not d:
        return await update.message.reply_text(
            "Привет! Это бот танцевального коллектива Inspire 💃\n"
            "Чтобы подключиться, откройте личную ссылку, которую прислал руководитель.")
    await update.message.reply_text(
        f"Привет, {esc(d['name'].split()[0])}! Ты в базе Inspire · группа <b>{d['group_name']}</b> 🔥\n\n"
        "/me — мой профиль\n/schedule — расписание\n/absent — предупредить о пропуске\n\n"
        "Просто напиши сюда — сообщение получит руководитель. Видео отработки, фото, документы — тоже сюда.",
        parse_mode=HTML)


async def me(update: Update, ctx):
    d = dancer_by_tg(update.effective_user.id)
    if not d:
        return await update.message.reply_text("Сначала подключитесь по личной ссылке от руководителя.")
    att = db.one("""SELECT AVG(a.present)*100 p, COUNT(*) n FROM attendance a JOIN rehearsals r ON r.id=a.rehearsal_id
                    WHERE a.dancer_id=? AND r.date>=?""", (d["id"], (date.today() - timedelta(days=30)).isoformat()))
    fees = db.one("""SELECT SUM(s.fee) f, COUNT(*) n FROM assignments s JOIN projects p ON p.id=s.project_id
                     WHERE s.dancer_id=? AND s.status='confirmed' AND p.status='выполнен' AND p.date>=?""",
                  (d["id"], date.today().replace(month=1, day=1).isoformat()))
    up = db.rows("""SELECT p.title, p.date, p.venue, s.status FROM assignments s JOIN projects p ON p.id=s.project_id
                    WHERE s.dancer_id=? AND p.date>=? AND p.status!='отменён' ORDER BY p.date LIMIT 5""",
                 (d["id"], date.today().isoformat()))
    st = {"confirmed": "✅", "yes": "👍", "maybe": "🤔", "no": "❌", "invited": "❔"}
    txt = (f"<b>{esc(d['name'])}</b> · {d['group_name']} · {esc(d['style'] or '')}\n"
           f"📊 Посещаемость за 30 дней: <b>{(att['p'] or 0):.0f}%</b> ({att['n']} репетиций)\n"
           f"💶 Гонорары в этом году: <b>{money(fees['f'] or 0)}</b> за {fees['n']} выступл.\n")
    if up:
        txt += "\n<b>Мои ближайшие проекты:</b>\n" + "\n".join(
            f"{st.get(x['status'], '')} {x['date'][8:]}.{x['date'][5:7]} {esc(x['title'])} · {esc(x['venue'])}" for x in up)
    await update.message.reply_text(txt, parse_mode=HTML)


async def schedule(update: Update, ctx):
    d = dancer_by_tg(update.effective_user.id)
    g = d["group_name"] if d else (ctx.args[0] if ctx.args else None)
    q = "SELECT date,time,group_name,place FROM rehearsals WHERE date>=? AND date<=?"
    args = [date.today().isoformat(), (date.today() + timedelta(days=7)).isoformat()]
    if g:
        q += " AND group_name=?"
        args.append(g)
    rs = db.rows(q + " ORDER BY date,time", args)
    if not rs:
        return await update.message.reply_text("На неделе репетиций нет.")
    wd = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    await update.message.reply_text("🗓 <b>Репетиции на неделю</b>\n" + "\n".join(
        f"{wd[date.fromisoformat(r['date']).weekday()]} {r['date'][8:]}.{r['date'][5:7]} · {r['time']} · {r['group_name']} · {esc(r['place'])}"
        for r in rs), parse_mode=HTML)


async def absent(update: Update, ctx):
    d = dancer_by_tg(update.effective_user.id)
    if not d:
        return
    reason = " ".join(ctx.args) or "без причины"
    nxt = db.one("SELECT id,date,time FROM rehearsals WHERE group_name=? AND date>=? ORDER BY date,time LIMIT 1",
                 (d["group_name"], date.today().isoformat()))
    if nxt:
        db.execute("INSERT OR REPLACE INTO attendance(rehearsal_id,dancer_id,present,reason) VALUES(?,?,0,?)",
                   (nxt["id"], d["id"], reason))
    db.execute("INSERT INTO messages(dancer_id,date,direction,text,kind) VALUES(?,?,'in',?,'absence')",
               (d["id"], now(), f"Пропуск: {reason}"))
    for a in ADMIN_IDS:
        await ctx.bot.send_message(a, f"🚫 <b>{esc(d['name'])}</b> ({d['group_name']}) пропустит "
                                      f"{nxt['date'][8:] + '.' + nxt['date'][5:7] + ' ' + nxt['time'] if nxt else 'репетицию'}: {esc(reason)}",
                                   parse_mode=HTML)
    await update.message.reply_text("Принято, руководитель предупреждён. Выздоравливай / до встречи! 🙌")


# ── сводка ───────────────────────────────────────────────────────────────────
async def send_summary(bot, chat_id):
    try:
        path = await asyncio.to_thread(summary.render_jpeg)
        with open(path, "rb") as f:
            await bot.send_photo(chat_id, f, caption=summary.text_summary()[:1024], parse_mode=HTML)
    except Exception as e:  # если браузер на сервере не установлен — хотя бы текст
        log.exception("summary render")
        await bot.send_message(chat_id, summary.text_summary() + f"\n\n⚠️ Картинка не собралась: {e}", parse_mode=HTML)


async def svodka(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    await update.message.reply_text("Собираю сводку… ⏳")
    await send_summary(ctx.bot, update.effective_chat.id)


async def daily(ctx: ContextTypes.DEFAULT_TYPE):
    for a in ADMIN_IDS:
        await send_summary(ctx.bot, a)
    # поздравления танцорам с днём рождения — от имени коллектива
    md = date.today().strftime("-%m-%d")
    for d in db.rows("SELECT name, tg_id FROM dancers WHERE tg_id IS NOT NULL AND status!='left' AND substr(birthday,5)=?", (md,)):
        try:
            await ctx.bot.send_message(d["tg_id"], f"🎂 {esc(d['name'].split()[0])}, с днём рождения от всей семьи Inspire! "
                                                   "Пусть каждый выход на сцену будет как первый 💫")
        except Exception:
            pass


async def dash(update: Update, ctx):
    if is_admin(update.effective_user):
        await update.message.reply_text(f"🖥 Пульт: {PUBLIC_URL}/" + (f"?key={DASH_KEY}" if DASH_KEY else ""))


# ── деньги ───────────────────────────────────────────────────────────────────
def guess_cat(text, words, default):
    t = text.lower()
    for k, v in words.items():
        if k in t:
            return v
    return default


def find_project(text):
    """Пытаемся привязать платёж к проекту по имени заказчика/названию."""
    for w in sorted(re.findall(r"[\wÄÖÜäöüß-]{4,}", text), key=len, reverse=True):
        p = db.one("""SELECT p.id, p.client_id, p.title, c.company, c.name FROM projects p LEFT JOIN clients c ON c.id=p.client_id
                      WHERE (c.company LIKE ? OR c.name LIKE ? OR p.title LIKE ?) AND p.status IN ('подтверждён','выполнен')
                      ORDER BY ABS(julianday(p.date)-julianday('now')) LIMIT 1""", (f"%{w}%",) * 3)
        if p:
            return p
    return None


async def money_cmd(update: Update, ctx, direction):
    if not is_admin(update.effective_user):
        return
    if not ctx.args:
        return await update.message.reply_text(f"Пример: /{'plus 1200 Свадьба Мюллер' if direction == 'in' else 'minus 300 аренда зала'}")
    try:
        amount = float(ctx.args[0].replace(",", "."))
    except ValueError:
        return await update.message.reply_text("Первым словом должна быть сумма, например /plus 1200 Skyline")
    note = " ".join(ctx.args[1:])
    p = find_project(note) if direction == "in" else None
    cat = guess_cat(note, INC_WORDS, "Гонорары") if direction == "in" else guess_cat(note, EXP_WORDS, "Прочее")
    db.execute("INSERT INTO transactions(date,amount,direction,category,project_id,client_id,method,note,created_by)"
               " VALUES(?,?,?,?,?,?,?,?,'бот')",
               (date.today().isoformat(), amount, direction, cat, p and p["id"], p and p["client_id"], "банк", note))
    s = stats.collect()
    await update.message.reply_text(
        f"{'💶 +' if direction == 'in' else '💸 −'}{money(amount)} · {cat}"
        + (f"\n🔗 Проект: {esc(p['title'])} · {esc(p['company'] or p['name'])}" if p else "")
        + f"\n\nМесяц: {money(s['income_month'])} приход · {money(s['profit_month'])} прибыль", parse_mode=HTML)


async def plus(update, ctx):
    await money_cmd(update, ctx, "in")


async def minus(update, ctx):
    await money_cmd(update, ctx, "out")


async def debts(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    s = stats.collect()
    if not s["debtors"]:
        return await update.message.reply_text("Все расплатились 🎉")
    await update.message.reply_text("⏳ <b>Ждём оплату</b>\n" + "\n".join(
        f"• {esc(x['company'] or x['name'])} — {money(x['due'])} ({esc(x['title'])}, {x['date'][8:]}.{x['date'][5:7]})"
        for x in s["debtors"]) + f"\n\nИтого: <b>{money(s['receivables'])}</b>", parse_mode=HTML)


# ── проекты и CRM ────────────────────────────────────────────────────────────
async def projects(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    ps = db.rows("""SELECT p.id,p.title,p.date,p.status,p.budget,p.dancers_needed,c.company,c.name,
                      (SELECT COUNT(*) FROM assignments a WHERE a.project_id=p.id AND a.status IN ('yes','confirmed')) r
                    FROM projects p LEFT JOIN clients c ON c.id=p.client_id
                    WHERE p.date>=? AND p.status NOT IN ('отменён') ORDER BY p.date LIMIT 12""", (date.today().isoformat(),))
    await update.message.reply_text("📁 <b>Ближайшие проекты</b>\n" + "\n".join(
        f"<code>#{p['id']}</code> {p['date'][8:]}.{p['date'][5:7]} {esc(p['title'])} · {esc(p['company'] or p['name'])} · "
        f"{money(p['budget'])} · {p['status']} · 👥 {p['r']}/{p['dancers_needed']}" for p in ps), parse_mode=HTML)


async def newproject(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    parts = [x.strip() for x in " ".join(ctx.args).split(";")]
    if len(parts) < 2:
        return await update.message.reply_text("Формат: /newproject 24.10.2026; Шоу в Alte Oper; 3500; 8")
    try:
        dt = datetime.strptime(parts[0], "%d.%m.%Y").date()
    except ValueError:
        return await update.message.reply_text("Дата в формате ДД.ММ.ГГГГ, например 24.10.2026")
    pid = db.execute("INSERT INTO projects(title,date,status,budget,dancers_needed,created_on) VALUES(?,?,'переговоры',?,?,?)",
                     (parts[1], dt.isoformat(), float(parts[2]) if len(parts) > 2 and parts[2] else 0,
                      int(parts[3]) if len(parts) > 3 and parts[3] else 0, date.today().isoformat()))
    await update.message.reply_text(f"Проект <code>#{pid}</code> создан. Заказчика и детали можно дописать в пульте.\n"
                                    f"Собрать состав: /call {pid}", parse_mode=HTML)


async def call(update: Update, ctx):
    """Опрос готовности танцоров на проект — кнопки прямо в личке у каждого."""
    if not is_admin(update.effective_user) or not ctx.args:
        return await update.message.reply_text("Формат: /call 42  (номер из /projects). Можно добавить группы: /call 42 Pro Show Adults")
    p = db.one("SELECT * FROM projects WHERE id=?", (int(ctx.args[0]),))
    if not p:
        return await update.message.reply_text("Нет такого проекта")
    groups = ctx.args[1:] or ["Pro", "Show"]
    ds = db.rows(f"SELECT id,tg_id FROM dancers WHERE status='active' AND tg_id IS NOT NULL AND group_name IN ({','.join('?' * len(groups))})", groups)
    kb = KB([[B("✅ Буду", callback_data=f"call:{p['id']}:yes"), B("❌ Не смогу", callback_data=f"call:{p['id']}:no"),
              B("🤔 Не знаю", callback_data=f"call:{p['id']}:maybe")]])
    n = 0
    for d in ds:
        db.execute("INSERT OR IGNORE INTO assignments(project_id,dancer_id,status) VALUES(?,?,'invited')", (p["id"], d["id"]))
        try:
            await ctx.bot.send_message(d["tg_id"], f"⭐ <b>{esc(p['title'])}</b>\n📅 {p['date'][8:]}.{p['date'][5:7]} · {esc(p['venue'] or '')}\n"
                                                   f"Нужно {p['dancers_needed']} танцоров. Ты с нами?", reply_markup=kb, parse_mode=HTML)
            n += 1
        except Exception:
            pass
    await update.message.reply_text(f"Отправил {n} танцорам ({', '.join(groups)}). Ответы будут приходить сюда.")


async def on_call_answer(update: Update, ctx):
    q = update.callback_query
    _, pid, ans = q.data.split(":")
    d = dancer_by_tg(q.from_user.id)
    if not d:
        return await q.answer("Вы не подключены")
    db.execute("INSERT INTO assignments(project_id,dancer_id,status) VALUES(?,?,?) "
               "ON CONFLICT(project_id,dancer_id) DO UPDATE SET status=excluded.status", (int(pid), d["id"], ans))
    p = db.one("""SELECT title,dancers_needed,(SELECT COUNT(*) FROM assignments WHERE project_id=? AND status IN ('yes','confirmed')) r
                  FROM projects WHERE id=?""", (int(pid), int(pid)))
    await q.answer("Записал!")
    await q.edit_message_reply_markup(None)
    await q.message.reply_text({"yes": "🔥 Ты в составе (предварительно). Детали пришлю позже.",
                                "no": "Понял, в следующий раз!", "maybe": "Ок, дай знать, как определишься: /me"}[ans])
    for a in ADMIN_IDS:
        await ctx.bot.send_message(a, f"{ {'yes': '✅', 'no': '❌', 'maybe': '🤔'}[ans]} {esc(d['name'])} → {esc(p['title'])} "
                                      f"· состав {p['r']}/{p['dancers_needed']}", parse_mode=HTML)


async def on_rsvp(update: Update, ctx):
    q = update.callback_query
    d = dancer_by_tg(q.from_user.id)
    ans = q.data.split(":")[1]
    await q.answer("Спасибо!")
    await q.edit_message_reply_markup(None)
    if d:
        db.execute("INSERT INTO messages(dancer_id,date,direction,text,kind) VALUES(?,?,'in',?,'poll')",
                   (d["id"], now(), {"yes": "✅ Буду", "no": "❌ Не буду", "maybe": "🤔 Пока не знаю"}[ans]))


async def note(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    txt = " ".join(ctx.args)
    if ":" not in txt:
        return await update.message.reply_text("Формат: /note Skyline: обсудили тайминг, ждут КП до пятницы")
    who, summ = [x.strip() for x in txt.split(":", 1)]
    c = db.one("SELECT id, company, name FROM clients WHERE company LIKE ? OR name LIKE ? LIMIT 1", (f"%{who}%",) * 2)
    if not c:
        cid = db.execute("INSERT INTO clients(name,kind,created_on,source) VALUES(?,?,?,?)", (who, "частный", date.today().isoformat(), "Telegram"))
        c = {"id": cid, "company": None, "name": who}
    db.execute("INSERT INTO communications(client_id,date,channel,direction,summary) VALUES(?,?,?,?,?)",
               (c["id"], date.today().isoformat(), "звонок", "out", summ))
    await update.message.reply_text(f"📝 Записал в историю «{esc(c['company'] or c['name'])}». Напоминание «что дальше» ставится в пульте.",
                                    parse_mode=HTML)


async def invites(update: Update, ctx):
    if not is_admin(update.effective_user):
        return
    ds = db.rows("SELECT name, group_name, phone, invite_code FROM dancers WHERE tg_id IS NULL AND status!='left' ORDER BY group_name, name")
    if not ds:
        return await update.message.reply_text("Все 100% танцоров уже в боте 🎉")
    csv = "Имя;Группа;Телефон;Ссылка\n" + "\n".join(
        f"{d['name']};{d['group_name']};{d['phone'] or ''};https://t.me/{BOT_USERNAME}?start={d['invite_code']}" for d in ds)
    await update.message.reply_document(io.BytesIO(csv.encode("utf-8-sig")), filename="inspire_invites.csv",
                                        caption=f"{len(ds)} танцоров ещё не подключены. Отправьте каждому его ссылку в WhatsApp/SMS.")


# ── рассылки ─────────────────────────────────────────────────────────────────
async def broadcast(update: Update, ctx, group=None, text=None):
    q, args = "SELECT tg_id FROM dancers WHERE status='active' AND tg_id IS NOT NULL", []
    if group:
        q += " AND group_name=?"
        args.append(group)
    n = 0
    for r in db.rows(q, args):
        try:
            await ctx.bot.send_message(r["tg_id"], f"📣 {esc(text)}", parse_mode=HTML)
            n += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)  # Telegram: не больше ~30 сообщений в секунду
    db.execute("INSERT INTO messages(dancer_id,date,direction,text,kind,is_read) VALUES(NULL,?,'broadcast',?,'broadcast',1)", (now(), text))
    await update.message.reply_text(f"📣 Доставлено: {n}")


async def all_cmd(update: Update, ctx):
    if is_admin(update.effective_user) and ctx.args:
        await broadcast(update, ctx, None, " ".join(ctx.args))


async def group_cmd(update: Update, ctx):
    if is_admin(update.effective_user) and len(ctx.args) > 1:
        await broadcast(update, ctx, ctx.args[0], " ".join(ctx.args[1:]))


# ── файлы → проекты ──────────────────────────────────────────────────────────
def _file_of(msg):
    if msg.photo:
        return msg.photo[-1], "photo", f"photo_{msg.photo[-1].file_unique_id}.jpg"
    for kind in ("video", "document", "audio", "voice", "video_note", "animation"):
        f = getattr(msg, kind)
        if f:
            ext = {"video": "mp4", "audio": "mp3", "voice": "ogg", "video_note": "mp4", "animation": "mp4"}.get(kind, "bin")
            return f, kind, getattr(f, "file_name", None) or f"{kind}_{f.file_unique_id}.{ext}"
    return None, None, None


async def on_file(update: Update, ctx):
    msg = update.message
    f, kind, name = _file_of(msg)
    u = update.effective_user
    d = None if is_admin(u) else dancer_by_tg(u.id)
    if not is_admin(u) and not d:
        return
    if d:
        ps = db.rows("""SELECT p.id,p.title,p.date FROM assignments a JOIN projects p ON p.id=a.project_id
                        WHERE a.dancer_id=? AND p.date>=? ORDER BY p.date LIMIT 6""",
                     (d["id"], (date.today() - timedelta(days=30)).isoformat()))
    else:
        ps = db.rows("""SELECT id,title,date FROM projects WHERE status!='отменён' AND date>=? ORDER BY ABS(julianday(date)-julianday('now')) LIMIT 8""",
                     ((date.today() - timedelta(days=45)).isoformat(),))
    key = f"{msg.chat_id}:{msg.message_id}"
    ctx.bot_data.setdefault("pending", {})[key] = {"file_id": f.file_id, "kind": kind, "name": name, "size": f.file_size,
                                                    "caption": msg.caption, "by": "руководитель" if d is None else d["name"]}
    rows = [[B(f"{p['date'][8:]}.{p['date'][5:7]} · {p['title'][:34]}", callback_data=f"file:{key}:{p['id']}")] for p in ps]
    rows.append([B("📂 Общий архив (без проекта)", callback_data=f"file:{key}:0")])
    await msg.reply_text("К какому проекту прикрепить файл?", reply_markup=KB(rows))


async def on_file_choice(update: Update, ctx):
    q = update.callback_query
    _, chat, mid, pid = q.data.split(":")
    item = ctx.bot_data.get("pending", {}).pop(f"{chat}:{mid}", None)
    if not item:
        return await q.answer("Файл уже сохранён или устарел")
    pid = int(pid) or None
    folder = os.path.join(STORAGE, "projects", str(pid or "general"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{datetime.now():%Y%m%d_%H%M%S}_{os.path.basename(item['name'])}")
    try:
        tf = await ctx.bot.get_file(item["file_id"])  # Telegram отдаёт ботам файлы до 20 МБ
        await tf.download_to_drive(path)
    except Exception as e:
        path = None  # большой файл: храним ссылку на file_id, сам файл остаётся в Telegram
        log.warning("download: %s", e)
    db.execute("INSERT INTO files(project_id,date,uploaded_by,kind,filename,path,size,tg_file_id,caption) VALUES(?,?,?,?,?,?,?,?,?)",
               (pid, date.today().isoformat(), item["by"], item["kind"], item["name"], path, item["size"], item["file_id"], item["caption"]))
    title = db.one("SELECT title FROM projects WHERE id=?", (pid,))["title"] if pid else "Общий архив"
    await q.answer("Сохранено")
    await q.edit_message_text(f"📎 Сохранено в «{title}»" + ("" if path else " (большой файл — хранится в Telegram)"))
    if item["by"] != "руководитель":
        for a in ADMIN_IDS:
            await ctx.bot.send_message(a, f"📎 {esc(item['by'])} загрузил(а) файл в «{esc(title)}»", parse_mode=HTML)
            await ctx.bot.copy_message(a, int(chat), int(mid))


# ── переписка танцор ↔ руководитель ──────────────────────────────────────────
async def on_text(update: Update, ctx):
    msg, u = update.message, update.effective_user
    if is_admin(u):
        r = msg.reply_to_message
        if r:
            m = db.one("SELECT dancer_id FROM messages WHERE admin_msg_id=? ORDER BY id DESC LIMIT 1", (r.message_id,))
            if m:
                d = db.one("SELECT tg_id,name FROM dancers WHERE id=?", (m["dancer_id"],))
                await ctx.bot.send_message(d["tg_id"], f"💬 <b>Руководитель:</b>\n{esc(msg.text)}", parse_mode=HTML)
                db.execute("INSERT INTO messages(dancer_id,date,direction,text,is_read) VALUES(?,?,'out',?,1)", (m["dancer_id"], now(), msg.text))
                db.execute("UPDATE messages SET is_read=1 WHERE dancer_id=? AND direction='in'", (m["dancer_id"],))
                return await msg.reply_text(f"✓ Отправлено: {esc(d['name'])}")
        return await msg.reply_text("Чтобы ответить танцору — сделайте reply на его сообщение. Команды: /start")
    d = dancer_by_tg(u.id)
    if not d:
        return await msg.reply_text("Подключитесь по личной ссылке от руководителя 🙏")
    mid = db.execute("INSERT INTO messages(dancer_id,date,direction,text) VALUES(?,?,'in',?)", (d["id"], now(), msg.text))
    for a in ADMIN_IDS:
        sent = await ctx.bot.send_message(a, f"💬 <b>{esc(d['name'])}</b> · {d['group_name']}\n{esc(msg.text)}\n\n<i>reply — чтобы ответить</i>",
                                          parse_mode=HTML)
        db.execute("UPDATE messages SET admin_msg_id=? WHERE id=?", (sent.message_id, mid))
    await msg.reply_text("Передал руководителю 👌")


def main():
    if not BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в inspire/.env (получить у @BotFather)")
    db.init()
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [("start", start), ("me", me), ("schedule", schedule), ("absent", absent), ("svodka", svodka),
                    ("dash", dash), ("plus", plus), ("minus", minus), ("debts", debts), ("projects", projects),
                    ("newproject", newproject), ("call", call), ("note", note), ("invites", invites),
                    ("all", all_cmd), ("group", group_cmd)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(on_call_answer, pattern=r"^call:"))
    app.add_handler(CallbackQueryHandler(on_rsvp, pattern=r"^rsvp:"))
    app.add_handler(CallbackQueryHandler(on_file_choice, pattern=r"^file:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE
                                   | filters.VIDEO_NOTE | filters.ANIMATION, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    hh, mm = map(int, DAILY_AT.split(":"))
    app.job_queue.run_daily(daily, dtime(hh, mm, tzinfo=TZ), name="daily")
    log.info("Inspire bot запущен, сводка каждый день в %s (%s)", DAILY_AT, TIMEZONE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
