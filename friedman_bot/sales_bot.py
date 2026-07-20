"""
Продавец — отдельный Telegram-бот: сделки, воронка, лидогенерация, дожатие до
оплаты + ежедневное обучение продажам (дайджест в 07:00 с карточкой-изображением).

Мозг переиспользуется из основного бота (bot.py): та же БД, база знаний sales_kb,
воронка проектов, финансы и таблица инвойсов. Запускается отдельным процессом со
своим токеном SALES_BOT_TOKEN (или /setsalestoken секретарю); основной бот
поднимает его как supervised-процесс (см. _restart_sales в bot.py).

Архитектура и план развития — SALES_BOT_SPEC.md.
"""
import os
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

import bot as B  # «мозг» Продавца и доступ к БД/базе знаний

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [sales] %(message)s")
log = logging.getLogger("sales")

GREETING = (
    "💼 *Продавец на связи.*\n\n"
    "Это отдельный бот — здесь про деньги из искусства: воронка сделок, "
    "лидогенерация, оферты, цена, дожатие до оплаты. Я вижу твои проекты с "
    "ожидаемым профитом, финансы, долги и таблицу инвойсов.\n\n"
    "Спроси что угодно, например:\n"
    "• _что дожимать первым, чтобы не было кассового разрыва?_\n"
    "• _напиши письмо клиенту X — напоминание об оплате_\n"
    "• _какую цену поставить за фасад ~40 м²?_\n"
    "• _где взять новых клиентов, не нарушая закон?_\n\n"
    "Каждое утро в *07:00* пришлю дайджест: 7 минут теории продаж с цитатами "
    "(никогда не повторяются) + применение к твоей реальной воронке + "
    "микро-задание дня.\n\n"
    "📊 Бизнес-пульт FARBAHOLIX (воронка + лиды + деньги): /ip — пришлю ссылку.\n"
    "🎤 Голосовые понимаю; /voice — отвечать голосом."
)

RESTART_LEGEND = (
    "💼 *Продавец перезапущен и снова на связи.*\n"
    "_{when}_\n\n"
    "Команды:\n"
    "• */sales* — разбор воронки: что дожимать первым и как; можно с вопросом: "
    "_/sales как дожать Café Sa'Sis_\n"
    "• */funnel* — воронка цифрами (без ИИ, мгновенно)\n"
    "• */digest* — утренний дайджест продаж прямо сейчас\n"
    "• */ip* — ссылка на бизнес-пульт FARBAHOLIX (воронка + лиды + деньги)\n"
    "• */voice* — вкл/выкл голосовые ответы\n"
    "• */restart* — самоперезапуск\n\n"
    "Просто пиши (или говори) — обсудим сделки, цены, письма клиентам, "
    "каналы новых заказов. Утренний дайджест — ежедневно в 07:00."
)


async def _post_init(app):
    """При старте шлём владельцу «легенду». Троттл ~90с от двойных рестартов."""
    chat = B.get_chat_id()
    if not chat:
        return
    import time as _t
    try:
        last = float(B._settings_get("sales_legend_last") or 0)
    except (TypeError, ValueError):
        last = 0
    now_ts = _t.time()
    if now_ts - last < 90:
        return
    B._settings_set("sales_legend_last", str(now_ts))
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
        os.execv(sys.executable, [sys.executable, "sales_bot.py"])
    except Exception as e:
        log.error(f"self-restart execv: {e}")
        await update.message.reply_text(f"Не смог перезапуститься сам: {e}")


async def cmd_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ссылка на бизнес-пульт FARBAHOLIX (dashboard_biz.py, :8770)."""
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            ip = r.read().decode().strip()
        await update.message.reply_text(
            f"💼 Бизнес-пульт FARBAHOLIX:\nhttp://{ip}:8765/biz\n\n"
            "Внутри: воронка сделок (синхронна с «Проектами» Секретаря), доска "
            "лидов с касаниями, деньги (обороты, порог §19, топ-клиенты).\n\n"
            "Сохрани как PWA в Safari: Поделиться → На экран «Домой»")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Не удалось узнать IP: {e}")


def _voice_on() -> bool:
    return (B._settings_get("sales_voice") or "") == "on"


async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Вкл/выкл голосовые ответы Продавца: /voice [on|off] (без аргумента — тумблер),
    /voice_on и /voice_off — явно."""
    cmd = ((update.message.text or "").split() or [""])[0].lower()
    arg = (ctx.args[0].lower() if ctx.args else "")
    if "voice_on" in cmd or arg in ("on", "вкл", "1"):
        B._settings_set("sales_voice", "on")
    elif "voice_off" in cmd or arg in ("off", "выкл", "0"):
        B._settings_set("sales_voice", "off")
    else:
        B._settings_set("sales_voice", "off" if _voice_on() else "on")
    state = "включены ✅" if _voice_on() else "выключены ⏹"
    await update.message.reply_text(f"🔊 Голосовые ответы {state}")


async def _reply_chunks(update: Update, header: str, reply: str):
    for chunk in B._split_msg(header + reply, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))


