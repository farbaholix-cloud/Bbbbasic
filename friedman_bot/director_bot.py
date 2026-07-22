"""
Директор — ГЛАВНЫЙ Telegram-бот и единственный интерфейс владельца к команде
агентов. Принимает любую задачу целиком, по-настоящему делегирует её агентам
(Секретарь, Юрист, Продавец, Стратег — их мозги вызываются внутри процесса),
контролирует результаты и выдаёт владельцу минимум: решения на подтверждение,
задачи владельцу и следующий шаг. Утром в 07:00 — сводка-синтез из картин всех
агентов. Через /update Директор обновляет и перезапускает всю команду.

Мозг переиспользуется из bot.py (общая БД, базы знаний всех агентов).
Запускается отдельным процессом со своим токеном DIRECTOR_BOT_TOKEN
(или /setdirectortoken секретарю); процесс bot.py остаётся «машинным
отделением» — супервизором и авто-деплоем, но владелец общается только здесь.
"""
import os
import sys
import asyncio
import logging
import subprocess
import tempfile
from datetime import datetime, time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

import bot as B  # «мозг» Директора и всей команды, доступ к БД/базам знаний

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [director] %(message)s")
log = logging.getLogger("director")

GREETING = (
    "🎩 *Директор на связи. Теперь я — твой главный бот.*\n\n"
    "Остальным ботам писать больше не нужно: кидай сюда любую задачу целиком — "
    "я сам раздам поручения команде (🗂 Секретарь · ⚖️ Юрист · 💼 Продавец · "
    "🧭 Стратег), проверю результаты и верну тебе минимум: решения на "
    "подтверждение, задачи, которые можешь сделать только ты, и следующий шаг.\n\n"
    "Например:\n"
    "• _пришёл запрос на мурал 40 м² — разрули от лида до счёта_\n"
    "• _зафиксируй: потратил 40€ на краску, напомни завтра про грунт_\n"
    "• _что с деньгами в этом месяце — раздай задачи_\n"
    "• _что горит?_\n\n"
    "Каждое утро в *07:00* — одна сводка: выводы из картин Секретаря, Юриста, "
    "Маркетолога/Продавца и Стратега.\n\n"
    "• /team — команда и статус процессов\n"
    "• /brief — утренняя сводка прямо сейчас\n"
    "• /update — обновить и перезапустить всю команду\n"
    "🎤 Голосовые понимаю; /voice — отвечать голосом."
)

RESTART_LEGEND = (
    "🎩 *Директор перезапущен и снова на связи.*\n"
    "_{when}_\n\n"
    "Я главный бот: кидай задачу целиком — делегирую команде и верну выводы. "
    "Утренняя сводка в 07:00.\n\n"
    "Команды: /team · /brief · /update · /voice · /restart"
)


async def _post_init(app):
    """При старте шлём владельцу «легенду». Троттл ~90с от двойных рестартов."""
    chat = B.get_chat_id()
    if not chat:
        return
    import time as _t
    try:
        last = float(B._settings_get("director_legend_last") or 0)
    except (TypeError, ValueError):
        last = 0
    now_ts = _t.time()
    if now_ts - last < 90:
        return
    B._settings_set("director_legend_last", str(now_ts))
    when = datetime.now(B.BERLIN).strftime("%d.%m.%Y %H:%M") if B.BERLIN else datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        await app.bot.send_message(chat, RESTART_LEGEND.format(when=when), parse_mode="Markdown")
    except Exception as e:
        log.error(f"post_init legend: {e}")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    B.save_chat_id(update.effective_chat.id)
    await update.message.reply_text(GREETING, parse_mode="Markdown")


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Самоперезапуск через execv: тот же PID, без второго инстанса. Только владелец."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    await update.message.reply_text("♻️ Перезапускаюсь, вернусь через пару секунд…")
    d = os.path.dirname(os.path.abspath(__file__))
    log.info("самоперезапуск по команде /restart")
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.chdir(d)
        os.execv(sys.executable, [sys.executable, "director_bot.py"])
    except Exception as e:
        log.error(f"self-restart execv: {e}")
        await update.message.reply_text(f"Не смог перезапуститься сам: {e}")


