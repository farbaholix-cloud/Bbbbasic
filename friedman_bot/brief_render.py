"""Рендер утренней сводки в одностраничный JPEG (iOS 26 стиль), точно под iPhone.

Использует Playwright (headless Chromium). На сервере один раз:
    pip install playwright && playwright install chromium
    apt install -y fonts-noto-color-emoji fonts-dejavu   # эмодзи + кириллица
Если что-то из этого недоступно — бот сам откатится на текстовую сводку.
"""

import os
import math
import html as _html

# Шесть осей «звезды счастья» — те же ключи/цвета/эмодзи, что и во вкладке Счастье
# дашборда. Геометрия (ex,ey) в процентах смещения от центра карты повторяет раскладку
# мостика: 2 горизонтали + 4 диагонали → силуэт буквы «Ж».
H_BRIEF = [
    ("work",       "💼", "#5b9dff", (30, -30)),
    ("friendship", "🤝", "#ff7ac0", (-30, -30)),
    ("health",     "🌿", "#52e08a", (42, 0)),
    ("love",       "❤️", "#ff6b7d", (-42, 0)),
    ("wellbeing",  "💰", "#ffd07a", (30, 30)),
    ("hobby",      "🎨", "#b18bff", (-30, 30)),
]
_HVB_W, _HVB_H = 300.0, 190.0  # система координат SVG-линий


def _happiness_block(hap):
    """HTML «звезды счастья»: длина каждого луча ∝ √(оценка/5), как в дашборде."""
    hap = hap or {}
    vals = {}
    for key, _emoji, _color, _geo in H_BRIEF:
        try:
            v = int(round(float(hap.get(key) or 3)))
        except (TypeError, ValueError):
            v = 3
        vals[key] = max(1, min(5, v))
    minval = min(vals.values())
    cx, cy = _HVB_W / 2, _HVB_H / 2
    lines, nodes = [], []
    for key, emoji, color, (ex, ey) in H_BRIEF:
        t = math.sqrt(vals[key] / 5.0)
        left = 50 + ex * t
        top = 50 + ey * t
        x = left / 100 * _HVB_W
        y = top / 100 * _HVB_H
        lines.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="14" stroke-opacity="0.12"/>'
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="2" stroke-opacity="0.92"/>'
        )
        nodes.append(
            f'<div class="hn" style="left:{left:.1f}%;top:{top:.1f}%">'
            f'<div class="hdot" style="background:linear-gradient(145deg,{color},{color}99);'
            f'box-shadow:0 0 0 1px {color}66,0 0 16px {color}aa,0 6px 16px rgba(0,0,0,.5)">{emoji}</div>'
            f'<div class="hnv" style="color:{color}">{vals[key]}</div></div>'
        )
    svg = (f'<svg class="hlines" viewBox="0 0 {_HVB_W:.0f} {_HVB_H:.0f}" '
           f'preserveAspectRatio="none">{"".join(lines)}</svg>')
    return (
        '<div class="card glass hap">'
        '<div class="h">🤗 Баланс счастья</div>'
        f'<div class="sub">слабее всего сейчас — {minval}/5 · нажми, переосознай в дашборде</div>'
        f'<div class="hmap">{svg}<div class="hcenter">{minval}</div>{"".join(nodes)}</div>'
        '<div class="hfoot">⚓ Капитанский мостик · система Фридмана</div>'
        '</div>'
    )

# Размер ровно под iPhone 14 (390x844 pt @3x = 1170x2532 px). Меняется при другой модели.
IPHONE_W = 390
IPHONE_H = 844
SCALE = 3

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
/* Высота НЕ фиксирована: короткая сводка = ровно экран iPhone (min-height),
   длинная — растёт вниз, картинка получается выше экрана (листаешь). */