async def cmd_funnel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Воронка цифрами — без ИИ, мгновенно (проверка живости данных)."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    text = B.get_funnel_context()
    if not text:
        await update.message.reply_text(
            "Воронка пуста. Задай проектам «💰 Ожидаемый профит» в приложении "
            "(сумма + стадия + дата оплаты) — и я увижу сделки.")
        return
    await update.message.reply_text(text)


async def cmd_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ask: str = None):
    """Разбор воронки/дожатие. /sales <вопрос> — точечный запрос."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    if ask is None:
        ask = " ".join(ctx.args or []).strip()
    await update.message.reply_text(
        "💼 Разбираю воронку и финансы… это займёт до минуты.")
    reply = await asyncio.get_event_loop().run_in_executor(None, lambda: B.sales_agent_sync(ask))
    if not reply:
        await update.message.reply_text("Не удалось получить разбор 😔 Попробуй ещё раз.")
        return
    B.remember_seller("assistant", "разбор воронки" + (f" по запросу: {ask[:120]}" if ask else ""))
    await _reply_chunks(update, "💼 *Продавец:*\n\n", reply)


async def _send_digest(bot, chat_id: int):
    """Сгенерировать и отправить дайджест: карточка-изображение + текст частями."""
    topic, text, quotes = await asyncio.get_event_loop().run_in_executor(
        None, B.sales_digest_sync)
    if not text:
        await bot.send_message(chat_id, "Не собрался дайджест 😔 Попробуй /digest ещё раз.")
        return False
    when = datetime.now(B.BERLIN).strftime("%d.%m.%Y") if B.BERLIN else datetime.now().strftime("%d.%m.%Y")
    card = await asyncio.get_event_loop().run_in_executor(
        None, lambda: B.render_sales_card(topic, quotes[0] if quotes else "", when))
    if card:
        try:
            with open(card, "rb") as f:
                await bot.send_photo(chat_id, f, caption=("🌅 " + topic) if topic else "🌅 Утро продаж")
        except Exception as e:
            log.error(f"digest photo: {e}")
        finally:
            try:
                os.unlink(card)
            except Exception:
                pass
    header = f"🌅 *{topic}*\n\n" if topic else ""
    for chunk in B._split_msg(header + text, 3800):
        try:
            await bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception:
            await bot.send_message(chat_id, chunk.replace("*", "").replace("_", ""))
    return True


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Дайджест вручную (без дневной заявки — можно сколько угодно, тема всегда новая)."""
    chat_id = update.effective_chat.id
    owner = B.get_chat_id()
    if owner and chat_id != owner:
        return
    B.save_chat_id(chat_id)
    await update.message.reply_text(
        "🌅 Готовлю дайджест: свежий ресёрч + твоя воронка… ~1–2 минуты.")
    await _send_digest(ctx.bot, chat_id)


async def sales_morning(ctx: ContextTypes.DEFAULT_TYPE):
    """Ежедневно 07:00 Berlin. Атомарная заявка в общей БД — дубли исключены,
    даже если живы два процесса бота."""
    chat_id = B.get_chat_id()
    if not chat_id:
        return
    today = (datetime.now(B.BERLIN) if B.BERLIN else datetime.now()).strftime("%Y-%m-%d")
    if not B._claim_daily("sales_digest:" + today):
        return
    try:
        await _send_digest(ctx.bot, chat_id)
    except Exception as e:
        log.error(f"sales_morning: {e}")


async def _route_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, txt: str):
    """Единый маршрут текста/голоса: диалоговый Продавец с памятью переписки."""
    B.remember_seller("user", txt)
    await update.message.reply_text("💼 Думаю…")
    reply = await asyncio.get_event_loop().run_in_executor(
        None, lambda: B.sales_dialog_sync(txt))
    if not reply:
        await update.message.reply_text("Не получилось ответить 😔 Попробуй ещё раз.")
        return
    B.remember_seller("assistant", reply[:1500])
    await _reply_chunks(update, "", reply)
    if _voice_on():
        try:
            await B.speak_reply(update, reply)
        except Exception as e:
            log.error(f"sales voice reply: {e}")


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
    token = B.get_sales_token()
    if not token:
        raise SystemExit(
            "Токен Продавец-бота не задан. Создай бота у @BotFather и пришли токен "
            "секретарю командой /setsalestoken ТОКЕН, либо задай SALES_BOT_TOKEN в окружении."
        )
    try:
        B.ensure_sales_kb()      # база знаний Продавца
        B.ensure_strategy_kb()   # маркетинг-контекст Стратега (ссылки из SKILL.md)
        B.ensure_legal_kb()      # финансово-правовые справки для границ §19
    except Exception as e:
        log.error(f"ensure kb: {e}")

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["sales", "seller"], cmd_sales))
    app.add_handler(CommandHandler(["funnel", "voronka"], cmd_funnel))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("ip", cmd_ip))
    app.add_handler(CommandHandler(["voice", "voice_on", "voice_off"], cmd_voice))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    jq = app.job_queue
    digest_t = time(7, 0, tzinfo=B.BERLIN) if B.BERLIN else time(7, 0)
    jq.run_daily(sales_morning, time=digest_t)

    log.info("Продавец-бот запущен 💼")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
