"""
Финансист — ядро денежного контура FARBAHOLIX.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ И ОТДЕЛЬНАЯ БАЗА
---------------------------------------
Раньше деньги жили в общей базе Секретаря и считались так:
    «выставленный счёт» == «полученные деньги»
(таблица invoice_archive, колонка paid DEFAULT 1, группировка по inv_date).
Из-за этого дашборд показывал оборот, которого на счету никогда не было,
а «свежие» месяцы врали сильнее всего — счёт выставлен сегодня, деньги придут
через два месяца или не придут вовсе.

Здесь этот класс ошибок исключён на уровне модели данных:

  fin_invoice  — ЧТО ВЫСТАВЛЕНО (обязательство клиента). Само по себе НЕ доход.
  fin_payment  — ЧТО РЕАЛЬНО ПРИШЛО/УШЛО по банковской выписке. Единственный
                 источник правды о деньгах.
  fin_match    — связь между ними (сверка). Показывает, что оплачено, что висит.

Доход за период = сумма fin_payment (приход, деловая категория) за период.
Никогда не сумма счетов. Счета — это «ожидание», отдельная величина.

АНТИГАЛЛЮЦИНАЦИЯ
----------------
Любой ответ Финансиста строится ТОЛЬКО SQL-запросом к этим таблицам и всегда
сопровождается coverage(): до какой даты есть выписки. Если спрашивают про
период, который выпискам не покрыт, — модуль обязан сказать «данных нет»,
а не досчитывать по счетам. Функция assert_covered() выдаёт этот приговор явно.

ИДЕМПОТЕНТНЫЙ ИМПОРТ
--------------------
Раньше сид заливался один раз и гасился константой версии: файл менялся —
база молча оставалась старой («я обновил, а он не видит»). Здесь ключ импорта —
sha256 СОДЕРЖИМОГО файла (fin_source). Поменялся файл — импорт пройдёт заново
автоматически; не поменялся — работа не делается. Никаких ручных версий.
"""

import csv
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIN_DB = os.path.join(BASE_DIR, "finance.db")
INBOX_DIR = os.path.join(BASE_DIR, "finance_inbox")

# Категории прихода, которые считаются ДЕЛОВОЙ выручкой. Личные переводы
# (other_income — переводы от родственников и т.п.) в оборот не входят: путать
# их с выручкой нельзя ни для §19, ни для отчётности.
BUSINESS_INCOME_CATS = ("client_income",)

# Возврат клиенту (переплата, Rückerstattung). Хранится отрицательной суммой и
# ВЫЧИТАЕТСЯ из выручки, а не попадает в расходы: иначе один и тот же возврат
# завышал бы и доход, и затраты. Так было с Klügling Café — клиент заплатил
# дважды, 1500 € вернули, и обе стороны операции считались по отдельности.
CLIENT_REFUND_CAT = "client_refund"

CURRENCY = "EUR"


# ─────────────────────────────── инфраструктура ───────────────────────────────

@contextmanager
def fdb(path=None):
    """Соединение с базой Финансиста. Коммит при успехе, откат при ошибке,
    закрытие всегда."""
    conn = sqlite3.connect(path or FIN_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def fdb_ro(path=None):
    """Соединение ТОЛЬКО НА ЧТЕНИЕ — для остальных агентов и дашбордов.
    Писать в денежную базу имеет право лишь Финансист; физически запрещаем."""
    p = path or FIN_DB
    if not os.path.exists(p):
        raise FileNotFoundError("finance.db ещё не создана — запусти finance_core.bootstrap()")
    conn = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(conn):
    """Идемпотентная схема. Вызывается при каждом старте."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS fin_source (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,                 -- invoices | bank | manual
        imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
        rows_new INTEGER DEFAULT 0,
        rows_total INTEGER DEFAULT 0,
        period_from TEXT, period_to TEXT,
        note TEXT,
        UNIQUE(path, sha256));

    CREATE TABLE IF NOT EXISTS fin_invoice (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL,
        inv_date TEXT NOT NULL,             -- ISO YYYY-MM-DD, дата выставления
        client TEXT DEFAULT '',
        client_no TEXT DEFAULT '',
        description TEXT DEFAULT '',
        amount REAL NOT NULL,               -- брутто к оплате
        currency TEXT DEFAULT 'EUR',
        kleinunternehmer INTEGER DEFAULT 1,
        cancelled INTEGER DEFAULT 0,        -- сторно/отозван — из ожиданий убрать
        source_id INTEGER REFERENCES fin_source(id),
        note TEXT DEFAULT '',
        UNIQUE(number, inv_date));

    CREATE TABLE IF NOT EXISTS fin_payment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        val_date TEXT NOT NULL,             -- ISO, дата операции по выписке
        amount REAL NOT NULL,               -- + приход, − расход
        party TEXT DEFAULT '',              -- контрагент / назначение
        category TEXT DEFAULT '',
        account TEXT DEFAULT 'bank',
        dedup_key TEXT NOT NULL UNIQUE,
        source_id INTEGER REFERENCES fin_source(id));

    CREATE TABLE IF NOT EXISTS fin_match (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL REFERENCES fin_invoice(id) ON DELETE CASCADE,
        payment_id INTEGER NOT NULL REFERENCES fin_payment(id) ON DELETE CASCADE,
        amount REAL NOT NULL,
        method TEXT DEFAULT 'auto',         -- number | amount+client | manual
        confidence REAL DEFAULT 1.0,
        UNIQUE(invoice_id, payment_id));

    CREATE TABLE IF NOT EXISTS fin_expense_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount REAL NOT NULL,               -- положительное число = расход
        recur TEXT DEFAULT 'monthly',       -- monthly | yearly | once
        day INTEGER DEFAULT 1,
        due_date TEXT,                      -- для once
        active INTEGER DEFAULT 1,
        note TEXT DEFAULT '');

    CREATE TABLE IF NOT EXISTS fin_meta (key TEXT PRIMARY KEY, value TEXT);

    CREATE INDEX IF NOT EXISTS ix_pay_date ON fin_payment(val_date);
    CREATE INDEX IF NOT EXISTS ix_pay_cat  ON fin_payment(category);
    CREATE INDEX IF NOT EXISTS ix_inv_date ON fin_invoice(inv_date);
    """)
    _migrate(conn)