async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обновить всю команду: скачать свежий код и перезапустить Секретаря —
    тот поднимет Юриста, Продавца и Директора уже на новой версии."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    d = os.path.dirname(os.path.abspath(__file__))
    await update.message.reply_text("🔄 Качаю свежий код с GitHub…")
    try:
        sha = B._remote_sha()
        downloaded = B._download_code(d, sha)
        try:
            with open(B._SHA_FILE, "w") as f:
                f.write(sha)
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ Скачано ({sha[:7]}): " + ", ".join(downloaded)
            + "\n♻️ Перезапускаю команду — вернусь через полминуты…")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Не удалось обновить: {e}")
        return
    try:
        B._restart_dashboard(d)
        B._restart_dashboard_mac(d)
    except Exception as e:
        log.error(f"update dashboards: {e}")
    # Секретарь перезапустится и сам поднимет Юриста, Продавца и этого Директора
    # (наш процесс при этом будет заменён свежим — сообщения выше уже отправлены).
    B._restart_secretary(d)


_TEAM_PROCS = (("🗂 Секретарь (движок, деплой)", "[ /]bot[.]py"),
               ("⚖️ Юрист", "jurist_bot.py"),
               ("💼 Продавец", "sales_bot.py"),
               ("🎩 Директор", "director_bot.py"),
               ("📊 Дашборд", "dashboard.py"),
               ("🖥 Mac-дашборд", "dashboard_mac.py"))


async def cmd_team(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда и живой статус процессов — без ИИ, мгновенно."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    lines = ["🎩 *Команда FARBAHOLIX* (я делегирую им сам — писать им не нужно):\n"]
    for label, pat in _TEAM_PROCS:
        try:
            r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=10)
            alive = bool(r.stdout.strip())
        except Exception:
            alive = None
        mark = "🟢" if alive else ("🔴" if alive is not None else "⚪️")
        lines.append(f"{mark} {label}")
    lines.append("\n🗂 операционка/память · ⚖️ право/налоги/Rechnung · "
                 "💼 сделки/дожатие · 🧭 Стратег — по запросу.\n"
                 "Все пишут в одну базу. Если что-то 🔴 — /update поднимет всех.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _send_brief(bot, chat_id: int):
    # Тот же постер-«картинка», что слал Секретарь до появления Директора —
    # общий рендер render_owner_brief, только шлёт бот Директора (verbose=True:
    # при сбое рендера объяснит причину и предложит /setupbrief).
    await B.render_owner_brief(bot, chat_id, verbose=True)


async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Хвосты логов всех процессов — диагностика «почему молчит» без сервера."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    parts = []
    for name, p in (("Секретарь", "/tmp/bot.log"), ("Юрист", "/tmp/jurist.log"),
                    ("Продавец", "/tmp/sales.log"), ("Директор", "/tmp/director.log"),
                    ("Дашборд", "/tmp/dash.log")):
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4000))
                txt = f.read().decode("utf-8", "replace")
            tail = "\n".join(txt.splitlines()[-10:]) or "(пусто)"
        except Exception as e:
            tail = f"(нет файла: {type(e).__name__})"
        parts.append(f"═══ {name} ═══\n{tail}")
    for chunk in B._split_msg("\n\n".join(parts), 3800):
        await update.message.reply_text(chunk)


async def cmd_invoices(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Единая таблица счетов в .xls — та же, что /showinvoices у Юриста."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    rows = B.all_archive_rows()
    if not rows:
        await update.message.reply_text("Таблица счетов пуста.")
        return
    total = sum((r["gross"] or 0) for r in rows)
    try:
        path = await asyncio.get_event_loop().run_in_executor(None, B.export_invoices_xls)
    except Exception as e:
        log.error(f"invoices xls: {e}")
        await update.message.reply_text(f"Не смог собрать таблицу 😔 {e}")
        return
    await update.message.reply_text(f"🧾 В таблице {len(rows)} счетов · всего {total:.0f}€.")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename="Rechnungen_alle.xls")
    except Exception as e:
        log.error(f"invoices send: {e}")


