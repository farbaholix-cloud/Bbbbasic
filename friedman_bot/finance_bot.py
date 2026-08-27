"""
Финансист — отдельный Telegram-бот денежного контура FARBAHOLIX.

ЧЕМ ОН ОТЛИЧАЕТСЯ ОТ ОСТАЛЬНЫХ БОТОВ
------------------------------------
Секретарь, Юрист и Продавец сначала спрашивают модель, а данные подкладывают как
подсказку. Здесь наоборот: цифры считает SQL (finance_core), модель только
объясняет уже посчитанное. Отсюда два следствия:

1. Команды /year /month /open /todo /sum вообще НЕ зовут ИИ — это чистый запрос
   к базе. Соврать физически нечем; ответ одинаков в боте, в дашборде и в отчёте.
2. В свободном диалоге модель получает context_block() с уже готовыми суммами и
   явной «границей знания». Считать самой ей запрещено промптом.

Запуск: отдельный процесс. Токен — из FINANCE_BOT_TOKEN или из настройки
finance_bot_token в friedman.db (команда /setfinancetoken Секретарю). См. finance_kb/SKILL.md,
раздел «Подключение бота»).
"""

import asyncio
import logging
import os
import sys
from datetime import date, datetime

import finance_core as fc

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [fin] %(message)s")
log = logging.getLogger("fin")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIN_KB_DIR = os.path.join(BASE_DIR, "finance_kb")
BACKUP_DIR = os.environ.get("FIN_BACKUP_DIR", os.path.expanduser("~/FARBAHOLIX/backup"))

GREETING = (
    "💶 *Финансист на связи.*\n\n"
    "Я веду отдельную денежную базу и отвечаю только по ней. Моё правило: "
    "*доход — это деньги, пришедшие на счёт*, а выставленный счёт — ещё не доход. "
    "Если данных за период нет, я скажу «нет данных», а не назову ноль.\n\n"
    "*Точные команды (считает база, не ИИ):*\n"
    "• `/year 2025` — год: выставлено, получено, расходы, нетто, что висит\n"
    "• `/month 2026-05` — месяц\n"
    "• `/open` — незакрытые счета\n"
    "• `/todo` — поступления, которые надо опознать\n"
    "• `/sum` — общая сводка и граница данных\n"
    "• `/sync` — импорт нового из `finance_inbox/` + сверка\n"
    "• `/backup` — шифрованный MD-бэкап\n\n"
    "Свободным текстом — объясню, сравню, найду причину. "
    "Юридические и налоговые выводы — не ко мне, а к Юристу: я дам ему цифры."
)

FINANCE_PROMPT = """Ты — «Финансист», денежный контур FARBAHOLIX (Вячеслав/Slavik, художник-фрилансер в Германии, Freiberufler Künstler, Kleinunternehmer §19, статус §24).

ЖЕЛЕЗНЫЕ ПРАВИЛА (нарушение = профнепригодность):
1. НЕ СЧИТАЙ САМ. Все суммы уже посчитаны в блоке ФИНАНСОВЫЕ ДАННЫЕ ниже. Бери числа оттуда дословно. Если нужной цифры там нет — так и скажи и предложи команду (/year, /month, /open), а НЕ прикидывай.
2. ГРАНИЦА ЗНАНИЯ. За периодом, который не покрыт выписками, данных НЕТ. Отвечай «данных за этот период нет, выписки заканчиваются <дата>». Ноль вместо «неизвестно» — грубая ошибка.
3. ДОХОД = ДЕНЬГИ НА СЧЕТУ. Выставленный счёт — это обязательство клиента, не доход. Всегда разделяй «выставлено» и «получено»; если пользователь смешивает — мягко поправь.
4. НИКАКИХ ПРИДУМАННЫХ КЛИЕНТОВ, НОМЕРОВ И ДАТ. Только то, что есть в данных.
5. Если в данных есть раздел «ТРЕБУЕТ РЕШЕНИЯ ХОЗЯИНА» и вопрос касается этих сумм — скажи, что часть поступлений не опознана, и назови их.

МАРШРУТИЗАЦИЯ К ДРУГИМ АГЕНТАМ (ты часть команды, а не один в поле):
- Налоги, §19/Kleinunternehmer, USt, EÜR/ELSTER, законность, форма счёта, договоры → это ЮРИСТ. Ты даёшь ему цифры и говоришь: «правовой финал — у Юриста». Свои налоговые выводы не выдавай за окончательные.
- Дожать оплату, переговоры, цена, письмо клиенту → ПРОДАВЕЦ. Ты даёшь список должников и сроки.
- Запланировать дело, напомнить, календарь, проекты → СЕКРЕТАРЬ. Деньги у него больше не ведутся.
- Стратегия, приоритеты, «что делать» в целом → ДИРЕКТОР. Ему нужны точные цифры без округлений «на глаз».
Маркетолог (в совете Стратега) — приток лидов; денежных данных не ведёт.

ТОН: по-русски, на «ты», коротко и по делу. Суммы — с валютой и за какой период. Если цифра выглядит тревожно (кассовый разрыв, старый долг клиента) — скажи прямо и предложи следующий шаг.

БАЗА ЗНАНИЙ: {kb}. SKILL.md вшит ниже — Read по нему не нужен. Детали в references/*.md читай Read'ом только если вопрос реально этого требует.

Сегодня: {today}.
"""