def _migrate(conn):
    """Догнать схему на живой базе. Появилось с первыми счетами с 19 % USt
    (июль 2026): до этого все счета шли по §19 и разделять брутто/нетто/налог
    было не нужно. amount остаётся БРУТТО — именно эту сумму платит клиент и
    именно она сходится с выпиской; net/vat нужны Юристу для отчётности."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(fin_invoice)").fetchall()]
    if "net" not in cols:
        conn.execute("ALTER TABLE fin_invoice ADD COLUMN net REAL")
    if "vat" not in cols:
        conn.execute("ALTER TABLE fin_invoice ADD COLUMN vat REAL DEFAULT 0")


def meta_get(conn, key, default=None):
    r = conn.execute("SELECT value FROM fin_meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def meta_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO fin_meta(key,value) VALUES(?,?)", (key, str(value)))


# ─────────────────────────────── утилиты разбора ──────────────────────────────

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def to_iso(s):
    """'26.03.2024' | '2024-03-26' | '26.03.24' → '2024-03-26'. Иначе ''."""
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})$", s)
    if m:
        d, mo, y = m.groups()
        y = int(y)
        if y < 100:
            y += 2000
        return "%04d-%02d-%02d" % (y, int(mo), int(d))
    return ""


def to_amount(s):
    """Немецкий формат сумм: '1.234,56' | '-15,00' | '1234.56' → float."""
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").strip().replace(" ", " ").replace(" ", "")
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-+]", "", s)
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s and "." in s:                 # 1.234,56 — точка тысячная
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                            # 1234,56
        s = s.replace(",", ".")
    try:
        v = float(s or 0)
    except ValueError:
        return 0.0
    return -v if neg else v


def norm_number(s):
    """Номер счёта без разделителей и регистра: 're 26.03.24' → '260324'."""
    return re.sub(r"[^0-9a-zA-Z]", "", (s or "")).lower()


def norm_party(s):
    """Схлопнуть пробелы/регистр — для устойчивого ключа дедупликации."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _dedup_key(val_date, amount, party, seq):
    """Банковские выписки не дают стабильных id. Ключ = дата+сумма+контрагент
    (+порядковый номер такого же платежа в тот же день, чтобы два одинаковых
    перевода в один день не схлопнулись в один)."""
    raw = "%s|%.2f|%s|%d" % (val_date, amount, norm_party(party)[:120], seq)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ─────────────────────────────────── импорт ───────────────────────────────────

def _register_source(conn, path, kind, note=""):
    """Вернуть (source_id, is_new). Ключ — sha256 содержимого. Если файл уже
    импортирован в этом же состоянии — is_new=False и работу можно не делать."""
    sha = _sha256(path)
    rel = os.path.relpath(path, BASE_DIR)
    row = conn.execute("SELECT id FROM fin_source WHERE path=? AND sha256=?", (rel, sha)).fetchone()
    if row:
        return row["id"], False
    cur = conn.execute(
        "INSERT INTO fin_source(path, sha256, kind, note) VALUES(?,?,?,?)", (rel, sha, kind, note))
    return cur.lastrowid, True


def _finish_source(conn, sid, rows_new, rows_total, period_from, period_to):
    conn.execute("UPDATE fin_source SET rows_new=?, rows_total=?, period_from=?, period_to=? WHERE id=?",
                 (rows_new, rows_total, period_from, period_to, sid))


def import_invoices(conn, path, force=False):
    """Счета из JSON: [{number, date, recipient, customer_no, description, total}].
    Формат совпадает с invoices_seed.json и с тем, что отдаёт Юрист."""
    sid, is_new = _register_source(conn, path, "invoices")
    if not is_new and not force:
        return {"skipped": True, "reason": "файл не менялся", "path": os.path.basename(path)}
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    new = 0
    dates = []
    for r in rows:
        iso = to_iso(r.get("date") or r.get("inv_date"))
        if not iso:
            continue
        dates.append(iso)
        amount = to_amount(r.get("total") if r.get("total") is not None else r.get("gross"))
        vat = to_amount(r.get("vat") or 0)
        net = to_amount(r.get("net")) if r.get("net") is not None else round(amount - vat, 2)
        cur = conn.execute(
            "INSERT OR IGNORE INTO fin_invoice"
            "(number, inv_date, client, client_no, description, amount, net, vat, currency,"
            " kleinunternehmer, source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ((r.get("number") or "").strip(), iso,
             (r.get("recipient") or r.get("client") or r.get("client_name") or "").strip(),
             str(r.get("customer_no") or "").strip(),
             (r.get("description") or "").strip(), amount, net, vat, CURRENCY,
             1 if r.get("kleinunternehmer", vat <= 0) else 0, sid))
        new += cur.rowcount
    _finish_source(conn, sid, new, len(rows), min(dates or [""]), max(dates or [""]))
    return {"skipped": False, "kind": "invoices", "path": os.path.basename(path),
            "new": new, "seen": len(rows),
            "period": [min(dates or [""]), max(dates or [""])]}


def import_bank_json(conn, path, force=False):
    """Банк из bank_seed.json: {'transactions': [{date, amount, cat, party}]}."""
    sid, is_new = _register_source(conn, path, "bank")
    if not is_new and not force:
        return {"skipped": True, "reason": "файл не менялся", "path": os.path.basename(path)}
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    rows = blob["transactions"] if isinstance(blob, dict) else blob
    return _ingest_payments(conn, sid, [
        {"date": r.get("date"), "amount": r.get("amount"),
         "party": r.get("party"), "category": r.get("cat") or ""} for r in rows],
        os.path.basename(path))


