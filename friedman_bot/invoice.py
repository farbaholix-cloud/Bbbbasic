"""Генерация немецкого счёта (Rechnung) в PDF по вводным из бота.

Вызывается из bot.py::apply_actions и create_invoice_from_text:

    path, total, number = generate_invoice(
        recipient="Cosmopop GmbH\\nUnteres Rheinufer 39\\n67061 Ludwigshafen",
        items=[{"desc": "LFP26 Graffiti, Bühne 2 - Vorauszahlung", "price": 2000, "qty": 1}],
        salutation="Herr Thanabalasingam",   # опционально
        customer_no="",                       # опционально
        number="20260629-1",                  # из next_invoice_number()
    )

Рендер: HTML → PDF через Playwright (chromium уже стоит для дашбордов/сводок).

ВАЖНО (жёсткое правило проекта): IBAN, BIC, Steuernummer и персональный
Steuer-Identifikationsnummer НИКОГДА не хранятся в коде/git. Они читаются из
таблицы settings (ключи inv_iban / inv_bic / inv_steuernummer / inv_ident_nr).
Если не заданы — в PDF попадает плейсхолдер вида [IBAN], а не реальное значение.
Задать их владельцу можно командой секретарю /setinvoicedata (см. bot.py) либо
напрямую в settings.
"""

import os
import html
import tempfile
from datetime import datetime

# ── Немецкие месяцы для строки даты «29. Juni 2026» ───────────────────────────
_MONTHS_DE = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}

# ── Реквизиты отправителя ─────────────────────────────────────────────────────
# Неконфиденциальные брендовые поля имеют дефолты (бренд FARBAHOLIX). Их можно
# переопределить в settings. КОНФИДЕНЦИАЛЬНЫЕ (iban/bic/steuernummer/ident_nr)
# дефолта не имеют — только settings, иначе плейсхолдер.
_SENDER_DEFAULTS = {
    "name":   "Viacheslav Balabaiev",
    "title":  "Graffiti Künstler",
    "street": "Sigmund-Freud-Str. 76",
    "phone":  "+49 151 724 503 47",
    "email":  "farbaholix@gmail.com",
    "city":   "Frankfurt",           # город в строке «Ort, Datum»
    "bank":   "Nassauische Sparkasse",
}
# ключи в settings для секретных полей (плейсхолдер, если не заданы)
_SECRET_KEYS = {
    "iban":       ("inv_iban",       "[IBAN]"),
    "bic":        ("inv_bic",        "[BIC]"),
    "steuernummer": ("inv_steuernummer", "[Steuernummer]"),
    "ident_nr":   ("inv_ident_nr",   "[Steuer-Identifikationsnummer]"),
}


def _settings(key, default=None):
    """Достаём настройку из общей БД, не создавая жёсткой зависимости от bot."""
    try:
        from bot import _settings_get
        val = _settings_get(key)
        return val if val not in (None, "") else default
    except Exception:
        return default


def _sender():
    """Собираем реквизиты отправителя: settings поверх дефолтов; секреты — из settings."""
    s = {}
    for k, dflt in _SENDER_DEFAULTS.items():
        s[k] = _settings(f"inv_{k}", dflt)
    for k, (skey, placeholder) in _SECRET_KEYS.items():
        s[k] = _settings(skey, placeholder)
    return s


def _eur(n):
    """2000 → «2.000,00» (немецкий формат: точка-разделитель тысяч, запятая-дробь)."""
    s = f"{float(n):,.2f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _de_date(dt):
    return f"{dt.day}. {_MONTHS_DE[dt.month]} {dt.year}"


def _esc(t):
    return html.escape(str(t or ""))


def _addr_html(block):
    """Многострочный адрес (\\n) → HTML с <br>, экранируя каждую строку."""
    lines = [ln for ln in str(block or "").replace("\r", "").split("\n")]
    return "<br>".join(_esc(ln) if ln.strip() else "&nbsp;" for ln in lines)