# ───────────────────────────── детерминированные ответы ────────────────────────
# Ниже — ответы БЕЗ участия ИИ. Их можно сверять с выпиской построчно.

def _eur(x):
    return "{:,.2f} €".format(x or 0).replace(",", " ")


def r_year(arg):
    y = (arg or str(date.today().year)).strip()[:4]
    if not y.isdigit():
        return "Нужен год: `/year 2025`"
    with fc.fdb_ro() as c:
        rep = fc.year_report(c, y)
        if not rep["received_count"] and not rep["invoiced_count"]:
            return "За %s в базе нет ни счетов, ни поступлений." % y
        L = ["*%s год*" % y, "",
             "💰 Получено на счёт: *%s* (%d поступлений)" % (_eur(rep["received"]), rep["received_count"]),
             "🧾 Выставлено счетов: %s (%d шт.)" % (_eur(rep["invoiced"]), rep["invoiced_count"]),
             "💸 Расходы: %s" % _eur(rep["spent"]),
             "📊 Нетто (получено − расходы): *%s*" % _eur(rep["net"])]
        if rep["open_invoices"]:
            L.append("")
            L.append("⏳ Не оплачено по счетам %s года — %s:" % (y, _eur(rep["open_total"])))
            for o in rep["open_invoices"]:
                L.append("   • %s №%s %s — %s (%d дн.)"
                         % (o["date"], o["number"], o["client"], _eur(o["open"]), o["days"]))
        if rep["unmatched_income"]:
            L.append("")
            L.append("⚠️ Не опознано поступлений: %d — см. /todo" % rep["unmatched_income"])
        if rep["coverage_warning"]:
            L.append("")
            L.append("❗️ " + rep["coverage_warning"])
        return "\n".join(L)


def r_month(arg):
    ym = (arg or datetime.now().strftime("%Y-%m")).strip()[:7]
    if len(ym) != 7 or ym[4] != "-":
        return "Нужен месяц: `/month 2026-05`"
    with fc.fdb_ro() as c:
        warn = fc.assert_covered(c, ym)
        # Непокрытый период: показывать нули нельзя — «0 €» читается как «не заработал»,
        # хотя правда в том, что мы просто не знаем. Отдаём только предупреждение.
        if warn:
            inv = fc.invoiced(c, month=ym)
            L = ["*%s*" % ym, "", "❗️ " + warn]
            if inv["count"]:
                L += ["", "Известно только про счета: выставлено %s (%d шт.). "
                          "Пришли ли по ним деньги — неизвестно." % (_eur(inv["total"]), inv["count"])]
            L += ["", "Пришли выписку за этот период — `/sync`, и цифры появятся."]
            return "\n".join(L)
        rec, inv, sp = fc.received(c, month=ym), fc.invoiced(c, month=ym), fc.spent(c, month=ym)
        L = ["*%s*" % ym, "",
             "💰 Получено: *%s* (%d)" % (_eur(rec["total"]), rec["count"]),
             "🧾 Выставлено: %s (%d)" % (_eur(inv["total"]), inv["count"]),
             "💸 Расходы: %s" % _eur(sp["total"])]
        if not rec["count"] and not inv["count"]:
            L += ["", "_Движений и счетов в этом месяце не было._"]
        return "\n".join(L)