async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Утренняя сводка вручную — постер на сегодня."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    await update.message.reply_text("🎩 Собираю сводку…")
    await _send_brief(ctx.bot, chat_id)


async def director_morning(ctx: ContextTypes.DEFAULT_TYPE):
    """Ежедневно 07:00 Berlin. Атомарная заявка в общей БД — дубли исключены."""
    chat_id = B.get_chat_id()
    if not chat_id:
        return
    today = (datetime.now(B.BERLIN) if B.BERLIN else datetime.now()).strftime("%Y-%m-%d")
    if not B._claim_daily("director_brief:" + today):
        return
    try:
        await _send_brief(ctx.bot, chat_id)
    except Exception as e:
        log.error(f"director_morning: {e}")


def _voice_on() -> bool:
    return (B._settings_get("director_voice") or "") == "on"


async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Вкл/выкл голосовые ответы Директора: /voice [on|off] (без аргумента — тумблер)."""
    cmd = ((update.message.text or "").split() or [""])[0].lower()
    arg = (ctx.args[0].lower() if ctx.args else "")
    if "voice_on" in cmd or arg in ("on", "вкл", "1"):
        B._settings_set("director_voice", "on")
    elif "voice_off" in cmd or arg in ("off", "выкл", "0"):
        B._settings_set("director_voice", "off")
    else:
        B._settings_set("director_voice", "off" if _voice_on() else "on")
    state = "включены ✅" if _voice_on() else "выключены ⏹"
    await update.message.reply_text(f"🔊 Голосовые ответы {state}")


async def _reply_chunks(update: Update, header: str, reply: str):
    for chunk in B._split_msg(header + reply, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))


# Один оркестр за раз: наложение двух тяжёлых цепочек друг на друга — главный
# источник «молчания». Вторая задача честно ждёт в очереди.
_orch_lock = asyncio.Lock()


async def _route_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, txt: str):
    """Оркестрация: быстрый триаж → параллельное исполнение поручений агентами →
    контроль и минимальный свод. На каждом шаге есть деградация — владелец
    никогда не остаётся без ответа."""
    if _orch_lock.locked():
        await update.message.reply_text("⏳ Ещё довожу предыдущую задачу — эта в очереди, возьму следом.")
    async with _orch_lock:
        try:
            await _orchestrate(update, ctx, txt)
        except Exception as e:
            log.error(f"orchestration crash: {e}", exc_info=True)
            await update.message.reply_text(
                f"⚠️ Сбой оркестрации ({type(e).__name__}). Логи сохранены — попробуй ещё раз.")


async def _orchestrate(update: Update, ctx: ContextTypes.DEFAULT_TYPE, txt: str):
    B.remember_director("user", txt)
    loop = asyncio.get_event_loop()

    # Детерминированные сценарии с файлом на выходе — мимо LLM-триажа, ноль
    # токенов, гарантированный результат прямо в этот чат ботом Директора.
    # 1) «пришли/скинь PDF счёта…» — выдача готовых PDF из единой таблицы
    if B.looks_like_invoice_fetch(txt):
        await B.send_invoice_pdfs(update, txt)
        B.remember_director("assistant", "отправил PDF счетов по запросу: " + txt[:120])
        return
    # 2) создание документов: счёт (Rechnung) и договор
    if B.looks_like_contract_request(txt):
        await B.create_contract_from_text(update, txt)
        B.remember_director("assistant", "составил договор: " + txt[:150])
        return
    if B.looks_like_invoice_request(txt):
        await B.create_invoice_from_text(update, txt)
        B.remember_director("assistant", "выставил счёт: " + txt[:150])
        return

    # Шаг 1: быстрый триаж (haiku без инструментов; при сбое LLM внутри сработает
    # резервный маршрут по ключевым словам — пустого resp не бывает)
    resp = await loop.run_in_executor(None, lambda: B.director_dialog_sync(txt))

    # Актуализация базы: триаж мог вернуть actions («сделано», «оплата пришла»…) —
    # применяем сразу, все агенты видят через общую БД
    acts = (resp or {}).get("actions") or []
    applied_notes = []
    if acts:
        try:
            applied = await loop.run_in_executor(None, lambda: B.apply_actions(acts[:8]))
            applied_notes = [t for _k, _i, t, _a, _p in applied if t]
        except Exception as e:
            log.error(f"director apply_actions: {e}")

    delegations = (resp or {}).get("delegate") or []
    if not delegations:
        reply = (resp or {}).get("reply", "")
        if not reply and applied_notes:
            reply = "Записал."
        if not reply:
            await update.message.reply_text("Не получилось собрать ответ 😔 Попробуй ещё раз.")
            return
        if applied_notes:
            reply += "\n\n📝 " + "\n📝 ".join(applied_notes)
        B.remember_director("assistant", reply[:1500])
        await _reply_chunks(update, "", reply)
        if _voice_on():
            try:
                await B.speak_reply(update, reply)
            except Exception as e:
                log.error(f"director voice reply: {e}")
        return

    # Шаг 2: исполняем поручения ПАРАЛЛЕЛЬНО (каждое — вызов мозга агента).
    note = resp.get("note", "")
    jobs = []
    for dlg in delegations[:4]:  # максимум 4 поручения за раз — защита от разбегания
        to = (dlg.get("to") or "").strip()
        task = (dlg.get("task") or "").strip()
        if to and task:
            jobs.append((to, task))
    if not jobs:
        await update.message.reply_text("Поручения не сформировались 😔 Попробуй переформулировать.")
        return

    labels = [B.DIRECTOR_AGENT_LABEL.get(to, to) for to, _ in jobs]
    header = ("🎩 " + note + "\n" if note else "🎩 ") + "Поручил: " + " · ".join(labels)
    progress = await update.message.reply_text(header + "\n⏳ агенты работают…")

    done_marks = {}

    async def _run_one(to, task):
        out, notes, files = await loop.run_in_executor(
            None, lambda: B.director_run_delegation(to, task))
        done_marks[to] = "✓" if out else "✗"
        try:
            marks = " ".join(f"{B.DIRECTOR_AGENT_LABEL.get(t, t)} {m}" for t, m in done_marks.items())
            await progress.edit_text(header + f"\n{marks} ({len(done_marks)}/{len(jobs)})…")
        except Exception:
            pass  # правка прогресса — косметика, не роняем оркестр
        return (to, task, out, notes, files)

    results = list(await asyncio.gather(*(_run_one(to, task) for to, task in jobs)))
    ok_results = [r for r in results if r[2]]

    if not ok_results:
        await update.message.reply_text(
            "Агенты не дали результата 😔 Это записано в логи (/tmp/director.log). "
            "Попробуй ещё раз или переформулируй.")
        return

    # Шаг 3: один агент — его ответ уходит владельцу напрямую (свод не нужен,
    # экономим целый sonnet-вызов); несколько — контроль и минимальный свод
    if len(ok_results) == 1:
        to, _task, out, notes, _files = ok_results[0]
        reply = f"{B.DIRECTOR_AGENT_LABEL.get(to, to)}:\n\n{out}"
        if notes:
            reply += "\n\n📝 " + "; ".join(notes)
    else:
        reply = await loop.run_in_executor(
            None, lambda: B.director_finalize_sync(txt, ok_results))
        if not reply:
            # деградация: отдаём сырые результаты, лишь бы не потерять работу агентов
            reply = "\n\n".join(
                f"{B.DIRECTOR_AGENT_LABEL.get(to, to)}:\n{out}"
                for to, _t, out, _n, _f in ok_results)
    if applied_notes:
        reply += "\n\n📝 " + "\n📝 ".join(applied_notes)
    B.remember_director("assistant", reply[:1500])
    await _reply_chunks(update, "", reply)
    # Файлы от агентов (PDF счёта и т.п.) — вслед за текстом
    for path in (f for r in ok_results for f in (r[4] or [])):
        try:
            with open(path, "rb") as doc:
                await update.message.reply_document(doc, filename=os.path.basename(path))
        except Exception as e:
            log.error(f"send delegated file {path}: {e}")
    if _voice_on():
        try:
            await B.speak_reply(update, reply)
        except Exception as e:
            log.error(f"director voice reply: {e}")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    txt = (update.message.text or "").strip()
    if not txt:
        return
    await _route_text(update, ctx, txt)


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """PDF/фото Директору → единый контур счетов: распознать и сложить счёт в
    таблицу invoice_archive + PDF-хранилище (договор — в архив договоров).
    Именно так закидываются старые счета, выставленные до появления хранилища."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    doc = update.message.document
    photo = update.message.photo[-1] if update.message.photo else None
    if not doc and not photo:
        return
    fid = doc.file_id if doc else photo.file_id
    name = (doc.file_name if doc else "image.jpg") or "file.bin"
    ext = os.path.splitext(name)[1] or (".pdf" if doc else ".jpg")
    tmp = os.path.join(tempfile.gettempdir(), f"dir_{fid[:16]}{ext}")
    tg_file = await ctx.bot.get_file(fid)
    await tg_file.download_to_drive(tmp)
    B.remember_director("user", f"прислал документ: {name}")
    await update.message.reply_text("📄 Принял — распознаю и кладу в архив… ~полминуты.")
    try:
        kind, ack = await asyncio.get_event_loop().run_in_executor(
            None, lambda: B.store_archived_document(tmp))
    except Exception as e:
        log.error(f"director ingest: {e}")
        kind, ack = None, None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    if ack:
        await update.message.reply_text(
            f"✅ {ack}\n📁 Записан в единую таблицу"
            + ("; PDF — в хранилище (пришлю по запросу)." if kind == "invoice" else "."))
        B.remember_director("assistant", "в архив: " + ack)
    else:
        await update.message.reply_text(
            "⚠️ Не распознал файл как счёт или договор. Пришли почётче (PDF или "
            "ровное фото) — либо это не тот тип документа.")


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    await update.message.reply_text("🎤 Слушаю…")
    voice = update.message.voice
    f = await ctx.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await f.download_to_drive(tmp.name)
        tmp_path = tmp.name
    text = await asyncio.get_event_loop().run_in_executor(None, lambda: B._transcribe_sync(tmp_path))
    try:
        os.unlink(tmp_path)
    except Exception:
        pass
    if not text:
        await update.message.reply_text("Не разобрал голос 😔 Напиши текстом.")
        return
    await update.message.reply_text(f"🎙 Понял: „{text[:300]}“")
    await _route_text(update, ctx, text)