# Заголовки немецких банковских выгрузок (Naspa/Sparkasse/DKB/camt). Ищем по
# вхождению подстроки в нижнем регистре — банки любят менять формулировки.
_CSV_DATE = ("valutadatum", "wertstellung", "buchungstag", "buchungsdatum", "datum", "date")
_CSV_AMT = ("betrag", "umsatz", "amount", "soll/haben", "value")
_CSV_PARTY = ("beguenstigter", "begünstigter", "zahlungspflichtiger", "auftraggeber",
              "name des", "empfaenger", "empfänger", "party", "counterparty")
# Порядок ВАЖЕН: назначение платежа ищем сначала в Verwendungszweck и только
# потом в Buchungstext. В немецкой выписке номер счёта («RN 010726») живёт именно
# в Verwendungszweck, а Buchungstext — это тип операции («GUTSCHRIFT»). Взять не ту
# колонку = потерять номер счёта = развалить сверку. Такой перепутанный выбор уже
# случался, поэтому колонки перебираются по приоритету признака, а не слева направо.
_CSV_PURP = ("verwendungszweck", "vwz", "purpose", "reference", "beschreibung", "buchungstext")


def _pick(header, needles):
    """Индекс колонки по приоритету признаков: сначала первый needle по всем
    колонкам, потом второй и т.д."""
    low = [(h or "").strip().lower() for h in header]
    for n in needles:
        for i, hl in enumerate(low):
            if n in hl:
                return i
    return -1


def _pick_all(header, needles):
    """Все колонки, похожие на назначение платежа. Текст из них склеивается:
    чем больше контекста, тем надёжнее находится номер счёта."""
    low = [(h or "").strip().lower() for h in header]
    out = []
    for n in needles:
        for i, hl in enumerate(low):
            if n in hl and i not in out:
                out.append(i)
    return out


def import_bank_csv(conn, path, force=False):
    """Банковская выписка CSV (экспорт из онлайн-банка). Терпимо относится к
    кодировке и разделителю; колонки ищет по немецким/английским заголовкам.
    Если заголовки не опознаны — возвращает ошибку ЯВНО, а не молча ноль строк:
    молчаливый ноль — как раз то, из-за чего база «не обновлялась»."""
    sid, is_new = _register_source(conn, path, "bank")
    if not is_new and not force:
        return {"skipped": True, "reason": "файл не менялся", "path": os.path.basename(path)}
    raw = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        return {"error": "не удалось прочитать файл ни в одной кодировке",
                "path": os.path.basename(path)}
    delim = ";" if raw.count(";") >= raw.count(",") else ","
    reader = list(csv.reader(raw.splitlines(), delimiter=delim))
    # заголовок — первая строка, где нашлись и дата, и сумма
    hi, di, ai = -1, -1, -1
    for i, row in enumerate(reader[:15]):
        d, a = _pick(row, _CSV_DATE), _pick(row, _CSV_AMT)
        if d >= 0 and a >= 0:
            hi, di, ai = i, d, a
            break
    if hi < 0:
        return {"error": "не нашёл колонки даты и суммы — пришли файл как есть, добавлю формат",
                "path": os.path.basename(path),
                "header_seen": reader[0][:12] if reader else []}
    header = reader[hi]
    pi = _pick(header, _CSV_PARTY)
    uis = _pick_all(header, _CSV_PURP)
    items = []
    for row in reader[hi + 1:]:
        if len(row) <= max(di, ai):
            continue
        iso = to_iso(row[di])
        if not iso:
            continue
        parts = [row[pi]] if 0 <= pi < len(row) else []
        parts += [row[u] for u in uis if u < len(row)]
        party = " ".join(x.strip() for x in parts if x and x.strip())
        items.append({"date": iso, "amount": to_amount(row[ai]), "party": party, "category": ""})
    return _ingest_payments(conn, sid, items, os.path.basename(path))


def _ingest_payments(conn, sid, items, label):
    """Общий приём платежей: нормализация, дедуп, автокатегория."""
    new, dates = 0, []
    seen_same = {}
    for it in items:
        iso = to_iso(it.get("date"))
        amt = to_amount(it.get("amount"))
        if not iso or not amt:
            continue
        party = (it.get("party") or "").strip()
        k = (iso, round(amt, 2), norm_party(party))
        seen_same[k] = seen_same.get(k, 0) + 1
        key = _dedup_key(iso, amt, party, seen_same[k])
        cat = it.get("category") or guess_category(party, amt)
        cur = conn.execute(
            "INSERT OR IGNORE INTO fin_payment(val_date, amount, party, category, account,"
            " dedup_key, source_id) VALUES(?,?,?,?,?,?,?)",
            (iso, amt, party, cat, "bank", key, sid))
        new += cur.rowcount
        dates.append(iso)
    _finish_source(conn, sid, new, len(items), min(dates or [""]), max(dates or [""]))
    return {"skipped": False, "kind": "bank", "path": label, "new": new, "seen": len(items),
            "period": [min(dates or [""]), max(dates or [""])]}


_CLIENT_HINTS = ("rechnung", "rn.", "rnr", "re ", "kdn", "knr", "rg ", "invoice")


def guess_category(party, amount):
    """Грубая автокатегория для строк без категории. Осторожно: доходом считаем
    только то, где явно виден признак счёта — лучше недосчитать и показать
    «неразобранное», чем приписать выручку личному переводу."""
    p = (party or "").lower()
    if amount > 0:
        return "client_income" if any(h in p for h in _CLIENT_HINTS) else "other_income"
    return "other_expense"