def r_open():
    with fc.fdb_ro() as c:
        op = fc.open_invoices(c)
    if not op:
        return "Незакрытых счетов нет — всё оплачено."
    L = ["*Незакрытые счета — %d шт. на %s*" % (len(op), _eur(sum(o["open"] for o in op))), ""]
    for o in sorted(op, key=lambda x: -x["days"]):
        mark = "🔴" if o["days"] > 90 else ("🟡" if o["days"] > 30 else "🟢")
        L.append("%s %s №%s — %s\n   %s · %s · %d дн." % (
            mark, o["client"], o["number"], _eur(o["open"]), o["date"],
            "оплачен частично: " + _eur(o["paid"]) if o["paid"] > 0.01 else "оплат не было", o["days"]))
    L.append("")
    L.append("_Дожать — задача Продавца; скажи ему, кого именно._")
    return "\n".join(L)


def r_todo():
    with fc.fdb_ro() as c:
        sug = fc.suggest_matches(c)
        rev = fc.income_review(c)
    tail = []
    if rev:
        # Отдельный класс ошибок: банк пометил приход как «прочий доход», и деньги
        # не попали в выручку вообще. Так выпали 3 000 € от Klügling Café.
        tail = ["", "*Прочий доход — это точно не клиент?* (%d)" % len(rev),
                "_Если клиент — деньги сейчас НЕ в выручке._"]
        for r in rev:
            tail.append("• %s · %s — `%s`" % (r["date"], _eur(r["amount"]), r["party"][:80]))
    if not sug:
        return "Все поступления разнесены по счетам." + ("\n".join(tail) if tail else "")
    L = ["*Поступления без однозначного счёта — %d*" % len(sug),
         "_Я не угадываю: подтверди, и я запишу._", ""]
    for s in sug:
        p = s["payment"]
        L.append("• *%s · %s*\n  `%s`" % (p["date"], _eur(p["amount"]), p["party"][:90]))
        for cand in s["candidates"]:
            L.append("  → счёт *%s* от %s (%s, открыто %s) — %s"
                     % (cand["number"], cand["date"], cand["client"], _eur(cand["open"]), cand["why"]))
        if not s["candidates"]:
            L.append("  → похожих счетов нет — возможно, это не оплата счёта")
    L.append("")
    L.append("Подтвердить: `/link <номер счёта> <дата платежа> <сумма>`")
    return "\n".join(L + tail)


def r_sum():
    with fc.fdb_ro() as c:
        cov = fc.coverage(c)
        L = ["*Сводка денежной базы*", "",
             "🗓 Выписки: %s … %s (%d операций)" % (cov["bank_from"], cov["bank_to"], cov["payments"]),
             "🧾 Счета: %s … %s (%d шт.)" % (cov["inv_from"], cov["inv_to"], cov["invoices"]), ""]
        for y in [r["y"] for r in c.execute(
                "SELECT DISTINCT substr(val_date,1,4) y FROM fin_payment ORDER BY y")]:
            rep = fc.year_report(c, y)
            L.append("*%s* — получено %s | выставлено %s | расходы %s"
                     % (y, _eur(rep["received"]), _eur(rep["invoiced"]), _eur(rep["spent"])))
        op = fc.open_invoices(c)
        L += ["", "⏳ Висит по счетам: *%s* (%d шт.) — /open" % (_eur(sum(o["open"] for o in op)), len(op))]
        L += ["", "❗️ После *%s* банковских данных нет. Пришли свежую выписку — /sync" % cov["bank_to"]]
        L += ["", "_Источники:_"]
        for s in cov["sources"]:
            L.append("_• %s — %s, %d строк, %s…%s_"
                     % (s["path"], s["kind"], s["rows_total"], s["period_from"], s["period_to"]))
        return "\n".join(L)


