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
    "• */invoice* — создать счёт: спрошу кому/за что/сколько → PDF\n"
    "• */contract* — создать договор: спрошу важные условия → PDF (дизайн как у счёта)\n"
    "• */collect* — тумблер «собирать инфо»: ВКЛ — коплю присланные счета и "
    "договора в таблицу без выводов; ВЫКЛ — открыты инструменты анализа\n"
    "• */analyze* — совокупный анализ по годам (когда сбор выключен)\n"
    "• */showinvoices* — выгрузить всю таблицу в .xls (в стиле инвойсов)\n"
    "• */strategy* — стратегический совет (финансист+маркетолог+арт-менеджер): "
    "план выхода из кризиса по инвойсам, финансам и твоим планам\n"
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


# ── Режим «собирать инфо» (тумблер) ───────────────────────────────────────────
# ВКЛ: копим инвойсы в таблицу, без выводов и анализа.
# ВЫКЛ: открываются инструменты анализа (/strategy, /analyze, /showinvoices).
def _collecting() -> bool:
    return (B._settings_get("analysis_mode") or "") == "collect"


_TOOLS_HINT = ("Инструменты анализа доступны:\n"
               "• /strategy — комплексная стратегия выхода из кризиса\n"
               "• /analyze — совокупный анализ по годам\n"
               "• /showinvoices — выгрузить всю таблицу в .xls")


async def cmd_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Тумблер «собирать инфо». ВКЛ — копим инвойсы, без выводов. ВЫКЛ — открыт анализ."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    n = len(B.all_archive_rows())
    if _collecting():
        B._settings_set("analysis_mode", "")
        await update.message.reply_text(
            f"🔴 *Сбор выключен.* В таблице: {n}.\n\n" + _TOOLS_HINT, parse_mode="Markdown")
    else:
        B._settings_set("analysis_mode", "collect")
        await update.message.reply_text(
            "🟢 *Сбор инфо включён.* Кидай инвойсы (любые годы) — коплю в таблицу, "
            "БЕЗ выводов и анализа (пока сбор идёт, анализ недоступен).\n"
            "Выключить: */collect* (или напиши «все инвойсы отправлены») — тогда откроются "
            "инструменты анализа." + (f"\n\n_Сейчас в таблице: {n}._" if n else ""),
            parse_mode="Markdown")


async def stop_collecting(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """«Все инвойсы отправлены»/‎/done — выключить сбор, открыть инструменты анализа."""
    B._settings_set("analysis_mode", "")
    n = len(B.all_archive_rows())
    await update.message.reply_text(
        f"🔴 *Сбор выключен.* Собрано в таблице: {n}.\n\n" + _TOOLS_HINT, parse_mode="Markdown")


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Совокупный анализ по годам (доступен, когда сбор выключен)."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    if _collecting():
        await update.message.reply_text(
            "📥 Сейчас идёт сбор инфо — выводы отключены. Выключи сбор (/collect или "
            "«все инвойсы отправлены»), потом /analyze.")
        return
    n = len(B.all_archive_rows())
    if not n:
        await update.message.reply_text("Таблица пуста. Включи сбор — /collect — и пришли инвойсы.")
        return
    await update.message.reply_text(f"📊 Делаю совокупный анализ по годам ({n} инвойсов)…")
    reply = await asyncio.get_event_loop().run_in_executor(None, B.analyze_all_sync)
    if not reply:
        await update.message.reply_text("Не удалось собрать анализ 😔 Попробуй ещё раз.")
        return
    for chunk in B._split_msg("⚖️ *Совокупный анализ инвойсов:*\n\n" + reply, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))


async def cmd_showinvoices(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Собрать красивый .xls (в стиле инвойсов) со ВСЕМИ инвойсами по всем годам."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    rows = B.all_archive_rows()
    if not rows:
        await update.message.reply_text(
            "Таблица пуста. Включи сбор — /collect — и пришли инвойсы.")
        return
    total = sum((r["gross"] or 0) for r in rows)
    years = B.archive_years()
    try:
        path = await asyncio.get_event_loop().run_in_executor(None, B.export_invoices_xls)
    except Exception as e:
        log.error(f"showinvoices xls: {e}")
        await update.message.reply_text(f"Не смог собрать файл 😔 {e}")
        return
    yrs = ", ".join(str(y) for y in years) or "—"
    await update.message.reply_text(
        f"📊 В таблице: *{len(rows)}* инвойсов ({yrs}) · оборот всего *{B._eur_de(total)} €*.",
        parse_mode="Markdown")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename="Rechnungen_alle.xls")
    except Exception as e:
        log.error(f"showinvoices send: {e}")


async def cmd_strategy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Стратегический совет: комплексные антикризисные рекомендации по картине из
    таблицы инвойсов (финансист + маркетолог + арт-менеджер + юр-контекст)."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    if _collecting():
        await update.message.reply_text(
            "📥 Сейчас идёт сбор инфо — стратегия отключена. Выключи сбор (/collect или "
            "«все инвойсы отправлены»), потом /strategy.")
        return
    B.save_chat_id(chat_id)
    n = len(B.all_archive_rows())
    hint = "" if n else "\n_В таблице инвойсов пусто — рекомендации будут по финансам/долгам/планам; " \
                        "для полной картины включи /collect и пришли инвойсы._"
    await update.message.reply_text(
        "🧭 Собираю стратегический совет (финансист + маркетолог + арт-менеджер) "
        "по всей картине… это займёт до минуты." + hint, parse_mode="Markdown")
    reply = await asyncio.get_event_loop().run_in_executor(None, B.strategy_council_sync)
    if not reply:
        await update.message.reply_text("Не удалось собрать рекомендации 😔 Попробуй ещё раз.")
        return
    for chunk in B._split_msg("🧭 *Стратегия выхода из кризиса:*\n\n" + reply, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))