def normalize_categories(conn):
    """Починка категорий, которые пришли из источника заведомо неверными.

    Главный случай: РАСХОД, помеченный как client_income. В выписке такие строки
    выглядят как «Maik Füller Gerüste für Cansativa Projekt» — упоминание проекта
    и слова Rechnung сбивало автокатегорию, хотя это выплата подрядчику, а не
    приход от клиента. На суммы дохода это не влияло (там фильтр amount>0), но
    ярлык мешал видеть важное: выплаты другим художникам — это вопрос
    Künstlersozialabgabe, и он должен быть виден Юристу отдельной строкой.

    Отрицательный client_income переводим в subcontractor_or_service. Возврат
    клиентского платежа (Rücklastschrift/Storno) оставляем как есть — он обязан
    уменьшать доход, поэтому распознаём его по ключевым словам."""
    reverse_words = ("rücklast", "ruecklast", "storno", "ruckbuch", "rückbuch", "retoure")
    moved = 0
    for r in conn.execute(
            "SELECT id, party FROM fin_payment WHERE amount<0 AND category='client_income'").fetchall():
        p = (r["party"] or "").lower()
        if any(w in p for w in reverse_words):
            continue
        conn.execute("UPDATE fin_payment SET category='subcontractor_or_service' WHERE id=?", (r["id"],))
        moved += 1
    return {"recategorized_negative_income": moved}


OVERRIDES_PATH = os.path.join(BASE_DIR, "finance_overrides.json")


def apply_overrides(conn, path=None):
    """Применить журнал ручных решений (finance_overrides.json).

    Зачем файл, а не правка прямо в базе: база собирается заново из источников,
    и любое решение, записанное только в неё, при следующей пересборке молча
    исчезнет. Здесь оно переживает всё и лежит в git — видно, кто, когда и почему.

    Решения человека имеют приоритет над автокатегоризацией, поэтому вызывается
    ПОСЛЕ normalize_categories()."""
    p = path or OVERRIDES_PATH
    out = {"cancelled": 0, "recategorized": 0, "not_found": []}
    if not os.path.exists(p):
        return out
    with open(p, "r", encoding="utf-8") as f:
        ov = json.load(f)

    for c in ov.get("cancelled_invoices", []):
        cur = conn.execute(
            "UPDATE fin_invoice SET cancelled=1, note=? WHERE number=? AND inv_date=?",
            (c.get("reason", "")[:400], c.get("number"), to_iso(c.get("date"))))
        if cur.rowcount:
            # снять привязки: аннулированный счёт не должен «съедать» платёж
            conn.execute("DELETE FROM fin_match WHERE invoice_id IN"
                         " (SELECT id FROM fin_invoice WHERE number=? AND inv_date=?)",
                         (c.get("number"), to_iso(c.get("date"))))
            out["cancelled"] += cur.rowcount
        else:
            out["not_found"].append("счёт %s от %s" % (c.get("number"), c.get("date")))

    for l in ov.get("manual_links", []):
        res = confirm_match(conn, l.get("invoice"), l.get("payment_date"),
                            l.get("payment_amount"), l.get("reason", "")[:300])
        if res.get("ok"):
            out["linked"] = out.get("linked", 0) + 1
        else:
            out["not_found"].append("связка %s ← %s: %s"
                                    % (l.get("invoice"), l.get("payment_date"), res.get("error")))

    for r in ov.get("payment_category", []):
        cur = conn.execute(
            "UPDATE fin_payment SET category=? WHERE val_date=? AND ABS(amount-?)<0.01"
            " AND lower(party) LIKE ?",
            (r.get("category"), to_iso(r.get("date")), float(r.get("amount")),
             "%" + (r.get("party_like") or "").lower() + "%"))
        if cur.rowcount:
            out["recategorized"] += cur.rowcount
        else:
            out["not_found"].append("платёж %s на %s" % (r.get("date"), r.get("amount")))
    return out


PERSONAL_HINTS = ("overchuk", "privat", "darlehen", "bürgergeld", "buergergeld")


def income_review(conn, floor=300.0):
    """Крупные приходы, лежащие в other_income, — кандидаты на «это на самом деле
    клиент». Именно так 3 000 € от Klügling Café выпали из выручки: банк пометил
    их как прочий доход, и они не попадали ни в один отчёт. Личные переводы
    (родственники, частные займы) отсеиваем по признакам."""
    rows = conn.execute(
        "SELECT * FROM fin_payment WHERE amount>=? AND category='other_income'"
        " ORDER BY val_date", (floor,)).fetchall()
    return [{"date": r["val_date"], "amount": round(r["amount"], 2), "party": r["party"]}
            for r in rows if not any(h in (r["party"] or "").lower() for h in PERSONAL_HINTS)]


def subcontractor_payments(conn, year=None):
    """Выплаты подрядчикам/другим художникам. Отдельная величина: от неё зависит
    Künstlersozialabgabe как Verwerter — вопрос к Юристу, но цифру даёт Финансист."""
    where = ["amount < 0", "category IN ('subcontractor_or_service','subcontractor_artists')"]
    args = []
    if year:
        where.append("substr(val_date,1,4)=?"); args.append(str(year))
    rows = conn.execute("SELECT * FROM fin_payment WHERE " + " AND ".join(where)
                        + " ORDER BY val_date", args).fetchall()
    return {"total": round(-sum(r["amount"] for r in rows), 2), "count": len(rows),
            "items": [{"date": r["val_date"], "amount": round(-r["amount"], 2),
                       "party": r["party"]} for r in rows]}


def import_inbox(conn, force=False):
    """Забрать всё, что лежит в finance_inbox/ — это прямой канал передачи данных
    (см. finance_inbox/README.md). Порядок: счета, потом банк."""
    out = []
    if not os.path.isdir(INBOX_DIR):
        return out
    files = sorted(os.listdir(INBOX_DIR))
    for fn in files:
        p = os.path.join(INBOX_DIR, fn)
        if not os.path.isfile(p):
            continue
        low = fn.lower()
        if low.startswith("invoices") and low.endswith(".json"):
            out.append(import_invoices(conn, p, force))
        elif low.startswith("bank") and low.endswith(".json"):
            out.append(import_bank_json(conn, p, force))
        elif low.startswith("bank") and low.endswith(".csv"):
            out.append(import_bank_csv(conn, p, force))
    return out