def r_sync():
    rep = fc.bootstrap(verbose=False)
    L = ["*Синхронизация*", ""]
    touched = False
    for im in rep["imports"]:
        if im.get("error"):
            L.append("❌ %s — %s" % (im.get("path", "?"), im["error"])); touched = True
        elif im.get("skipped"):
            L.append("• %s — без изменений" % im.get("path", "?"))
        else:
            L.append("✅ %s — новых строк %d из %d (%s…%s)"
                     % (im["path"], im["new"], im["seen"], im["period"][0], im["period"][1]))
            touched = touched or im["new"] > 0
    rc = rep["reconcile"]
    L += ["", "🔗 Сверка: связано по номеру %d, частичных %d, по сумме %d, «один платёж — "
          "несколько счетов» %d" % (rc["matched_by_number"], rc["matched_partial"],
                                    rc["matched_by_amount"], rc["matched_sum_of_invoices"]),
          "📌 Открытых счетов: %d · неразнесённых поступлений: %d"
          % (rc["invoices_open"], rc["payments_unlinked"])]
    if not touched:
        L += ["", "_Новых данных не было. Положи файл в `finance_inbox/` — подхвачу._"]
    return "\n".join(L)


def r_link(arg):
    parts = (arg or "").split()
    if len(parts) < 3:
        return "Формат: `/link <номер счёта> <дата платежа> <сумма>`\nНапример: `/link 270524 28.05.2024 300`"
    with fc.fdb() as c:
        res = fc.confirm_match(c, parts[0], parts[1], fc.to_amount(parts[2]))
    if not res.get("ok"):
        return "❌ " + res["error"]
    return "✅ Счёт %s закрыт платежом %s на %s." % (res["invoice"], res["payment"], _eur(res["amount"]))


DETERMINISTIC = {
    "year": r_year, "month": r_month, "open": lambda a: r_open(), "todo": lambda a: r_todo(),
    "sum": lambda a: r_sum(), "sync": lambda a: r_sync(), "link": r_link,
}


# ───────────────────────────────── свободный диалог ────────────────────────────

