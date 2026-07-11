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
import asyncio
import logging
import tempfile
from datetime import time

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


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt:
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

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
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
