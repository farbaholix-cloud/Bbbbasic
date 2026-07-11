"""
Юрист — отдельный Telegram-бот, общение в нём сугубо на налогово-правовые темы
(Германия): Freiberufler / Kleinunternehmer / KSK / ELSTER / Sozialversicherung,
плюс контекст §24 (украинец на временной защите).

Мозг переиспользуется из основного бота (bot.py): тот же доступ к финансовой БД,
та же база знаний legal_kb, тот же набор действий (инвойсы, напоминания, письма).
Запускается отдельным процессом со своим токеном JURIST_BOT_TOKEN; основной бот
поднимает его как supervised-процесс (см. _restart_jurist в bot.py).
"""
import os
import re
import sys
import asyncio
import logging
import tempfile
from datetime import datetime, time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

import bot as B  # переиспользуем «мозг» Юриста и доступ к БД/базе знаний

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [jurist] %(message)s")
log = logging.getLogger("jurist")

GREETING = (
    "⚖️ *Юрист на связи.*\n\n"
    "Это отдельный бот — здесь общаемся сугубо по налогово-правовым вопросам в Германии. "
    "Я вижу твои финансы, счета и долги, знаю специфику Freiberufler / Kleinunternehmer / "
    "KSK / ELSTER и контекст §24 (украинец на временной защите).\n\n"
    "Спроси что угодно, например:\n"
    "• _проанализируй мой оборот — близок ли я к порогу Kleinunternehmer?_\n"
    "• _стоит ли вступать в KSK и сколько сэкономлю на страховке?_\n"
    "• _помоги заполнить Anlage EÜR в ELSTER_\n"
    "• _напиши письмо в Finanzamt о продлении срока_\n"
    "• _когда и что мне подавать в этом году?_\n\n"
    "Можешь прислать *договор, счёт или письмо из ведомства* (PDF/фото) — разберу и подскажу, "
    "что это и что делать.\n\n"
    "🎤 Голосовые тоже понимаю."
)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    B.save_chat_id(update.effective_chat.id)
    await update.message.reply_text(GREETING, parse_mode="Markdown")


# Легенда при перезапуске — короткое уведомление владельцу, что Юрист поднялся,
# что умеет и что может перезапустить сам себя.
RESTART_LEGEND = (
    "⚖️ *Юрист перезапущен и снова на связи.*\n"
    "_{when}_\n\n"
    "Умею: счета (Rechnung PDF), анализ финансов и оборота, письма в ведомства, "
    "напоминания о сроках, разбор присланных документов.\n\n"
    "Команды:\n"
    "• */analysis2025* — режим анализа 2025: пришли инвойсы за год, потом "
    "«все инвойсы отправлены» — дам совокупные выводы\n"
    "• */show2025* — выгрузить таблицу 2025 в .xls (в стиле инвойсов)\n"
    "• */restart* — самоперезапуск (не завися от секретаря)\n"
    "• */wipeinvoicestoday* — удалить все счета, созданные сегодня (архив + PDF)"
)