html,body{width:390px;overflow:hidden}
body{font-family:-apple-system,'Inter','Helvetica Neue','Noto Sans',sans-serif;color:#f4f6fb;position:relative;
  min-height:844px;background:#0a0b14}
.bg{position:absolute;inset:0;z-index:0;
  background:
   radial-gradient(46% 30% at 16% 6%, rgba(91,157,255,.62), transparent 60%),
   radial-gradient(44% 28% at 88% 4%, rgba(177,139,255,.56), transparent 60%),
   radial-gradient(54% 32% at 92% 70%, rgba(65,227,212,.42), transparent 62%),
   radial-gradient(56% 34% at 6% 88%, rgba(255,122,192,.42), transparent 60%),
   radial-gradient(50% 28% at 50% 44%, rgba(255,198,87,.16), transparent 60%),
   linear-gradient(165deg,#0e1126,#0a0b14 65%)}
.wrap{position:relative;z-index:1;min-height:844px;padding:40px 18px 14px;display:flex;flex-direction:column;gap:8px}
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
.legal{padding:13px 15px;border-radius:18px;
  background:linear-gradient(135deg,rgba(91,157,255,.16),rgba(65,227,212,.10));border:1px solid rgba(91,157,255,.34)}
.legal .h{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:#9dc0ff;margin-bottom:7px;display:flex;align-items:center;gap:7px}
.legal .body{font-size:13px;font-weight:600;line-height:1.5;color:#eef0f4}
.legal .imp{font-size:12px;font-weight:600;color:rgba(235,240,250,.72);margin-top:7px;line-height:1.42}
.legal .meta{font-size:10.5px;font-weight:700;color:rgba(235,240,250,.48);margin-top:8px;padding-top:7px;border-top:1px solid rgba(255,255,255,.12);display:flex;justify-content:space-between;gap:8px}
.legal .meta .cf{color:#7fe0c4}
/* Баланс счастья — «звезда Ж» из вкладки Счастье, внизу сводки */
.hap{margin-top:auto;padding:12px 15px 13px}
.hap .h{margin-bottom:2px}
.hap .sub{font-size:11px;font-weight:700;color:rgba(235,240,250,.5);margin-bottom:2px}
.hmap{position:relative;width:100%;height:138px}
.hlines{position:absolute;inset:0;width:100%;height:100%}
.hcenter{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:48px;height:48px;border-radius:50%;
  background:radial-gradient(circle at 38% 28%,#48485a,#06060e);display:flex;align-items:center;justify-content:center;
  font-size:21px;font-weight:900;color:#ffd07a;z-index:3;text-shadow:0 2px 10px rgba(255,208,122,.5);
  box-shadow:0 0 0 1.5px rgba(255,255,255,.18),inset 0 1.5px 0 rgba(255,255,255,.3),0 6px 22px rgba(0,0,0,.85)}
.hn{position:absolute;transform:translate(-50%,-50%);text-align:center;z-index:2}
.hdot{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:17px;margin:0 auto;
  border:1px solid rgba(255,255,255,.45)}
.hnv{font-size:13px;font-weight:900;margin-top:2px;text-shadow:0 1px 5px rgba(0,0,0,.65)}
.hfoot{text-align:center;font-size:10px;color:rgba(235,240,250,.34);font-weight:600;letter-spacing:.4px;margin-top:8px}
"""


def _esc(s):
    return _html.escape(str(s or ""))


def build_html(d):
    urgent = d.get("urgent") or []
    reminders = d.get("reminders") or []
    spend_today = d.get("spend_today") or []
    parts = []
    parts.append('<div class="head"><div class="anchor">⚓</div><div>'
                 f'<div class="greet">☀️ Доброе утро, Слава!</div>'
                 f'<div class="date">{_esc(d.get("date_str"))}</div></div></div>')

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

    # Свежие немецкие/ЕС правовые новости для украинцев призывного возраста
    legal = d.get("ua_legal") or {}
    if legal.get("summary"):
        imp = (f'<div class="imp">🎯 {_esc(legal["importance"])}</div>' if legal.get("importance") else "")
        meta_bits = []
        if legal.get("date"):
            meta_bits.append(f'<span>🗓 {_esc(legal["date"])}</span>')
        if legal.get("confidence"):
            meta_bits.append(f'<span class="cf">✓ достоверность: {_esc(legal["confidence"])}</span>')
        meta = f'<div class="meta">{"".join(meta_bits)}</div>' if meta_bits else ""
        parts.append(
            '<div class="legal">'
            '<div class="h">🛂 Украинцы призывного возраста · DE/ЕС</div>'
            f'<div class="body">{_esc(legal["summary"])}</div>{imp}{meta}</div>')

    # Внизу — «звезда счастья» (бывшая заглушка «Ж»), красиво вписанная в дизайн
    parts.append(_happiness_block(d.get("happiness")))

    body = "\n".join(parts)
    return ("<!DOCTYPE html><html lang=ru><head><meta charset=utf-8>"
            "<meta name=viewport content='width=390,initial-scale=1'>"
            f"<style>{CSS}</style></head><body><div class=bg></div>"
            f"<div class=wrap>{body}</div></body></html>")


def render_brief_jpeg(d, out_path):
    """Рендер JPEG через Playwright. Возвращает высоту картинки в CSS-px (для
    решения фото/документ). Бросает исключение при сбое — вызывающий ловит и шлёт текст."""
    from playwright.sync_api import sync_playwright
    htmltext = build_html(d)
    height_css = IPHONE_H
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox",
                                            "--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": IPHONE_W, "height": IPHONE_H},
                                device_scale_factor=SCALE)
        page.set_content(htmltext, wait_until="networkidle")
        page.wait_for_timeout(250)
        try:
            height_css = int(page.evaluate("document.documentElement.scrollHeight")) or IPHONE_H
        except Exception:
            height_css = IPHONE_H
        # full_page: если сводка выше экрана iPhone — картинка получается длинной,
        # владелец пролистывает её при необходимости (min-height держит короткие
        # сводки ровно в один экран).
        page.screenshot(path=out_path, type="jpeg", quality=92, full_page=True)
        browser.close()
    return height_css


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
        "ua_legal": {
            "summary": "Временная защита §24 продлена до 04.03.2026 · BAMF: смена статуса на §24a возможна с 2025 · дискуссия в ЕС о правилах выезда мужчин 18–60 — решений пока нет",
            "importance": "Касается напрямую: твой статус §24 продлён, срочных действий не требуется.",
            "confidence": "высокая — источники BAMF и Bundesregierung",
            "date": "новости за последние 3 недели",
        },
        "happiness": {"work": 4, "friendship": 3, "health": 5, "wellbeing": 2, "hobby": 4, "love": 3},
    }
    out = os.path.join(os.path.dirname(__file__), "brief_sample.jpg")
    print("height css:", render_brief_jpeg(sample, out), "→", out)