# ──────────────────────────────────── сверка ──────────────────────────────────

MATCH_WINDOW_DAYS = 180        # счёт может быть оплачен сильно позже


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _client_token(name):
    """Опорное слово клиента для нечёткого сравнения ('FSV Frankfurt' → 'fsv')."""
    t = norm_party(name).split(" ")
    return t[0] if t and len(t[0]) >= 3 else ""


def _link(conn, inv_id, pay_id, amount, method, conf):
    conn.execute("INSERT OR IGNORE INTO fin_match(invoice_id,payment_id,amount,method,confidence)"
                 " VALUES(?,?,?,?,?)", (inv_id, pay_id, round(amount, 2), method, conf))


def reconcile(conn):
    """Связать счета с платежами. Стратегии от сильной к слабой; каждая следующая
    работает только с тем, что осталось. Автоматически связываем ТОЛЬКО то, где
    арифметика сходится копейка в копейку, — всё спорное уходит в suggest_matches()
    на подтверждение человеком. Лучше показать «разобрать», чем тихо соврать.

      1) номер счёта в назначении + сумма совпала        → 1.0
      2) номер счёта в назначении + сумма меньше (аванс) → 0.9  (частичная оплата)
      3) точная сумма + клиент + окно дат                → 0.6
      4) один платёж = сумма нескольких счетов клиента   → 0.5  (напр. «RG: 6,7»)

    Существующие связи (в т.ч. ручные) не трогаем."""
    invs = [dict(r) for r in conn.execute(
        "SELECT * FROM fin_invoice WHERE cancelled=0 ORDER BY inv_date").fetchall()]
    pays = [dict(r) for r in conn.execute(
        "SELECT * FROM fin_payment WHERE amount>0 ORDER BY val_date").fetchall()]

    paid = {}          # invoice_id → уже привязано денег
    for r in conn.execute("SELECT invoice_id, SUM(amount) s FROM fin_match GROUP BY invoice_id"):
        paid[r["invoice_id"]] = r["s"]
    used = {}          # payment_id → уже распределено денег
    for r in conn.execute("SELECT payment_id, SUM(amount) s FROM fin_match GROUP BY payment_id"):
        used[r["payment_id"]] = r["s"]

    def rest_inv(i):
        return round(i["amount"] - paid.get(i["id"], 0.0), 2)

    def rest_pay(p):
        return round(p["amount"] - used.get(p["id"], 0.0), 2)

    def apply(inv, p, amount, method, conf):
        _link(conn, inv["id"], p["id"], amount, method, conf)
        paid[inv["id"]] = paid.get(inv["id"], 0.0) + amount
        used[p["id"]] = used.get(p["id"], 0.0) + amount

    made = {"number": 0, "partial": 0, "amount": 0, "sum": 0}

    def in_window(inv, p):
        return inv["inv_date"] <= p["val_date"] and _days(inv["inv_date"], p["val_date"]) <= MATCH_WINDOW_DAYS

    # 1–2) по номеру счёта в назначении платежа
    for p in pays:
        if rest_pay(p) <= 0.01:
            continue
        np = norm_number(p["party"])
        for inv in invs:
            if rest_inv(inv) <= 0.01:
                continue
            n = norm_number(inv["number"])
            if len(n) < 5 or n not in np:
                continue
            ri, rp = rest_inv(inv), rest_pay(p)
            if abs(ri - rp) < 0.01:
                apply(inv, p, rp, "number", 1.0); made["number"] += 1
                break
            if rp < ri:                      # аванс / частичная оплата
                apply(inv, p, rp, "number-partial", 0.9); made["partial"] += 1
                break
            # платёж больше счёта — спорно, отдаём человеку (см. suggest_matches)

    # 3) точная сумма + клиент + окно дат
    for p in pays:
        if rest_pay(p) <= 0.01:
            continue
        for inv in invs:
            if rest_inv(inv) <= 0.01 or abs(rest_inv(inv) - rest_pay(p)) > 0.01:
                continue
            if not in_window(inv, p):
                continue
            tok = _client_token(inv["client"])
            if tok and tok in norm_party(p["party"]):
                apply(inv, p, rest_pay(p), "amount+client", 0.6); made["amount"] += 1
                break

    # 4) один платёж закрывает несколько счетов одного клиента (частая практика:
    #    «RG: 6,7» — клиент платит одной суммой за два счёта сразу)
    for p in pays:
        rp = rest_pay(p)
        if rp <= 0.01:
            continue
        cand = [i for i in invs if rest_inv(i) > 0.01 and in_window(i, p)
                and _client_token(i["client"]) and _client_token(i["client"]) in norm_party(p["party"])]
        combo = _subset_summing(cand, rp, rest_inv)
        if combo:
            for inv in combo:
                apply(inv, p, rest_inv(inv), "sum-of-invoices", 0.5)
            made["sum"] += 1

    linked = {i["id"] for i in invs if paid.get(i["id"], 0) > 0.01}
    open_n = sum(1 for i in invs if rest_inv(i) > 0.01)
    return {"matched_by_number": made["number"], "matched_partial": made["partial"],
            "matched_by_amount": made["amount"], "matched_sum_of_invoices": made["sum"],
            "invoices": len(invs), "invoices_linked": len(linked), "invoices_open": open_n,
            "payments_in": len(pays),
            "payments_unlinked": sum(1 for p in pays if rest_pay(p) > 0.01)}


def _subset_summing(items, target, valfn, max_k=3):
    """Найти подмножество (2..max_k элементов), сумма которых == target.
    Возвращает ЕДИНСТВЕННОЕ решение; если вариантов несколько — None
    (неоднозначность разбирает человек, а не догадка машины)."""
    import itertools
    found = []
    n = min(len(items), 8)                      # защита от комбинаторного взрыва
    for k in range(2, max_k + 1):
        for combo in itertools.combinations(items[:n], k):
            if abs(sum(valfn(i) for i in combo) - target) < 0.01:
                found.append(combo)
                if len(found) > 1:
                    return None
    return list(found[0]) if len(found) == 1 else None