async def _post_init(app):
    """При старте бота шлём владельцу «легенду». Работает и при самоперезапуске.
    Троттл ~90с — чтобы быстрые двойные рестарты (супервизор секретаря + деплой)
    не давали дубль пингов."""
    chat = B.get_chat_id()
    if not chat:
        return
    import time as _t
    try:
        last = float(B._settings_get("jurist_legend_last") or 0)
    except (TypeError, ValueError):
        last = 0
    now_ts = _t.time()
    if now_ts - last < 90:
        return
    B._settings_set("jurist_legend_last", str(now_ts))
    when = datetime.now(B.BERLIN).strftime("%d.%m.%Y %H:%M") if B.BERLIN else datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        await app.bot.send_message(chat, RESTART_LEGEND.format(when=when), parse_mode="Markdown")
    except Exception as e:
        log.error(f"post_init legend: {e}")


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Самоперезапуск Юриста независимо от секретаря: заменяем процесс свежим через execv.
    Тот же PID, никакого второго инстанса (значит и без Telegram-Conflict); подхватывает
    обновлённый на диске код. Только владелец."""
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
        os.execv(sys.executable, [sys.executable, "jurist_bot.py"])  # заменяет текущий процесс
    except Exception as e:
        log.error(f"self-restart execv: {e}")
        await update.message.reply_text(f"Не смог перезапуститься сам: {e}")


# ── Режим пакетного анализа 2025 ──────────────────────────────────────────────
def _analysis_mode() -> str:
    return B._settings_get("analysis_mode") or ""


async def cmd_analysis2025(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Включить режим анализа 2025: собираем присланные PDF-инвойсы в таблицу."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    B._settings_set("analysis_mode", "2025_collect")
    n = len(B.year_archive_rows(2025))
    await update.message.reply_text(
        "📊 *Режим анализа 2025 включён.*\n\n"
        "Кидай PDF-инвойсы по одному — я распознаю каждый и складываю в таблицу "
        "(без разбора по отдельности, чтобы не жечь токены).\n"
        "Когда пришлёшь все — напиши *«все инвойсы отправлены»* (или /done): дам "
        "СОВОКУПНЫЙ анализ за год и выводы, дальше сможем спокойно обсуждать 2025 "
        "по таблице, не перечитывая файлы.\n"
        + (f"\n_Уже в архиве 2025: {n} шт._" if n else ""),
        parse_mode="Markdown")


async def cmd_analysisoff(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Выключить режим анализа (данные в таблице остаются)."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B._settings_set("analysis_mode", "")
    await update.message.reply_text("Режим анализа выключен. Таблица 2025 сохранена — можешь спрашивать о ней в любой момент.")


async def cmd_show2025(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать таблицу 2025: собрать красивый .xls (в стиле инвойсов) и прислать файлом."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    rows = B.year_archive_rows(2025)
    if not rows:
        await update.message.reply_text(
            "Таблица 2025 пока пуста. Включи режим — /analysis2025 — и пришли инвойсы.")
        return
    total = sum((r["gross"] or 0) for r in rows)
    try:
        path = await asyncio.get_event_loop().run_in_executor(None, lambda: B.export_year_xls(2025))
    except Exception as e:
        log.error(f"show2025 xls: {e}")
        await update.message.reply_text(f"Не смог собрать файл 😔 {e}")
        return
    await update.message.reply_text(
        f"📊 В таблице 2025: *{len(rows)}* инвойсов · оборот *{B._eur_de(total)} €*.",
        parse_mode="Markdown")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename=f"Rechnungen_2025.xls")
    except Exception as e:
        log.error(f"show2025 send: {e}")


async def finalize_2025(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """«Все инвойсы отправлены» → совокупный анализ по таблице."""
    n = len(B.year_archive_rows(2025))
    if not n:
        await update.message.reply_text("В таблице 2025 пока пусто — сначала пришли инвойсы.")
        return
    await update.message.reply_text(f"📊 Собрано {n} инвойсов. Делаю совокупный анализ за 2025…")
    reply = await asyncio.get_event_loop().run_in_executor(None, lambda: B.analyze_year_sync(2025))
    B._settings_set("analysis_mode", "2025_ready")
    if not reply:
        await update.message.reply_text("Не удалось собрать анализ 😔 Попробуй ещё раз или пришли файлы заново.")
        return
    for chunk in B._split_msg("⚖️ *Анализ 2025:*\n\n" + reply, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))
    await update.message.reply_text(
        "Готово. Теперь просто спрашивай про 2025 — отвечаю по таблице, файлы не перечитываю. "
        "Выйти из режима: /analysisoff")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt:
        return
    # Фраза-включатель режима анализа 2025
    if re.search(r"включ\w*\s+режим\s+анализ\w*\s+2025|режим\s+анализа?\s+2025", txt, re.I):
        await cmd_analysis2025(update, ctx)
        return
    # В режиме сбора 2025: либо «все инвойсы отправлены», либо напоминание
    if _analysis_mode() == "2025_collect":
        if re.search(r"(все|всё)\s+инвойс\w*\s+отправл|инвойсы\s+все|готово|закончил|это\s+все", txt, re.I):
            await finalize_2025(update, ctx)
            return
        await update.message.reply_text(
            "📥 Я в режиме сбора 2025 — кидай PDF-инвойсы. Когда закончишь, напиши "
            "*«все инвойсы отправлены»* (или /done). Выйти без анализа: /analysisoff",
            parse_mode="Markdown")
        return
    # Просьба выставить счёт — детерминированный путь (надёжно даёт PDF),
    # а не через лоер-модель (она болтает «отправляю», но не выдаёт action).
    if B.looks_like_invoice_request(txt):
        B.save_chat_id(update.effective_chat.id)
        await B.create_invoice_from_text(update, txt)
        return
    await B.ai_lawyer(update, ctx, txt)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    if B.looks_like_invoice_request(text):
        B.save_chat_id(update.effective_chat.id)
        await B.create_invoice_from_text(update, text)
        return
    await B.ai_lawyer(update, ctx, text)


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Договор / счёт / письмо из ведомства — скачиваем и отдаём Юристу на разбор (через Read)."""
    doc = update.message.document
    photo = update.message.photo[-1] if update.message.photo else None
    if not doc and not photo:
        return
    fid = doc.file_id if doc else photo.file_id
    name = (doc.file_name if doc else "image.jpg") or "file.bin"
    ext = os.path.splitext(name)[1] or (".pdf" if doc else ".jpg")
    tmp = os.path.join(tempfile.gettempdir(), f"jur_{fid[:16]}{ext}")
    tg_file = await ctx.bot.get_file(fid)
    await tg_file.download_to_drive(tmp)

    # Режим сбора 2025: складываем инвойс в таблицу (без разбора по одному).
    if _analysis_mode() == "2025_collect":
        try:
            ack = await asyncio.get_event_loop().run_in_executor(
                None, lambda: B.store_archived_invoice(tmp))
        except Exception as e:
            log.error(f"archive ingest: {e}")
            ack = None
        n = len(B.year_archive_rows(2025))
        if ack:
            await update.message.reply_text(f"✅ В таблицу ({n}): {ack}")
        else:
            await update.message.reply_text(
                "⚠️ Не смог распознать как счёт. Пришли почётче или пропусти. "
                f"Сейчас в таблице: {n}.")
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return

    # Сначала пробуем авто-импорт: если это ИСХОДЯЩИЙ счёт самого владельца —
    # забираем из него реквизиты (в настройки) и клиента (в память).
    try:
        imp = await asyncio.get_event_loop().run_in_executor(
            None, lambda: B.import_own_invoice_sync(tmp))
    except Exception as e:
        log.error(f"own-invoice import: {e}")
        imp = None
    if imp and imp.get("imported"):
        await update.message.reply_text(
            "⚖️ Разобрал твой счёт и запомнил данные:\n\n" + imp["summary"]
            + "\n\nТеперь можно короче: _«инвойс "
            + "<клиент> на <сумму>»_ — подставлю адрес сам.\n"
            "Реквизиты неверны? Поменяй: `/setinvoicedata <поле> <значение>` секретарю.",
            parse_mode="Markdown")
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return

    instruction = (
        f"Проанализируй документ по пути {tmp} (используй инструмент Read). "
        "Если это фото бумаги — оно может быть снято под углом, помято, со складками и тенями: "
        "всё равно аккуратно распознай весь текст и все числа. Немецкий формат: 4.372,32 = 4372.32. "
        "Это может быть договор (Vertrag), счёт (Rechnung), письмо из ведомства/кассы (Finanzamt/KSK/"
        "Krankenkasse/AOK/Jobcenter) или иной официальный документ. Дай налогово-правовую оценку: "
        "1) что это за документ; 2) ключевые пункты, суммы, сроки; 3) риски/на что обратить внимание; "
        "4) что мне конкретно сделать и нужно ли что-то ответить/подать. "
        "Если это договор — обрати внимание на оплату, ответственность, расторжение и налоговые последствия."
    )
    try:
        await B.ai_lawyer(update, ctx, instruction)
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def main():
    B.init_db()
    token = B.get_jurist_token()  # из окружения или из настроек в БД (не из git)
    if not token:
        raise SystemExit(
            "Токен Юрист-бота не задан. Пришли его секретарю командой "
            "/setjuristtoken ТОКЕН, либо задай JURIST_BOT_TOKEN в окружении."
        )
    try:
        B.ensure_legal_kb()  # база знаний должна быть на диске
    except Exception as e:
        log.error(f"ensure_legal_kb: {e}")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("wipeinvoicestoday", B.cmd_wipeinvoicestoday))
    app.add_handler(CommandHandler("analysis2025", cmd_analysis2025))
    app.add_handler(CommandHandler("analysisoff", cmd_analysisoff))
    app.add_handler(CommandHandler("show2025", cmd_show2025))
    app.add_handler(CommandHandler("done", finalize_2025))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.PHOTO, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    jq = app.job_queue
    legal_t = time(9, 0, tzinfo=B.BERLIN) if B.BERLIN else time(9, 0)
    jq.run_daily(B.legal_deadlines_check, time=legal_t)  # напоминания о сроках/отчётах

    log.info("Юрист-бот запущен ⚖️")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