async def cmd_invoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка «создать invoice»: бот спрашивает данные, следующий текст/голос → счёт."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    ctx.user_data["await_doc"] = "invoice"
    await update.message.reply_text(
        "🧾 *Создаём счёт.* Ответь одним сообщением (можно голосом):\n"
        "• *Кому* — название и адрес (или короткое имя известного клиента)\n"
        "• *За что* — работа/проект\n"
        "• *Сумма* в €\n\n"
        "_Пример: «Café Sa'Sis, роспись стены, 800€». Отмена: /cancel_",
        parse_mode="Markdown")


async def cmd_contract(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка «создать контракт»: бот спрашивает важные вопросы, следующий текст/голос → договор."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    ctx.user_data["await_doc"] = "contract"
    await update.message.reply_text(
        "📄 *Создаём договор.* Ответь одним сообщением (удобно голосом), укажи важное:\n"
        "• *Заказчик* — название и адрес\n"
        "• *Что за работа* и *где* (объект, площадь/объём)\n"
        "• *Сумма* и *порядок оплаты* (напр. 50% предоплата)\n"
        "• *Сроки* выполнения\n"
        "• *Права на фото/изображения* (обычно за художником)\n"
        "• *Особые условия* (если есть)\n\n"
        "_Я учту твои прошлые договоры и нюансы. Дизайн — как у нового счёта. Отмена: /cancel_",
        parse_mode="Markdown")


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Отменить ожидание описания счёта/договора."""
    if ctx.user_data.get("await_doc"):
        ctx.user_data["await_doc"] = None
        await update.message.reply_text("Ок, отменил. Можешь продолжать как обычно.")


async def _route_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, txt: str):
    """Единая маршрутизация текста/голоса Юриста."""
    # Гайд-режим: бот ждёт описание для счёта/договора после кнопки
    awaiting = ctx.user_data.get("await_doc")
    if awaiting == "invoice":
        ctx.user_data["await_doc"] = None
        B.save_chat_id(update.effective_chat.id)
        await B.create_invoice_from_text(update, txt)
        return
    if awaiting == "contract":
        ctx.user_data["await_doc"] = None
        B.save_chat_id(update.effective_chat.id)
        await B.create_contract_from_text(update, txt)
        return
    # Фраза-тумблер сбора инфо
    if re.search(r"(включ\w*|начни|старт\w*)\s+сбор|собира\w*\s+инфо|режим\s+сбора", txt, re.I):
        if not _collecting():
            await cmd_collect(update, ctx)
        else:
            await update.message.reply_text("Сбор уже включён. Кидай инвойсы/договора. Выключить — /collect.")
        return
    # В режиме сбора: «все отправлены»/выключи → выкл; иначе напоминание
    if _collecting():
        if re.search(r"(все|всё)\s+(инвойс\w*|договор\w*|документ\w*)\s+отправл|это\s+все|готово|закончил|"
                     r"выключ\w*\s+сбор|стоп\s+сбор", txt, re.I):
            await stop_collecting(update, ctx)
            return
        await update.message.reply_text(
            "📥 Иду сбор — кидай PDF счетов и договоров, выводов пока не делаю. "
            "Когда закончишь — *«все отправлены»* (или /collect): откроются инструменты анализа.",
            parse_mode="Markdown")
        return
    # Запрос стратегии / выхода из кризиса
    if re.search(r"страте\w+|выход\w*\s+из\s+кризис|антикризис|что\s+делать\s+с\s+бизнес", txt, re.I):
        await cmd_strategy(update, ctx)
        return
    # Просьба составить договор (проверяем ДО инвойса — «договор» специфичнее)
    if B.looks_like_contract_request(txt):
        B.save_chat_id(update.effective_chat.id)
        await B.create_contract_from_text(update, txt)
        return
    # Просьба выставить счёт — детерминированный путь (надёжно даёт PDF)
    if B.looks_like_invoice_request(txt):
        B.save_chat_id(update.effective_chat.id)
        await B.create_invoice_from_text(update, txt)
        return
    await B.ai_lawyer(update, ctx, txt)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt:
        return
    await _route_text(update, ctx, txt)


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
    await _route_text(update, ctx, text)


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

    # Режим сбора: складываем счёт ИЛИ договор в таблицу (без разбора по одному).
    if _collecting():
        try:
            kind, ack = await asyncio.get_event_loop().run_in_executor(
                None, lambda: B.store_archived_document(tmp))
        except Exception as e:
            log.error(f"archive ingest: {e}")
            kind, ack = None, None
        if ack:
            await update.message.reply_text(f"✅ {ack}")
        else:
            await update.message.reply_text(
                "⚠️ Не смог распознать как счёт/договор. Пришли почётче или пропусти.")
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
        B.ensure_strategy_kb()  # база знаний стратегического совета
    except Exception as e:
        log.error(f"ensure_legal_kb: {e}")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("wipeinvoicestoday", B.cmd_wipeinvoicestoday))
    app.add_handler(CommandHandler(["collect", "analysis", "analysis2025"], cmd_collect))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler(["done", "analysisoff"], stop_collecting))
    app.add_handler(CommandHandler(["showinvoices", "show2025"], cmd_showinvoices))
    app.add_handler(CommandHandler(["strategy", "strategie"], cmd_strategy))
    app.add_handler(CommandHandler(["invoice", "rechnung", "schet"], cmd_invoice))
    app.add_handler(CommandHandler(["contract", "vertrag", "dogovor"], cmd_contract))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
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
