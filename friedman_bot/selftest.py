"""Экзамен перед обновлением.

Бот сдаёт его сам, каждый раз перед тем как поставить новый код. Не сдал —
новый код не ставится, бот остаётся на прежней версии и пишет владельцу, какое
действие сломалось.

ЗАЧЕМ. Раньше обновление проверяло у нового кода только грамматику
(py_compile): написано ли без опечаток. Работает ли — не проверял никто, и
ошибки находил владелец, в живом боте. Самый частый их вид — МОЛЧАЛИВОЕ
БЕЗДЕЙСТВИЕ: «переименовал» — а не переименовал, «добавил в календарь» — а
положил в хаос. Грамматика у такого кода безупречна. Поймать его можно только
одним способом: сделать действие и посмотреть, изменилась ли база.

КАК. Всё идёт на пустой черновой базе во временной папке — боевая не
трогается никогда. Сеть, модель и браузер не нужны: проверяется только то, что
детерминировано. Поэтому экзамен не падает от погоды — только от поломки.

Запуск: python3 selftest.py  → код выхода 0 = сдан, 1 = нет (список провалов в stdout).
Каждое обновление гоняет СВОЙ экзамен из новой версии, поэтому починка самого
экзамена доезжает тем же путём и не запирает обновления.
"""
import os
import sys
import shutil
import sqlite3
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))

failures = []
passed = 0


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f"{name}" + (f" — {detail}" if detail else ""))


def step(name, fn):
    """Шаг, который сам по себе может упасть исключением: это тоже провал."""
    try:
        fn()
    except Exception as e:
        failures.append(f"{name} — исключение: {type(e).__name__}: {str(e)[:160]}")


def _got(r):
    """Что вернуло действие — для текста провала, при любой форме ответа."""
    return f"вернуло {str(r)[:120]}"


def _fingerprint(path):
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _copy_code(dst):
    """Копия кода без данных. Модули при импорте сами лезут в базу рядом со своим
    файлом (токен сессии, схема, первичная сборка finance.db) — поэтому экзамен
    импортирует их из копии, и все такие пути смотрят в черновик."""
    for name in os.listdir(HERE):
        src = os.path.join(HERE, name)
        if os.path.isdir(src):
            if name.endswith("_kb") or name == "finance_inbox":
                shutil.copytree(src, os.path.join(dst, name))
        elif name.endswith((".py", ".json", ".md")):
            shutil.copy2(src, os.path.join(dst, name))