def ask_financier_sync(user_text):
    """Свободный вопрос: модель объясняет уже посчитанное. Мозг — общий с
    остальными агентами (bot.py), но контекст здесь свой и авторитетный."""
    try:
        import bot as B
    except Exception as e:
        log.error("bot.py недоступен: %s", e)
        return ("Мозг для свободного диалога сейчас недоступен, но точные команды работают: "
                "/year, /month, /open, /todo, /sum.")
    with fc.fdb_ro() as c:
        ctx = fc.context_block(c)
    sys_prompt = (FINANCE_PROMPT
                  .replace("{kb}", FIN_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    skill = B._kb_inline(os.path.join(FIN_KB_DIR, "SKILL.md"))
    if skill:
        sys_prompt += "\n\n=== SKILL.md (уже прочитан, Read не нужен) ===\n" + skill
    sys_prompt += "\n\n" + ctx
    try:
        res = B._claude_exec([B.CLAUDE_BIN, "-p", user_text,
                              "--append-system-prompt", sys_prompt,
                              "--allowedTools", "Read",
                              "--model", "sonnet", "--max-turns", "6"], timeout=240)
        raw = (res.stdout or "").strip()
        if raw.startswith("{"):
            import json as _j
            try:
                return _j.loads(raw).get("reply") or raw
            except Exception:
                pass
        return raw or "Не смог сформулировать ответ — переформулируй вопрос."
    except Exception as e:
        log.error("financier CLI: %s", e)
        return "Ошибка обращения к мозгу. Точные команды работают: /year, /month, /open, /sum."


# ──────────────────────────────── telegram-обвязка ─────────────────────────────

def get_token():
    """Токен: окружение → настройка в общей базе Секретаря (никогда не в git).

    Именно так берут токен Юрист и Продавец. В первой версии Финансист читал
    ТОЛЬКО переменную окружения — а команда /setfinancetoken кладёт токен в
    таблицу settings базы friedman.db. Бот не находил его, сразу завершался,
    и сторож поднимал труп каждые пять минут."""
    raw = os.environ.get("FINANCE_BOT_TOKEN") or ""
    if not raw:
        try:
            import sqlite3
            db = os.path.join(BASE_DIR, "friedman.db")
            if os.path.exists(db):
                conn = sqlite3.connect(db, timeout=10)
                try:
                    row = conn.execute(
                        "SELECT value FROM settings WHERE key='finance_bot_token'").fetchone()
                    raw = (row[0] if row else "") or ""
                finally:
                    conn.close()
        except Exception as e:
            log.error("токен из базы не прочитался: %s", e)
    return "".join(raw.split())          # Telegram иногда вставляет пробел в токен


def main():
    token = get_token()
    if not token:
        sys.exit("Токен не задан. Пришли Секретарю: /setfinancetoken <токен> "
                 "(или положи FINANCE_BOT_TOKEN в .env) — см. finance_kb/SKILL.md")
    from telegram import Update
    from telegram.constants import ParseMode
    from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

    fc.bootstrap(verbose=False)      # база готова к первому же вопросу

    async def _send(update, text):
        """Ответ частями. Если Telegram не принял разметку (в назначениях платежей
        попадаются _ * [ ], которые ломают Markdown) — шлём тем же текстом без
        разметки. Молчание вместо ответа хуже, чем ответ без жирного шрифта."""
        for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]:
            try:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.warning("Markdown отклонён (%s) — шлю без разметки", e)
                await update.message.reply_text(chunk)

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await _send(update, GREETING)

    def make_cmd(name, fn):
        async def h(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            arg = " ".join(ctx.args) if ctx.args else ""
            try:
                await _send(update, fn(arg))
            except Exception as e:
                log.exception("%s", name)
                await update.message.reply_text("Ошибка в /%s: %s" % (name, e))
        return h

    async def backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        pw = os.environ.get("FIN_BACKUP_PASS")
        if not pw:
            await update.message.reply_text(
                "Не задан FIN_BACKUP_PASS — без пароля шифрованный бэкап не сделать.\n"
                "Добавь его в .env и повтори.")
            return
        import finance_backup as fb
        made = fb.make_backup(BACKUP_DIR, plain=False, encrypted=True, password=pw)
        enc = [p for p in made if p.endswith(".md.enc")][0]
        await update.message.reply_document(
            document=open(enc, "rb"), filename=os.path.basename(enc),
            caption="Шифрованный срез базы. Расшифровать:\n"
                    "`python3 finance_backup.py --decrypt <файл>`",
            parse_mode=ParseMode.MARKDOWN)

    async def free_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        wait = await update.message.reply_text("💶 Считаю по базе…")
        txt = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ask_financier_sync(update.message.text or ""))
        try:
            await wait.delete()
        except Exception:
            pass
        await _send(update, txt)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    for name, fn in DETERMINISTIC.items():
        app.add_handler(CommandHandler(name, make_cmd(name, fn)))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    log.info("Финансист запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        # Проверка детерминированных ответов без Telegram: то, что видит хозяин.
        fc.bootstrap(verbose=False)
        for name, arg in (("sum", ""), ("year", "2025"), ("year", "2026"),
                          ("month", "2026-05"), ("month", "2026-07"), ("open", ""), ("todo", "")):
            print("\n" + "=" * 70 + "\n/%s %s\n" % (name, arg) + "=" * 70)
            print(DETERMINISTIC[name](arg))
    else:
        main()