def suggest_matches(conn, limit=20):
    """Кандидаты на связку, которые автомат НЕ стал применять сам: платёж и счёт
    похожи, но арифметика или клиент не сходятся точно. Это рабочий список
    «подтверди/отклони» — здесь Финансист честно говорит «не уверен»."""
    op = {o["number"]: o for o in open_invoices(conn)}
    invs = {r["number"]: dict(r) for r in conn.execute(
        "SELECT * FROM fin_invoice WHERE cancelled=0").fetchall()}
    out = []
    for p in unmatched_income(conn):
        np_num, np_party = norm_number(p["party"]), norm_party(p["party"])
        cands = []
        for num, o in op.items():
            inv = invs.get(num, {})
            score, why = 0.0, []
            n = norm_number(num)
            if len(n) >= 5 and n in np_num:
                score += 0.6; why.append("номер счёта в назначении")
            if abs(o["open"] - p["amount"]) < 0.01:
                score += 0.5; why.append("сумма совпадает")
            tok = _client_token(inv.get("client", ""))
            if tok and tok in np_party:
                score += 0.3; why.append("клиент похож")
            if o["date"] <= p["val_date"] and _days(o["date"], p["val_date"]) <= MATCH_WINDOW_DAYS:
                score += 0.1
            if score >= 0.5:
                cands.append({"number": num, "date": o["date"], "client": inv.get("client", ""),
                              "open": o["open"], "score": round(score, 2), "why": ", ".join(why)})
        cands.sort(key=lambda c: -c["score"])
        out.append({"payment": {"date": p["val_date"], "amount": p["amount"], "party": p["party"]},
                    "candidates": cands[:3]})
        if len(out) >= limit:
            break
    return out


def confirm_match(conn, invoice_number, payment_date, payment_amount, note="ручное подтверждение"):
    """Ручная связка — единственный способ закрыть спорный случай. Пишет method='manual',
    чтобы в отчёте было видно, где решение принял человек."""
    inv = conn.execute("SELECT * FROM fin_invoice WHERE number=?", (invoice_number,)).fetchone()
    if not inv:
        return {"ok": False, "error": "счёт %s не найден" % invoice_number}
    pay = conn.execute("SELECT * FROM fin_payment WHERE val_date=? AND ABS(amount-?)<0.01",
                       (to_iso(payment_date), float(payment_amount))).fetchone()
    if not pay:
        return {"ok": False, "error": "платёж %s на %s не найден" % (payment_date, payment_amount)}
    amt = min(float(payment_amount), inv["amount"])
    _link(conn, inv["id"], pay["id"], amt, "manual", 1.0)
    return {"ok": True, "invoice": invoice_number, "payment": pay["val_date"], "amount": amt, "note": note}


# ─────────────────────────────────── запросы ──────────────────────────────────
# Всё, что ниже, — детерминированные ответы из базы. Бот и дашборды НЕ считают
# деньги сами; они зовут эти функции. Один источник правды — одна арифметика.

def coverage(conn):
    """До какой даты у нас есть выписки и счета. Это «граница знания»:
    за её пределами Финансист обязан отвечать «данных нет»."""
    p = conn.execute("SELECT MIN(val_date) a, MAX(val_date) b, COUNT(*) n FROM fin_payment").fetchone()
    i = conn.execute("SELECT MIN(inv_date) a, MAX(inv_date) b, COUNT(*) n FROM fin_invoice").fetchone()
    srcs = [dict(r) for r in conn.execute(
        "SELECT path, sha256, kind, imported_at, rows_new, rows_total, period_from, period_to"
        " FROM fin_source ORDER BY id").fetchall()]
    return {"bank_from": p["a"], "bank_to": p["b"], "payments": p["n"],
            "inv_from": i["a"], "inv_to": i["b"], "invoices": i["n"],
            "sources": srcs}


def assert_covered(conn, ym_or_date):
    """Вернуть None, если период покрыт выписками, иначе — текст предупреждения.
    Именно эта проверка не даёт выдать «ноль» за «не знаю»."""
    cov = coverage(conn)
    if not cov["bank_to"]:
        return "Банковских выписок в базе нет вообще — любые суммы прихода недостоверны."
    end = (ym_or_date or "")[:10]
    if len(end) == 7:
        end = end + "-31"
    if end > cov["bank_to"]:
        return ("Выписки есть только по %s. Период после этой даты НЕ покрыт — "
                "цифры за него неизвестны (не ноль, а неизвестно)." % cov["bank_to"])
    return None


def received(conn, year=None, month=None, business_only=True):
    """Сколько РЕАЛЬНО пришло денег (банк). Это и есть доход."""
    where = ["amount > 0"]
    args = []
    if business_only:
        where.append("category IN (%s)" % ",".join("?" * len(BUSINESS_INCOME_CATS)))
        args += list(BUSINESS_INCOME_CATS)
    if year:
        where.append("substr(val_date,1,4)=?"); args.append(str(year))
    if month:
        where.append("substr(val_date,1,7)=?"); args.append(month)
    r = conn.execute("SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM fin_payment"
                     " WHERE " + " AND ".join(where), args).fetchone()
    total, cnt = r["s"], r["n"]
    if business_only:                       # вычесть возвраты клиентам за тот же период
        w2, a2 = ["amount < 0", "category = ?"], [CLIENT_REFUND_CAT]
        if year:
            w2.append("substr(val_date,1,4)=?"); a2.append(str(year))
        if month:
            w2.append("substr(val_date,1,7)=?"); a2.append(month)
        rf = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM fin_payment"
                          " WHERE " + " AND ".join(w2), a2).fetchone()
        total += rf["s"]                    # сумма отрицательная — это вычитание
    return {"total": round(total, 2), "count": cnt}