def main():
    # боевые базы рядом с кодом (если есть) не должны шелохнуться — это тоже проверка
    live = [os.path.join(HERE, n) for n in ("friedman.db", "finance.db")]
    live_before = [_fingerprint(p) for p in live]
    scratch = tempfile.mkdtemp(prefix="selftest_")
    code = os.path.join(scratch, "code")
    os.makedirs(code)
    _copy_code(code)
    sys.path.insert(0, code)
    db_path = os.path.join(code, "friedman.db")

    import bot
    bot.DB = db_path                 # всё ниже пишет ТОЛЬКО в черновик
    bot.init_db()

    def q(sql, args=()):
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    # ── календарь ─────────────────────────────────────────────────────────
    def t_plan():
        r = bot.apply_actions([{"type": "plan", "text": "Экзамен: встреча",
                                "date": "2030-05-14", "time": "9.05"}])
        rows = q("SELECT date, time FROM events WHERE text='Экзамен: встреча'")
        check("plan кладёт дело в календарь", len(rows) == 1, f"строк: {len(rows)}")
        check("plan выправляет время 9.05 → 09:05",
              rows and rows[0]["time"] == "09:05", rows and rows[0]["time"])
        check("plan не кладёт копию в парковку",
              not q("SELECT 1 FROM chaos WHERE text='Экзамен: встреча'"))
        check("plan отчитывается об успехе", r and r[0][0] == "plan", _got(r))
    step("plan", t_plan)

    def t_plan_batch():
        bot.apply_actions([{"type": "plan", "items": [
            {"text": "Экзамен: матч 1", "date": "2030-05-20", "time": "14:00"},
            {"text": "Экзамен: матч 2", "date": "2030-05-27", "time": "14:00"}]}])
        n = q("SELECT COUNT(*) n FROM events WHERE text LIKE 'Экзамен: матч%'")[0]["n"]
        check("plan пачкой кладёт каждое дело", n == 2, f"легло {n} из 2")
    step("plan пачкой", t_plan_batch)

    def t_plan_nodate():
        before = q("SELECT COUNT(*) n FROM events")[0]["n"]
        r = bot.apply_actions([{"type": "plan", "text": "Экзамен: когда-нибудь"}])
        after = q("SELECT COUNT(*) n FROM events")[0]["n"]
        check("plan без даты ничего не пишет", before == after)
        check("plan без даты честно отказывает", r and r[0][0] == "plan_fail", _got(r))
    step("plan без даты", t_plan_nodate)

    # ── парковка и переименование ─────────────────────────────────────────
    def t_save_rename():
        bot.apply_actions([{"type": "save", "text": "Экзамен: эскиз Хорц",
                            "area": "work", "importance": 7, "urgency": 7}])
        rows = q("SELECT id FROM chaos WHERE text='Экзамен: эскиз Хорц'")
        check("save кладёт вводную в парковку", len(rows) == 1)
        r = bot.apply_actions([{"type": "rename", "old": "Экзамен: эскиз Хорц",
                                "text": "Экзамен: эскиз Хорц — финал"}])
        check("rename по тексту меняет название",
              q("SELECT 1 FROM chaos WHERE text='Экзамен: эскиз Хорц — финал'"),
              _got(r))
    step("save и rename", t_save_rename)

    def t_rename_ambiguous():
        bot.apply_actions([{"type": "save", "text": "Экзамен: двойник А", "area": "work"},
                           {"type": "save", "text": "Экзамен: двойник Б", "area": "work"}])
        r = bot.apply_actions([{"type": "rename", "old": "Экзамен: двойник",
                                "text": "не должно случиться"}])
        check("rename не трогает ничего при двусмысленности",
              not q("SELECT 1 FROM chaos WHERE text='не должно случиться'"))
        check("rename при двусмысленности отказывает",
              r and r[0][0] == "rename_fail", _got(r))
    step("rename двусмысленный", t_rename_ambiguous)

    def t_done():
        cid = q("SELECT id FROM chaos WHERE text='Экзамен: эскиз Хорц — финал'")[0]["id"]
        bot.apply_actions([{"type": "done", "id": cid}])
        check("done закрывает вводную",
              q("SELECT done FROM chaos WHERE id=?", (cid,))[0]["done"] == 1)
    step("done", t_done)

    def t_remind():
        bot.apply_actions([{"type": "remind", "when": "2030-05-14 09:00",
                            "text": "Экзамен: напоминание"}])
        check("remind записывает напоминание",
              q("SELECT 1 FROM reminders WHERE text='Экзамен: напоминание'"))
    step("remind", t_remind)

    # ── оформление календаря ──────────────────────────────────────────────
    def t_decor():
        bot.apply_actions([{"type": "decor", "title": "ЭКЗАМЕН",
                            "from": "2030-10-14", "to": "2030-10-16",
                            "pattern": "crosses"}])
        check("decor ставит полосу", q("SELECT 1 FROM cal_decor WHERE title='ЭКЗАМЕН'"))
        bot.apply_actions([{"type": "decor", "title": "ЭКЗАМЕН",
                            "from": "2030-10-16", "to": "2030-10-18",
                            "pattern": "crosses"}])
        rows = q("SELECT date_from FROM cal_decor WHERE title='ЭКЗАМЕН'")
        check("decor с той же надписью переставляет, а не дублирует",
              len(rows) == 1 and rows[0]["date_from"] == "2030-10-16",
              f"полос {len(rows)}")
        bot.apply_actions([{"type": "decor_delete", "title": "ЭКЗАМЕН"}])
        check("decor_delete убирает полосу",
              not q("SELECT 1 FROM cal_decor WHERE title='ЭКЗАМЕН'"))
    step("decor", t_decor)

    # ── то, что читают модель, дашборд и свод ─────────────────────────────
    def t_context():
        ctx = bot.get_context()
        check("контекст Секретаря собирается и содержит календарь",
              isinstance(ctx, str) and "Экзамен" in ctx)
    step("контекст Секретаря", t_context)

    def t_status():
        def offline():
            raise OSError("экзамен без сети")
        real, bot._remote_sha = bot._remote_sha, offline
        try:
            text = bot._status_report_sync()
        finally:
            bot._remote_sha = real
        check("/status собирается и видит всех",
              all(n in text for n in ("Секретарь", "Финансист", "Дашборд", "Копия", "Версия")),
              text[:120])
    step("/status", t_status)

    def t_quiet():
        check("до обновления боты стартуют с легендой", not bot.quiet_start_active())
        bot._start_quiet_window()
        check("после обновления боты стартуют молча", bot.quiet_start_active())
    step("тихий старт после обновления", t_quiet)

    def t_bank_replace():
        import json
        import finance_core as fc
        fin = os.path.join(scratch, "finance_test.db")
        path = os.path.join(code, "finance_inbox", "bank_selftest.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def put(rows):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            with fc.fdb(fin) as c:
                fc.ensure_schema(c)
                fc.import_bank_json(c, path)
                return c.execute("SELECT COUNT(*) n, ROUND(SUM(amount),2) s FROM fin_payment").fetchone()
        put([{"date": "2030-08-07", "amount": 5000, "party": "cosmopop скриншот"}])
        n, s = put([{"date": "2030-08-07", "amount": 5000, "party": "Gutschrift cosmopop GmbH RNr. 1"},
                    {"date": "2030-08-08", "amount": -20, "party": "REWE"}])
        check("новая версия выписки заменяет старую, а не удваивает деньги",
              n == 2 and s == 4980, f"строк {n}, сумма {s}")
    step("выписка: замена версии", t_bank_replace)

    def t_vat():
        # С 2026 — обязательная Regelbesteuerung: счёт без ставки обязан выйти с 19 %
        import invoice
        seen = {}
        real = (invoice.generate_invoice, bot.register_own_invoice, bot.upsert_client)

        def fake(**kw):
            seen.update(kw)
            return ("", 1190.0, kw.get("number"))
        invoice.generate_invoice = fake
        bot.register_own_invoice = lambda *a, **k: seen.__setitem__("reg", a[-1])
        bot.upsert_client = lambda *a, **k: None
        try:
            bot.apply_actions([{"type": "invoice", "recipient": "Экзамен GmbH\nStr. 1\n60311 Frankfurt",
                                "items": [{"desc": "Wand", "price": 1000}]}])
        finally:
            invoice.generate_invoice, bot.register_own_invoice, bot.upsert_client = real
        check("счёт без ставки выходит с 19 % USt (не §19)",
              seen.get("vat_rate") == 19 and seen.get("reg") == 19, str(seen.get("vat_rate")))
        bot.seed_ust_case()
        bot.seed_ust_case()
        check("дело [ust] о Regelbesteuerung заведено один раз",
              len(q("SELECT 1 FROM bureau_cases WHERE topic='ust'")) == 1)
    step("НДС с 2026", t_vat)

    def t_issued():
        # Счета из ISSUED_INVOICES сервер собирает сам — описание должно давать
        # корректный счёт: оплачен → без «bitte überweisen», сумма сходится.
        import invoice
        totals = {}
        for inv in bot.ISSUED_INVOICES:
            html_text, total = invoice._build_html(
                recipient=inv["recipient"], items=inv["items"], number=inv["number"],
                salutation=inv.get("salutation"), customer_no=inv.get("customer_no", ""),
                intro=inv.get("intro"), dt=__import__("datetime").datetime(2026, 9, 22),
                vat_rate=inv.get("vat_rate"), title=inv.get("title", "Rechnung"),
                service_note=inv.get("service_note", ""), paid_note=inv.get("paid_note", ""),
                no_tax_note=inv.get("no_tax_note", False), show_bank=inv.get("show_bank"))
            totals[inv["number"]] = round(total, 2)
            ok = (("Bitte überweisen Sie den Rechnungsbetrag" not in html_text)
                  == bool(inv.get("paid_note"))) \
                and "Leistung" in html_text and "Als Kleinunternehmer" not in html_text
            check(f"счёт {inv['number']} собирается корректно", ok)
        check("суммы счетов 22.09.2026: 1 487,50 · 1 000,00 · 820,80",
              totals == {"220926": 1487.5, "220926-1": 1000.0, "220926-2": 820.8}, str(totals))
    step("счета 22.09.2026", t_issued)

    def t_dashboard():
        import dashboard
        dashboard.DB = db_path
        with dashboard.db() as c:        # своя схема дашборда, как при его старте
            dashboard.ensure_schema(c)
        data = dashboard.get_data()
        for k in ("chaos", "cards", "projects", "decor", "rev"):
            check(f"дашборд отдаёт «{k}»", k in data)
        check("дашборд видит дела из календаря",
              any("Экзамен" in str(c.get("text")) for c in data.get("cards", [])))
    step("дашборд", t_dashboard)

    def t_ux():
        # Журнал действий: дашборд пишет, бот сводит. Текст дел в журнал не идёт —
        # только устройство интерфейса.
        import dashboard
        evs = [{"ts": "2099-01-01T10:00:00Z", "sid": "t", "page": "plan", "kind": "open",
                "target": "plan", "extra": "h:10"},
               {"ts": "2099-01-01T10:00:02Z", "sid": "t", "page": "cal", "kind": "page",
                "target": "cal", "extra": "from:plan;first"}]
        evs += [{"ts": "2099-01-01T10:00:%02dZ" % (5 + i), "sid": "t", "page": "cal",
                 "kind": "tap", "target": "вкладка:cal", "x": .3, "y": .12, "w": 60, "h": 50}
                for i in range(30)]
        r = dashboard.api_ux({"events": evs})
        check("журнал действий принимает события", r.get("n") == 32, str(r))
        st = bot.ux_stats(36500 * 2)
        check("бот видит первый шаг «Мостик → Календарь»",
              st.get("first_move") and st["first_move"][0][0] == "Мостик → Календарь",
              str(st.get("first_move")))
        check("частая кнопка вверху экрана помечена как неудобная",
              any(t["target"] == "вкладка:cal" for t in st.get("hard_to_reach", [])))
    step("журнал действий (UX)", t_ux)

    def t_svod():
        import report_pages
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            pages, act, g = report_pages.build(c, fix=False, insight=False)
        finally:
            c.close()
        check("свод собирает страницы", len(pages) >= 1, f"страниц {len(pages)}")
    step("свод", t_svod)

    check("боевые базы не тронуты экзаменом",
          [_fingerprint(p) for p in live] == live_before)
    shutil.rmtree(scratch, ignore_errors=True)

    total = passed + len(failures)
    if failures:
        print(f"ЭКЗАМЕН НЕ СДАН: {len(failures)} из {total}")
        for f in failures:
            print("  ✗ " + f)
        return 1
    print(f"экзамен сдан: {passed} проверок")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # упал сам импорт или подготовка — это тоже провал, и о нём надо сказать
        print("ЭКЗАМЕН НЕ СДАН: не удалось даже начать")
        print(traceback.format_exc()[-800:])
        sys.exit(1)