def _build_html(recipient, items, number, salutation, customer_no,
                intro, dt, vat_rate):
    snd = _sender()

    # ── позиции таблицы ──
    rows = []
    subtotal = 0.0
    for i, it in enumerate(items, 1):
        qty = it.get("qty", 1) or 1
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            qty = 1
        price = float(it.get("price", 0) or 0)
        amount = qty * price
        subtotal += amount
        rows.append(
            f"<tr>"
            f"<td class=c>{i}</td>"
            f"<td class=c>{qty}</td>"
            f"<td>{_esc(it.get('desc', ''))}</td>"
            f"<td class=r>{_eur(price)}</td>"
            f"<td class=r>{_eur(amount)}</td>"
            f"</tr>"
        )
    table_rows = "\n".join(rows)

    # ── НДС / Kleinunternehmer ──
    if vat_rate:
        vat = subtotal * float(vat_rate) / 100.0
        total = subtotal + vat
        tax_block = (
            f"<table class='sum'>"
            f"<tr><td>Zwischensumme (netto)</td><td class=r>{_eur(subtotal)} €</td></tr>"
            f"<tr><td>zzgl. {_eur(vat_rate)} % USt.</td><td class=r>{_eur(vat)} €</td></tr>"
            f"<tr class=grand><td>Gesamtbetrag</td><td class=r>{_eur(total)} €</td></tr>"
            f"</table>"
        )
    else:
        total = subtotal
        tax_block = (
            "<p class='klein'>Als Kleinunternehmer im Sinne von § 19 Abs. 1 UStG "
            "wird die Umsatzsteuer nicht berechnet.</p>"
        )

    # ── обращение (опционально) ──
    greeting = ""
    if salutation and str(salutation).strip():
        greeting = f"<p class='greet'>Sehr geehrte/r {_esc(salutation)},</p>"

    kunde = (f"<div class='knr'>Kundennummer: {_esc(customer_no)}</div>"
             if customer_no and str(customer_no).strip() else "")

    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{
  font-family: 'Helvetica Neue', Arial, 'Segoe UI', sans-serif;
  color: #1a1a1a; margin: 0;
  padding: 60px 62px 48px 62px;
  font-size: 14px; line-height: 1.5;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}