def spent(conn, year=None, month=None):
    """Сколько ушло (расходы, положительным числом). Возвраты клиентам сюда НЕ
    входят — они уже вычтены из выручки в received()."""
    where = ["amount < 0", "category != '%s'" % CLIENT_REFUND_CAT]
    args = []
    if year:
        where.append("substr(val_date,1,4)=?"); args.append(str(year))
    if month:
        where.append("substr(val_date,1,7)=?"); args.append(month)
    r = conn.execute("SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM fin_payment"
                     " WHERE " + " AND ".join(where), args).fetchone()
    return {"total": round(-r["s"], 2), "count": r["n"]}


def invoiced(conn, year=None, month=None):
    """Сколько ВЫСТАВЛЕНО счетов (обязательства, не деньги)."""
    where = ["cancelled=0"]
    args = []
    if year:
        where.append("substr(inv_date,1,4)=?"); args.append(str(year))
    if month:
        where.append("substr(inv_date,1,7)=?"); args.append(month)
    r = conn.execute("SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM fin_invoice"
                     " WHERE " + " AND ".join(where), args).fetchone()
    return {"total": round(r["s"], 2), "count": r["n"]}


def monthly(conn, ym_from=None, ym_to=None):
    """Помесячно: выставлено / получено / потрачено. Основа графика в дашборде."""
    rows = {}
    for r in conn.execute("SELECT substr(inv_date,1,7) ym, SUM(amount) s FROM fin_invoice"
                          " WHERE cancelled=0 GROUP BY ym").fetchall():
        rows.setdefault(r["ym"], {})["invoiced"] = round(r["s"], 2)
    q = ("SELECT substr(val_date,1,7) ym,"
         " SUM(CASE WHEN amount>0 AND category IN (%s) THEN amount"
         "          WHEN amount<0 AND category='%s' THEN amount ELSE 0 END) inc,"
         " SUM(CASE WHEN amount<0 AND category!='%s' THEN -amount ELSE 0 END) exp"
         " FROM fin_payment GROUP BY ym"
         % (",".join("?" * len(BUSINESS_INCOME_CATS)), CLIENT_REFUND_CAT, CLIENT_REFUND_CAT))
    for r in conn.execute(q, list(BUSINESS_INCOME_CATS)).fetchall():
        d = rows.setdefault(r["ym"], {})
        d["received"] = round(r["inc"], 2)
        d["spent"] = round(r["exp"], 2)
    out = []
    for ym in sorted(rows):
        if ym_from and ym < ym_from:
            continue
        if ym_to and ym > ym_to:
            continue
        d = rows[ym]
        out.append({"ym": ym, "invoiced": d.get("invoiced", 0.0),
                    "received": d.get("received", 0.0), "spent": d.get("spent", 0.0)})
    return out


def open_invoices(conn, as_of=None):
    """Счета без (полной) оплаты — то, что реально висит на клиентах."""
    rows = conn.execute("""
        SELECT i.*, COALESCE(SUM(m.amount),0) paid
        FROM fin_invoice i LEFT JOIN fin_match m ON m.invoice_id=i.id
        WHERE i.cancelled=0 GROUP BY i.id ORDER BY i.inv_date""").fetchall()
    out = []
    for r in rows:
        rest = round(r["amount"] - r["paid"], 2)
        if rest > 0.01 and (not as_of or r["inv_date"] <= as_of):
            out.append({"number": r["number"], "date": r["inv_date"], "client": r["client"],
                        "amount": round(r["amount"], 2), "paid": round(r["paid"], 2),
                        "open": rest, "days": _days(r["inv_date"], as_of or str(date.today()))})
    return out


def unmatched_income(conn):
    """Приход, который не удалось привязать ни к одному счёту. Это рабочий
    список «разобрать», а не повод молча потерять деньги из отчёта."""
    rows = conn.execute("""
        SELECT p.* FROM fin_payment p
        LEFT JOIN fin_match m ON m.payment_id=p.id
        WHERE p.amount>0 AND m.id IS NULL AND p.category IN (%s)
        ORDER BY p.val_date""" % ",".join("?" * len(BUSINESS_INCOME_CATS)),
        list(BUSINESS_INCOME_CATS)).fetchall()
    return [dict(r) for r in rows]


def year_report(conn, year):
    """Точный годовой срез — то, что спрашивает Директор. Без домыслов:
    отдельно деньги (банк), отдельно счета, отдельно то, что не сошлось."""
    y = str(year)
    rec = received(conn, year=y)
    sp = spent(conn, year=y)
    inv = invoiced(conn, year=y)
    warn = assert_covered(conn, "%s-12" % y)
    op = [o for o in open_invoices(conn) if o["date"][:4] == y]
    v = conn.execute("SELECT COALESCE(SUM(vat),0) v, COUNT(*) n FROM fin_invoice"
                     " WHERE cancelled=0 AND COALESCE(vat,0)>0 AND substr(inv_date,1,4)=?",
                     (y,)).fetchone()
    return {"year": y,
            "vat_invoiced": round(v["v"], 2), "vat_invoices": v["n"],
            "received": rec["total"], "received_count": rec["count"],
            "invoiced": inv["total"], "invoiced_count": inv["count"],
            "spent": sp["total"],
            "net": round(rec["total"] - sp["total"], 2),
            "open_invoices": op, "open_total": round(sum(o["open"] for o in op), 2),
            "unmatched_income": len(unmatched_income(conn)),
            "coverage_warning": warn,
            "coverage": {k: v for k, v in coverage(conn).items() if k != "sources"}}


def planned_expenses(conn, months=1):
    """Плановые расходы на ближайшие N месяцев (регулярные платежи)."""
    rows = conn.execute("SELECT * FROM fin_expense_plan WHERE active=1").fetchall()
    total = 0.0
    items = []
    for r in rows:
        if r["recur"] == "monthly":
            amt = r["amount"] * months
        elif r["recur"] == "yearly":
            amt = r["amount"] * months / 12.0
        else:
            amt = r["amount"]
        total += amt
        items.append({"title": r["title"], "amount": round(amt, 2), "recur": r["recur"]})
    return {"months": months, "total": round(total, 2), "items": items}


