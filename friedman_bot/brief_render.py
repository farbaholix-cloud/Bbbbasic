"""Рендер утренней сводки в одностраничный JPEG (iOS 26 стиль), точно под iPhone.

Использует Playwright (headless Chromium). На сервере один раз:
    pip install playwright && playwright install chromium
    apt install -y fonts-noto-color-emoji fonts-dejavu   # эмодзи + кириллица
Если что-то из этого недоступно — бот сам откатится на текстовую сводку.
"""

import os
import html as _html

# Размер ровно под iPhone 14 (390x844 pt @3x = 1170x2532 px). Меняется при другой модели.
IPHONE_W = 390
IPHONE_H = 844
SCALE = 3

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:390px;height:844px;overflow:hidden}
body{font-family:-apple-system,'Inter','Helvetica Neue','Noto Sans',sans-serif;color:#f4f6fb;position:relative;
  background:#0a0b14}
.bg{position:absolute;inset:0;z-index:0;
  background:
   radial-gradient(46% 30% at 16% 6%, rgba(91,157,255,.62), transparent 60%),
   radial-gradient(44% 28% at 88% 4%, rgba(177,139,255,.56), transparent 60%),
   radial-gradient(54% 32% at 92% 70%, rgba(65,227,212,.42), transparent 62%),
   radial-gradient(56% 34% at 6% 88%, rgba(255,122,192,.42), transparent 60%),
   radial-gradient(50% 28% at 50% 44%, rgba(255,198,87,.16), transparent 60%),
   linear-gradient(165deg,#0e1126,#0a0b14 65%)}
.wrap{position:absolute;inset:0;z-index:1;padding:46px 18px 22px;display:flex;flex-direction:column;gap:11px}
.glass{background:rgba(255,255,255,.08);backdrop-filter:blur(26px) saturate(180%);
  border:1px solid rgba(255,255,255,.2);border-radius:22px;box-shadow:0 8px 26px rgba(0,0,0,.3),inset 0 1px 0 rgba(255,255,255,.32)}
.head{display:flex;align-items:center;gap:12px}
.anchor{width:48px;height:48px;border-radius:15px;flex-shrink:0;
  background:linear-gradient(135deg,rgba(91,157,255,.95),rgba(177,139,255,.95));
  display:flex;align-items:center;justify-content:center;font-size:25px;
  box-shadow:0 8px 20px rgba(91,157,255,.45),inset 0 1px 0 rgba(255,255,255,.5)}
.head .greet{font-size:21px;font-weight:800;letter-spacing:-.4px}
.head .date{font-size:12.5px;color:rgba(235,240,250,.6);margin-top:2px;font-weight:500}
.wisdom{padding:12px 15px;border-radius:16px;font-style:italic;font-size:13px;font-weight:500;color:#fbeec6;line-height:1.42;
  display:flex;gap:8px}
.wisdom .q{font-size:22px;line-height:.7;color:#ffc657;font-style:normal}
.card{padding:13px 15px}
.card .h{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;color:rgba(235,240,250,.6);margin-bottom:9px;display:flex;align-items:center;gap:7px}
.li{font-size:14px;font-weight:600;line-height:1.55;color:#eef0f4}
.li .t{color:#86b8ff;font-weight:800;font-size:12.5px}
.row{display:flex;gap:11px}
.row>.card{flex:1}
.spend .big{font-size:26px;font-weight:900;letter-spacing:-.8px;color:#ff9aa6;margin-bottom:6px}
.spend .it{font-size:12.5px;font-weight:600;color:#dbe2ec;line-height:1.6}
.spend .it b{color:#ffd07a}
.spend .week{font-size:11px;color:rgba(235,240,250,.55);margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.1);font-weight:600}
.spend .week b{color:#ff9aa6;font-weight:800}
.bal{display:flex;align-items:center;justify-content:space-between}
.bal .big{font-size:24px;font-weight:900;letter-spacing:-.6px}
.bal .split{font-size:13px;font-weight:700;color:rgba(235,240,250,.62)}
.pos{color:#52e08a}.neg{color:#ff6b7d}
.fest{padding:12px 15px;border-radius:18px;font-size:13px;font-weight:600;line-height:1.42;
  background:linear-gradient(135deg,rgba(255,122,192,.18),rgba(177,139,255,.13));border:1px solid rgba(255,122,192,.32)}
.fest .t{font-weight:800;color:#ff9ed4}
.hiphop{padding:12px 15px;border-radius:18px;font-size:13px;font-weight:600;line-height:1.42;
  background:linear-gradient(135deg,rgba(255,198,87,.16),rgba(255,107,125,.11));border:1px solid rgba(255,198,87,.32)}
.hiphop .t{font-weight:800;color:#ffd07a}
.foot{margin-top:auto;text-align:center;font-size:10.5px;color:rgba(235,240,250,.34);font-weight:600;letter-spacing:.4px}
.zh{color:#ffd07a;font-weight:900;font-style:normal}
"""


def _esc(s):
    return _html.escape(str(s or ""))


def build_html(d):
    urgent = d.get("urgent") or []
    reminders = d.get("reminders") or []
    spend_today = d.get("spend_today") or []
    parts = []
    parts.append('<div class="head"><div class="anchor">⚓</div><div>'
                 f'<div class="greet">☀️ Доброе утро, Слава! <span class="zh">Ж</span></div>'
                 f'<div class="date">{_esc(d.get("date_str"))}</div></div></div>')

    # Блок Wirtschaftsdezernent — всегда первым
    w = d.get("wirtschaft") or {}
    appointed = w.get("appointed")
    w_status = _esc(w.get("status") or "")
    if appointed is True:
        w_icon, w_title, w_color = "✅", "Wirtschaftsdezernent назначен!", "#52e08a"
        name_str = _esc(w.get("name") or "")
        party_str = _esc(w.get("party") or "")
        date_str = _esc(w.get("date") or "")
        w_body = f'<b>{name_str}</b> ({party_str})' + (f'<br>Вступает: {date_str}' if date_str else "")
    elif appointed is False:
        w_icon, w_title, w_color = "⏳", "Wirtschaftsdezernent не назначен", "#ffd07a"
        w_body = w_status
    else:
        w_icon, w_title, w_color = "🏛", "Франкфурт / Wirtschaftsdezernat", "rgba(235,240,250,.6)"
        w_body = w_status or "нет данных"
    parts.append(
        f'<div class="card glass" style="border-left:3px solid {w_color}">'
        f'<div class="h">{w_icon} {w_title}</div>'
        f'<div class="li" style="color:{w_color}">{w_body}</div></div>'
    )

    if d.get("wisdom"):
        parts.append(f'<div class="wisdom glass"><span class="q">"</span><span>{_esc(d["wisdom"])}</span></div>')

    if urgent:
        items = "".join(f'<div class="li">• {_esc(t)}</div>' for t in urgent[:4])
        parts.append(f'<div class="card glass"><div class="h">🔥 Срочное на сегодня</div>{items}</div>')
    else:
        parts.append('<div class="card glass"><div class="h">🔥 Сегодня</div>'
                     '<div class="li">Срочного нет — день для важного ✨</div></div>')

    if reminders:
        items = "".join(f'<div class="li"><span class="t">{_esc(tm)}</span> {_esc(tx)}</div>' for tm, tx in reminders[:3])
        parts.append(f'<div class="card glass"><div class="h">⏰ Напоминания</div>{items}</div>')

    # spend today + balance side by side
    sum_today = d.get("sum_today", 0)
    if spend_today:
        sit = "".join(f'<div class="it">• {_esc(t)} — <b>{a:.0f}€</b></div>' for t, a in spend_today[:3])
    else:
        sit = '<div class="it">плановых платежей нет</div>'
    week = ""
    if d.get("sum_week"):
        week = (f'<div class="week">7 дней: <b>{d["sum_week"]:.0f}€</b> · {_esc(d.get("week_names"))}</div>')
    spend_card = (f'<div class="card spend glass"><div class="h">💸 Расходы сегодня</div>'
                  f'<div class="big">{sum_today:.0f}€</div>{sit}{week}</div>')
    parts.append(spend_card)

    bal = d.get("balance", 0)
    parts.append(f'<div class="card glass bal"><div><div class="h" style="margin-bottom:4px">💰 Баланс</div>'
                 f'<div class="big">{bal:.0f}€</div></div>'
                 f'<div class="split">💵 {d.get("cash",0):.0f} · 💳 {d.get("card",0):.0f}</div></div>')

    if d.get("holiday"):
        parts.append(f'<div class="fest"><span class="t">🎉 Праздник дня:</span> {_esc(d["holiday"])}</div>')
    if d.get("hiphop"):
        parts.append(f'<div class="hiphop"><span class="t">🎤 Хип-хоп календарь:</span> {_esc(d["hiphop"])}</div>')

    parts.append('<div class="foot">⚓ Капитанский мостик · система Фридмана</div>')

    body = "\n".join(parts)
    return ("<!DOCTYPE html><html lang=ru><head><meta charset=utf-8>"
            "<meta name=viewport content='width=390,initial-scale=1'>"
            f"<style>{CSS}</style></head><body><div class=bg></div>"
            f"<div class=wrap>{body}</div></body></html>")


def render_brief_jpeg(d, out_path):
    """Рендер JPEG через Playwright. Бросает исключение при сбое — вызывающий ловит и шлёт текст."""
    from playwright.sync_api import sync_playwright
    htmltext = build_html(d)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox",
                                            "--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": IPHONE_W, "height": IPHONE_H},
                                device_scale_factor=SCALE)
        page.set_content(htmltext, wait_until="networkidle")
        page.wait_for_timeout(250)
        page.screenshot(path=out_path, type="jpeg", quality=92,
                        clip={"x": 0, "y": 0, "width": IPHONE_W, "height": IPHONE_H})
        browser.close()
    return out_path


if __name__ == "__main__":
    sample = {
        "date_str": "Воскресенье, 14 июня · 08:00",
        "wisdom": "Хаос становится управляемым в тот момент, когда ты выгружаешь его из головы.",
        "urgent": ["Эскиз стены для Роберта", "Счёт Стефану за стену"],
        "reminders": [("19:00", "Мостик — итоги недели")],
        "spend_today": [("Аренда студии", 30), ("Подписки", 15)],
        "sum_today": 45, "sum_week": 395, "week_names": "аренда · телефон · налог · спортзал",
        "balance": 220, "cash": 340, "card": -120,
        "holiday": "Международный день уличного искусства — твой день, FARBAHOLIX 🎨",
        "hiphop": "Сегодня ДР у MF DOOM 🕊 — легенда андеграунда, мастер метафор.",
    }
    out = os.path.join(os.path.dirname(__file__), "brief_sample.jpg")
    print(render_brief_jpeg(sample, out))
