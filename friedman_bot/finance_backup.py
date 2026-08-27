"""
Бэкап базы Финансиста в виде ЧИТАЕМОГО Markdown + шифрование.

Зачем именно Markdown, а не копия .db:
  .db — чёрный ящик: чтобы проверить, что в нём правда, нужен sqlite. MD-выгрузку
  можно открыть на телефоне, глазами сверить с выпиской и увидеть, что данные
  живые. Это и есть защита от «агент думает, что база есть, а её нет».

Шифрование: scrypt(пароль) → Fernet (AES-128-CBC + HMAC). Файл остаётся текстовым:
шапка открытым текстом (что это, когда, чем расшифровать) + тело в base64.

Использование:
    python3 finance_backup.py --out ~/FARBAHOLIX/backup        # .md + .md.enc
    python3 finance_backup.py --out DIR --plain-off            # только шифрованный
    python3 finance_backup.py --decrypt FILE.md.enc            # обратно в .md
Пароль берётся из переменной окружения FIN_BACKUP_PASS, иначе спрашивается.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import sys
from datetime import date, datetime

import finance_core as fc

MAGIC = "FARBAHOLIX-FIN-BACKUP-v1"


# ──────────────────────────────── выгрузка в MD ───────────────────────────────

def _eur(x):
    return "{:,.2f} €".format(x or 0).replace(",", " ")


def render_markdown(conn):
    """Полный человекочитаемый срез базы. Порядок разделов — от выводов к сырью,
    чтобы файл был полезен и как отчёт, и как бэкап."""
    cov = fc.coverage(conn)
    today = date.today().isoformat()
    L = []
    A = L.append

    A("# Финансы FARBAHOLIX — срез базы Финансиста")
    A("")
    A("- Сформировано: **%s**" % datetime.now().strftime("%d.%m.%Y %H:%M"))
    A("- Банковские выписки покрывают: **%s … %s** (%d операций)"
      % (cov["bank_from"] or "—", cov["bank_to"] or "—", cov["payments"]))
    A("- Счета в базе: **%s … %s** (%d шт.)"
      % (cov["inv_from"] or "—", cov["inv_to"] or "—", cov["invoices"]))
    A("")
    A("> Доход = деньги, пришедшие на счёт (выписка). Выставленный счёт доходом НЕ считается.")
    A("> За пределами периода выписок данных нет — там «неизвестно», а не «ноль».")
    A("")

    # ── по годам ──
    A("## Итоги по годам")
    A("")
    A("| Год | Выставлено | Получено на счёт | Расходы | Нетто | Открыто по счетам |")
    A("|---|---:|---:|---:|---:|---:|")
    years = [r["y"] for r in conn.execute(
        "SELECT DISTINCT substr(val_date,1,4) y FROM fin_payment ORDER BY y")]
    for y in years:
        rep = fc.year_report(conn, y)
        A("| %s | %s | %s | %s | %s | %s |" % (
            y, _eur(rep["invoiced"]), _eur(rep["received"]), _eur(rep["spent"]),
            _eur(rep["net"]), _eur(rep["open_total"])))
    A("")

    # ── помесячно ──
    A("## Помесячно")
    A("")
    A("| Месяц | Выставлено счетов | Пришло на счёт | Расходы |")
    A("|---|---:|---:|---:|")
    for m in fc.monthly(conn):
        A("| %s | %s | %s | %s |" % (m["ym"], _eur(m["invoiced"]), _eur(m["received"]), _eur(m["spent"])))
    A("")

    # ── открытые счета ──
    op = fc.open_invoices(conn)
    A("## Незакрытые счета — %d шт. на %s" % (len(op), _eur(sum(o["open"] for o in op))))
    A("")
    if op:
        A("| Дата | Номер | Клиент | Сумма | Оплачено | Открыто | Дней |")
        A("|---|---|---|---:|---:|---:|---:|")
        for o in op:
            A("| %s | %s | %s | %s | %s | %s | %d |" % (
                o["date"], o["number"], o["client"], _eur(o["amount"]),
                _eur(o["paid"]), _eur(o["open"]), o["days"]))
    else:
        A("_Все счета закрыты._")
    A("")

    # ── требует решения ──
    sug = fc.suggest_matches(conn)
    A("## Требует твоего решения — %d поступлений без счёта" % len(sug))
    A("")
    if sug:
        A("Автомат не связал их сам: сумма или клиент сходятся не однозначно.")
        A("")
        for s in sug:
            p = s["payment"]
            A("- **%s · %s** — `%s`" % (p["date"], _eur(p["amount"]), p["party"]))
            for c in s["candidates"]:
                A("  - кандидат: счёт **%s** от %s (%s, открыто %s) — %s"
                  % (c["number"], c["date"], c["client"], _eur(c["open"]), c["why"]))
            if not s["candidates"]:
                A("  - кандидатов нет — возможно, это не оплата счёта")
    else:
        A("_Всё разнесено._")
    A("")

    # ── все счета ──
    A("## Все счета")
    A("")
    A("| Дата | Номер | Клиент | Сумма | Статус |")
    A("|---|---|---|---:|---|")
    rows = conn.execute("""
        SELECT i.*, COALESCE(SUM(m.amount),0) paid FROM fin_invoice i
        LEFT JOIN fin_match m ON m.invoice_id=i.id
        GROUP BY i.id ORDER BY i.inv_date""").fetchall()
    for r in rows:
        rest = r["amount"] - r["paid"]
        st = "оплачен" if rest < 0.01 else ("частично (%s)" % _eur(r["paid"]) if r["paid"] > 0.01 else "открыт")
        if r["cancelled"]:
            st = "аннулирован"
        A("| %s | %s | %s | %s | %s |" % (r["inv_date"], r["number"], r["client"], _eur(r["amount"]), st))
    A("")

    # ── деловые поступления ──
    A("## Деловые поступления (выписка)")
    A("")
    A("| Дата | Сумма | Контрагент / назначение |")
    A("|---|---:|---|")
    for r in conn.execute("SELECT * FROM fin_payment WHERE amount>0 AND category='client_income'"
                          " ORDER BY val_date"):
        A("| %s | %s | %s |" % (r["val_date"], _eur(r["amount"]), (r["party"] or "").replace("|", "/")))
    A("")

    # ── источники ──
    A("## Источники данных (что именно импортировано)")
    A("")
    A("| Файл | Тип | Импортирован | Строк новых / всего | Период | sha256 |")
    A("|---|---|---|---:|---|---|")
    for s in cov["sources"]:
        A("| %s | %s | %s | %d / %d | %s … %s | `%s` |" % (
            s["path"], s["kind"], (s["imported_at"] or "")[:16], s["rows_new"], s["rows_total"],
            s["period_from"] or "—", s["period_to"] or "—", (s["sha256"] or "")[:12]))
    A("")
    A("---")
    A("_Файл сгенерирован автоматически модулем `finance_backup.py`. "
      "Правки вносить в базу через Финансиста, а не в этот файл._")
    return "\n".join(L)


# ─────────────────────────────────── крипто ───────────────────────────────────

# Только стандартная библиотека — принципиально. Бэкап обязан расшифровываться
# на любой машине с голым python3, без pip install: внешняя зависимость, которой
# в нужный момент не окажется, превращает архив в кирпич.
#
# Схема: scrypt(пароль, salt) → 64 байта → ключ шифрования + ключ подписи.
# Гамма — HMAC-SHA256(k_enc, nonce||счётчик) в режиме счётчика, текст XOR-ится с ней.
# Затем encrypt-then-MAC: подпись HMAC-SHA256(k_mac, nonce||шифротекст) — она ловит
# и подмену файла, и неверный пароль (расшифровка мусора не пройдёт проверку).

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def _keys_from_pass(password, salt):
    raw = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                         n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=64)
    return raw[:32], raw[32:]


def _keystream(k_enc, nonce, nbytes):
    out = bytearray()
    ctr = 0
    while len(out) < nbytes:
        out += hmac.new(k_enc, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:nbytes])


def encrypt_text(text, password):
    salt, nonce = os.urandom(16), os.urandom(16)
    k_enc, k_mac = _keys_from_pass(password, salt)
    data = text.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(k_enc, nonce, len(data))))
    tag = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()
    body = base64.b64encode(ct).decode()
    head = ("%s\nsalt: %s\nnonce: %s\ntag: %s\nkdf: scrypt n=%d r=%d p=%d\n"
            "created: %s\nhint: расшифровать — python3 finance_backup.py --decrypt <файл>\n---\n"
            % (MAGIC, base64.b64encode(salt).decode(), base64.b64encode(nonce).decode(),
               base64.b64encode(tag).decode(), SCRYPT_N, SCRYPT_R, SCRYPT_P,
               datetime.now().isoformat(timespec="seconds")))
    return head + "\n".join(body[i:i + 76] for i in range(0, len(body), 76)) + "\n"


def decrypt_text(blob, password):
    lines = blob.splitlines()
    if not lines or lines[0].strip() != MAGIC:
        raise ValueError("не похоже на бэкап Финансиста (нет заголовка %s)" % MAGIC)
    hdr, body_at = {}, None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            body_at = i + 1
            break
        if ":" in ln:
            k, v = ln.split(":", 1)
            hdr[k.strip()] = v.strip()
    if body_at is None or not {"salt", "nonce", "tag"} <= set(hdr):
        raise ValueError("повреждён заголовок бэкапа")
    salt = base64.b64decode(hdr["salt"])
    nonce = base64.b64decode(hdr["nonce"])
    tag = base64.b64decode(hdr["tag"])
    ct = base64.b64decode("".join(lines[body_at:]))
    k_enc, k_mac = _keys_from_pass(password, salt)
    if not hmac.compare_digest(tag, hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("неверный пароль или файл повреждён/изменён")
    return bytes(a ^ b for a, b in zip(ct, _keystream(k_enc, nonce, len(ct)))).decode("utf-8")


def _password(confirm=False):
    p = os.environ.get("FIN_BACKUP_PASS")
    if p:
        return p
    p = getpass.getpass("Пароль для бэкапа: ")
    if confirm and p != getpass.getpass("Повтори пароль: "):
        sys.exit("Пароли не совпали.")
    return p


# ──────────────────────────────────── CLI ─────────────────────────────────────

def make_backup(out_dir, plain=True, encrypted=True, password=None):
    """Собрать MD и положить в out_dir. Возвращает список созданных файлов."""
    os.makedirs(out_dir, exist_ok=True)
    with fc.fdb_ro() as conn:
        md = render_markdown(conn)
    stamp = date.today().isoformat()
    made = []
    if plain:
        p = os.path.join(out_dir, "finance_%s.md" % stamp)
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)
        made.append(p)
    if encrypted:
        pw = password or _password(confirm=True)
        p = os.path.join(out_dir, "finance_%s.md.enc" % stamp)
        with open(p, "w", encoding="utf-8") as f:
            f.write(encrypt_text(md, pw))
        made.append(p)
    # «последний» — стабильное имя, чтобы синхронизация не плодила мусор
    if made:
        latest = os.path.join(out_dir, "finance_latest" + (".md.enc" if encrypted else ".md"))
        with open(made[-1], "r", encoding="utf-8") as src, open(latest, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        made.append(latest)
    return made


def main():
    ap = argparse.ArgumentParser(description="Бэкап финансовой базы в шифрованный Markdown")
    ap.add_argument("--out", default=os.path.expanduser("~/FARBAHOLIX/backup"))
    ap.add_argument("--plain-off", action="store_true", help="не сохранять незашифрованный .md")
    ap.add_argument("--no-encrypt", action="store_true", help="только .md, без шифрования")
    ap.add_argument("--decrypt", metavar="FILE", help="расшифровать бэкап обратно в .md")
    ap.add_argument("--stdout", action="store_true", help="просто напечатать MD")
    a = ap.parse_args()

    if a.decrypt:
        with open(a.decrypt, "r", encoding="utf-8") as f:
            blob = f.read()
        out = decrypt_text(blob, _password())
        dst = a.decrypt[:-4] if a.decrypt.endswith(".enc") else a.decrypt + ".md"
        with open(dst, "w", encoding="utf-8") as f:
            f.write(out)
        print("расшифровано → %s" % dst)
        return

    if a.stdout:
        with fc.fdb_ro() as conn:
            print(render_markdown(conn))
        return

    made = make_backup(a.out, plain=not a.plain_off, encrypted=not a.no_encrypt)
    for p in made:
        print("сохранено → %s (%d КБ)" % (p, os.path.getsize(p) // 1024))


if __name__ == "__main__":
    main()