.head {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.name {{ font-size: 30px; font-weight: 700; letter-spacing: .3px; }}
.title {{ color: #b23a3a; font-size: 15px; margin-top: 3px; }}
.meta {{ background: #efefef; padding: 14px 18px; text-align: right;
  font-size: 12px; line-height: 1.75; color: #333; max-width: 46%; }}
.meta a, .meta .mail {{ color: #b23a3a; text-decoration: none; }}
.recip {{ margin-top: 78px; font-size: 15px; line-height: 1.55; }}
.date {{ text-align: right; color: #8a8a8a; font-size: 13px; margin-top: 34px; }}
h1 {{ font-size: 20px; font-weight: 700; margin: 12px 0 0; }}
.rnr {{ font-size: 14px; margin-top: 10px; }}
.knr {{ font-size: 13px; color: #555; margin-top: 3px; }}
.greet {{ margin-top: 26px; }}
.intro {{ margin-top: 22px; }}
table.pos {{ width: 100%; border-collapse: collapse; margin-top: 22px; font-size: 13.5px; }}
table.pos th {{ border: 1px solid #222; padding: 7px 9px; text-align: left; font-weight: 700; }}
table.pos td {{ border: 1px solid #222; padding: 7px 9px; }}
table.pos td.c {{ text-align: left; width: 42px; }}
table.pos td.r, table.pos th.r {{ text-align: right; white-space: nowrap; }}
.klein {{ font-size: 12.5px; margin-top: 7px; }}
table.sum {{ margin-top: 12px; margin-left: auto; border-collapse: collapse; font-size: 13.5px; }}
table.sum td {{ padding: 4px 10px; }}
table.sum td.r {{ text-align: right; white-space: nowrap; }}
table.sum tr.grand td {{ border-top: 1.5px solid #222; font-weight: 700; padding-top: 7px; }}
.pay {{ margin-top: 30px; line-height: 1.55; }}
.pay .bank {{ margin-top: 8px; }}
.pay .bank .b {{ font-weight: 700; }}
.close {{ margin-top: 30px; line-height: 1.7; }}
</style></head><body>
  <div class='head'>
    <div>
      <div class='name'>{_esc(snd['name'])}</div>
      <div class='title'>{_esc(snd['title'])}</div>
    </div>
    <div class='meta'>
      {_esc(snd['street'])}<br>
      {_esc(snd['phone'])}<br>
      <span class='mail'>{_esc(snd['email'])}</span><br>
      Pers. Identifikationsnummer: {_esc(snd['ident_nr'])}<br>
      Steuernummer: {_esc(snd['steuernummer'])}
    </div>
  </div>

  <div class='recip'>{_addr_html(recipient)}</div>

  <div class='date'>{_esc(snd['city'])}, {_de_date(dt)}</div>

  <h1>Rechnung</h1>
  <div class='rnr'>Rechnungsnummer.: {_esc(number)}</div>
  {kunde}

  {greeting}
  <p class='intro'>{_esc(intro)}</p>

  <table class='pos'>
    <tr>
      <th>Pos</th><th>Anzahl</th><th>Bezeichnung</th>
      <th class='r'>Einzelpreis (€)</th><th class='r'>Betrag (€)</th>
    </tr>
    {table_rows}
  </table>
  {tax_block}

  <div class='pay'>
    Bitte überweisen Sie den Rechnungsbetrag auf folgende Bankverbindung:
    <div class='bank'>
      Empfänger: {_esc(snd['name'])}<br>
      <span class='b'>{_esc(snd['bank'])}</span><br>
      IBAN: {_esc(snd['iban'])}<br>
      BIC: {_esc(snd['bic'])}
    </div>
  </div>

  <div class='close'>
    Vielen Dank für Ihren Auftrag!<br><br>
    Mit freundlichen Grüßen<br>
    {_esc(snd['name'])}
  </div>
</body></html>""", total


def generate_invoice(recipient, items, salutation=None, customer_no="",
                     number=None, intro=None, when=None, vat_rate=None):
    """Собирает PDF немецкого счёта и возвращает (path, total, number).

    recipient  — получатель: название и адрес, каждая часть с новой строки (\\n).
    items      — [{"desc": str, "price": число, "qty": int=1}, ...].
    salutation — «Herr Schmidt» / «Frau Müller» (опц.; иначе без обращения).
    customer_no— номер клиента (опц.).
    number     — номер счёта (из next_invoice_number()).
    intro      — вводная строка перед таблицей (опц.; иначе стандартная).
    when       — datetime счёта (опц.; иначе сейчас).
    vat_rate   — если задан (напр. 19) — показывается НДС-разбивка; иначе
                 ставится оговорка Kleinunternehmer §19 UStG.
    """
    if not items:
        raise ValueError("нет позиций для счёта")
    dt = when or datetime.now()
    number = number or dt.strftime("%d%m%y")
    if not intro:
        intro = ("Hiermit berechne ich Ihnen wie vorab besprochen für die "
                 "erbrachten Leistungen folgende Positionen:")

    html_text, total = _build_html(
        recipient=recipient, items=items, number=number,
        salutation=salutation, customer_no=customer_no,
        intro=intro, dt=dt, vat_rate=vat_rate,
    )

    safe = "".join(c for c in str(number) if c.isalnum() or c in "-_")
    out_path = os.path.join(tempfile.gettempdir(), f"Rechnung_{safe or 'neu'}.pdf")

    _render_pdf(html_text, out_path)
    return out_path, total, number


def _build_contract_html(client, title, intro, sections, place, dt, sign_names):
    """HTML договора в дизайне инвойса: шапка FARBAHOLIX + красный акцент,
    стороны, нумерованные § с заголовком и текстом, блок подписей."""
    snd = _sender()
    sec_html = []
    for i, s in enumerate(sections, 1):
        heading = _esc(s.get("heading", ""))
        body = _esc(s.get("body", "")).replace("\n", "<br>")
        sec_html.append(
            f"<div class='sec'><div class='sh'>§ {i} {heading}</div>"
            f"<div class='sb'>{body}</div></div>")
    an = _esc(sign_names.get("auftragnehmer") or snd["name"])
    ag = _esc(sign_names.get("auftraggeber") or (client.split("\n")[0] if client else "Auftraggeber"))
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Helvetica Neue', Arial, 'Segoe UI', sans-serif; color:#1a1a1a;
  margin:0; padding:56px 62px 46px; font-size:13px; line-height:1.5;
  -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.head {{ display:flex; justify-content:space-between; align-items:flex-start; }}
.name {{ font-size:28px; font-weight:700; letter-spacing:.3px; }}
.title2 {{ color:#b23a3a; font-size:14px; margin-top:3px; }}
.meta {{ background:#efefef; padding:12px 16px; text-align:right; font-size:11.5px;
  line-height:1.7; color:#333; max-width:46%; }}
.meta .mail {{ color:#b23a3a; }}
.accent {{ border-bottom:4px solid #b23a3a; margin:14px 0 0; }}
h1 {{ font-size:20px; font-weight:700; margin:22px 0 4px; text-transform:uppercase; letter-spacing:.5px; }}
.parties {{ margin-top:10px; font-size:13px; line-height:1.6; }}
.parties b {{ font-weight:700; }}
.intro {{ margin-top:14px; }}
.sec {{ margin-top:14px; }}
.sec .sh {{ font-weight:700; font-size:13.5px; margin-bottom:3px; }}
.sec .sb {{ text-align:justify; }}
.signs {{ display:flex; justify-content:space-between; margin-top:48px; gap:40px; }}
.sig {{ flex:1; }}
.sig .line {{ border-top:1px solid #333; margin-top:34px; padding-top:5px; font-size:11.5px; color:#333; }}
.place {{ margin-top:30px; color:#555; }}
</style></head><body>
  <div class='head'>
    <div><div class='name'>{_esc(snd['name'])}</div><div class='title2'>{_esc(snd['title'])}</div></div>
    <div class='meta'>{_esc(snd['street'])}<br>{_esc(snd['phone'])}<br>
      <span class='mail'>{_esc(snd['email'])}</span><br>
      Steuernummer: {_esc(snd['steuernummer'])}</div>
  </div>
  <div class='accent'></div>
  <h1>{_esc(title)}</h1>
  <div class='parties'>
    <b>zwischen</b><br>{_addr_html(snd['name'] + chr(10) + snd['street'])} — nachfolgend „Auftragnehmer“<br><br>
    <b>und</b><br>{_addr_html(client)} — nachfolgend „Auftraggeber“
  </div>
  <p class='intro'>{_esc(intro)}</p>
  {''.join(sec_html)}
  <div class='place'>{_esc(place or snd['city'])}, den {_de_date(dt)}</div>
  <div class='signs'>
    <div class='sig'><div class='line'>Auftragnehmer — {an}</div></div>
    <div class='sig'><div class='line'>Auftraggeber — {ag}</div></div>
  </div>
</body></html>"""


def generate_contract(client, title=None, intro=None, sections=None,
                      place=None, when=None, sign_names=None, ref=None):
    """Собирает PDF договора в дизайне инвойса. Возвращает (path, ref).

    client     — заказчик: название и адрес, каждая часть с новой строки (\\n).
    title      — заголовок (напр. «Werkvertrag / Künstlervertrag»).
    intro      — вводная фраза (Präambel).
    sections   — [{"heading": "Vertragsgegenstand", "body": "..."}, ...] на немецком.
    place/when — место и дата подписания.
    sign_names — {"auftragnehmer": "...", "auftraggeber": "..."} (опц.).
    ref        — номер/идентификатор договора для имени файла.
    """
    if not sections:
        raise ValueError("нет разделов договора")
    dt = when or datetime.now()
    title = title or "Werkvertrag"
    if not intro:
        intro = "Die Parteien schließen den folgenden Vertrag über die nachstehend beschriebene Leistung:"
    html_text = _build_contract_html(
        client=client or "", title=title, intro=intro, sections=sections,
        place=place, dt=dt, sign_names=sign_names or {})
    ref = ref or dt.strftime("%d%m%y")
    safe = "".join(c for c in str(ref) if c.isalnum() or c in "-_")
    out_path = os.path.join(tempfile.gettempdir(), f"Vertrag_{safe or 'neu'}.pdf")
    _render_pdf(html_text, out_path)
    return out_path, ref


def _render_pdf(html_text: str, out_path: str):
    """HTML → PDF через синхронный Playwright.

    ВАЖНО: sync Playwright нельзя вызывать из потока, где крутится asyncio-loop
    (боты — async), иначе «Sync API inside the asyncio loop». Поэтому весь рендер
    выполняем в ОТДЕЛЬНОМ потоке — там запущенного event loop нет, sync API работает.
    """
    import threading

    box = {}

    def _work():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox",
                                                    "--force-color-profile=srgb"])
                page = browser.new_page()
                page.set_content(html_text, wait_until="networkidle")
                page.wait_for_timeout(150)
                page.pdf(path=out_path, format="A4", print_background=True,
                         margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
                browser.close()
        except Exception as e:  # пробрасываем в вызывающий поток
            box["err"] = e

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=120)
    if t.is_alive():
        raise TimeoutError("рендер PDF не уложился в 120с")
    if "err" in box:
        raise box["err"]


if __name__ == "__main__":
    # Локальная проверка макета по образцу (IMG_0444): секреты будут плейсхолдерами.
    p, t, n = generate_invoice(
        recipient="Cosmopop GmbH\nVithursan Thanabalasingam\nUnteres Rheinufer 39\n\n67061 Ludwigshafen",
        items=[{"desc": "LFP26 Graffiti, Bühne 2 - Vorauszahlung", "price": 2000, "qty": 1}],
        intro=("Hiermit berechne ich Ihnen wie vorab besprochen für die Gestaltung "
               "des Hintergrunds der Bühne 2 auf dem Love Family Park 2026 folgende Vorauszahlung:"),
        number="20260629-1",
        when=datetime(2026, 6, 29),
    )
    print(f"OK → {p}  total={t:.2f}€  Nr={n}")