def main():
    B.init_db()
    token = B.get_director_token()
    if not token:
        raise SystemExit(
            "Токен Директор-бота не задан. Создай бота у @BotFather и пришли токен "
            "секретарю командой /setdirectortoken ТОКЕН, либо задай DIRECTOR_BOT_TOKEN в окружении."
        )
    try:
        B.ensure_director_kb()   # регламент Директора + справочник ИИ-инструментов
        B.ensure_secretary_kb()  # SKILL.md Секретаря — для маршрутизации операционки
        B.ensure_legal_kb()      # зоны Юриста
        B.ensure_sales_kb()      # зоны Продавца
        B.ensure_strategy_kb()   # зоны Стратега
    except Exception as e:
        log.error(f"ensure kb: {e}")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["team", "komanda", "status"], cmd_team))
    app.add_handler(CommandHandler(["brief", "svodka"], cmd_brief))
    app.add_handler(CommandHandler(["invoices", "showinvoices"], cmd_invoices))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler(["voice", "voice_on", "voice_off"], cmd_voice))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.PHOTO, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    jq = app.job_queue
    brief_t = time(7, 0, tzinfo=B.BERLIN) if B.BERLIN else time(7, 0)
    jq.run_daily(director_morning, time=brief_t)

    log.info("Директор-бот запущен 🎩 (главный)")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