def income_flow_for_dashboard():
    """Помесячный поток для графика «Поток дохода» в дашбордах.

    total = ДЕНЬГИ, ПРИШЕДШИЕ НА СЧЁТ. Раньше здесь стояла сумма выставленных
    счетов из invoice_archive (где paid по умолчанию =1), и график показывал
    оборот, которого на счету не было. Теперь источник — банковская выписка.

    Возвращает [] если базы Финансиста ещё нет: дашборд в этом случае честно
    покажет «нет данных», а не старую неправду."""
    try:
        with fdb_ro() as conn:
            cov = coverage(conn)
            rows = [{"ym": m["ym"], "total": m["received"], "invoiced": m["invoiced"]}
                    for m in monthly(conn)]
            return {"rows": rows, "covered_to": cov["bank_to"]}
    except Exception:
        return {"rows": [], "covered_to": None}


def context_block(conn, years=3):
    """Готовый текстовый срез для системного промпта Финансиста и для запросов
    от других агентов. Здесь уже посчитано ВСЁ, что обычно спрашивают, — модели
    не нужно (и нельзя) считать самой: её работа — объяснить, а не сложить.

    Первым абзацем идёт граница знания. Это не вежливость, а рабочее правило:
    именно её отсутствие раньше приводило к придуманным цифрам за свежие месяцы."""
    cov = coverage(conn)
    L = ["=== ФИНАНСОВЫЕ ДАННЫЕ (база Финансиста, единственный источник правды) ==="]
    L.append("Выписки покрывают: %s … %s (%d операций). Счета: %s … %s (%d шт.)."
             % (cov["bank_from"] or "—", cov["bank_to"] or "—", cov["payments"],
                cov["inv_from"] or "—", cov["inv_to"] or "—", cov["invoices"]))
    L.append("ГРАНИЦА ЗНАНИЯ: после %s банковских данных НЕТ. За этот период отвечай "
             "«данных нет», НИКОГДА не подставляй ноль и не считай по счетам."
             % (cov["bank_to"] or "—"))
    L.append("Доход = деньги на счету (fin_payment). Выставленный счёт доходом НЕ является.")
    L.append("")
    L.append("ПО ГОДАМ (выставлено / получено / расходы / нетто):")
    ys = [r["y"] for r in conn.execute(
        "SELECT DISTINCT substr(val_date,1,4) y FROM fin_payment ORDER BY y DESC")][:years]
    for y in sorted(ys):
        r = year_report(conn, y)
        L.append("  %s: выставлено %.2f € (%d сч.) | получено %.2f € (%d пост.) | "
                 "расходы %.2f € | нетто %.2f € | открыто по счетам %.2f €"
                 % (y, r["invoiced"], r["invoiced_count"], r["received"], r["received_count"],
                    r["spent"], r["net"], r["open_total"]))
    L.append("")
    L.append("ПОМЕСЯЧНО за последние 14 мес (месяц: выставлено / получено / расходы):")
    for m in monthly(conn)[-14:]:
        L.append("  %s: %.2f / %.2f / %.2f" % (m["ym"], m["invoiced"], m["received"], m["spent"]))
    op = open_invoices(conn)
    L.append("")
    L.append("НЕЗАКРЫТЫЕ СЧЕТА (%d шт., %.2f €):" % (len(op), sum(o["open"] for o in op)))
    for o in op:
        L.append("  %s №%s %s — %.2f € открыто (%d дн.)"
                 % (o["date"], o["number"], o["client"], o["open"], o["days"]))
    sug = suggest_matches(conn, limit=10)
    if sug:
        L.append("")
        L.append("ТРЕБУЕТ РЕШЕНИЯ ХОЗЯИНА — поступления без однозначного счёта (%d):" % len(sug))
        for s in sug:
            p = s["payment"]
            c = s["candidates"][0]["number"] if s["candidates"] else "—"
            L.append("  %s %.2f € «%s» → возможно счёт %s" % (p["date"], p["amount"], p["party"][:60], c))
    rev = income_review(conn)
    if rev:
        L.append("")
        L.append("ПРОЧИЙ ДОХОД НА ПРОВЕРКУ — крупные приходы вне выручки (%d):" % len(rev))
        for r in rev:
            L.append("  %s %.2f € «%s» — если это клиент, деньги сейчас НЕ в обороте"
                     % (r["date"], r["amount"], r["party"][:60]))
    pe = planned_expenses(conn, 1)
    if pe["items"]:
        L.append("")
        L.append("ПЛАНОВЫЕ РАСХОДЫ (в месяц): %.2f € — %s"
                 % (pe["total"], ", ".join("%s %.0f€" % (i["title"], i["amount"]) for i in pe["items"])))
    return "\n".join(L)


# ────────────────────────────────── bootstrap ─────────────────────────────────

def bootstrap(force=False, verbose=True):
    """Создать/обновить базу Финансиста из всех известных источников и свести.
    Безопасно вызывать сколько угодно раз: импорт идемпотентен по sha256."""
    report = {"imports": [], "reconcile": None}
    with fdb() as conn:
        ensure_schema(conn)
        for fn, fx in (("invoices_seed.json", import_invoices),
                       ("bank_seed.json", import_bank_json)):
            p = os.path.join(BASE_DIR, fn)
            if os.path.exists(p):
                report["imports"].append(fx(conn, p, force))
        report["imports"] += import_inbox(conn, force)
        report["normalize"] = normalize_categories(conn)
        report["overrides"] = apply_overrides(conn)   # решения человека — после автоматики
        report["reconcile"] = reconcile(conn)
        meta_set(conn, "last_bootstrap", datetime.now().isoformat(timespec="seconds"))
        report["coverage"] = {k: v for k, v in coverage(conn).items() if k != "sources"}
    if verbose:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


if __name__ == "__main__":
    import sys
    bootstrap(force="--force" in sys.argv)
