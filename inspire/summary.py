"""Ежедневная сводка Inspire: текст для Telegram + JPEG 1179×2556 (экран iPhone 15/16/17 Pro).

    python summary.py            # → storage/summary_YYYY-MM-DD.jpg
"""
import html
import os
from datetime import date

import content
import stats
from config import CURRENCY, COLLECTIVE, STORAGE

LEADER = os.environ.get("LEADER_NAME", "")
WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def e(x):
    return html.escape(str(x))


def m(x):
    return stats.money(x, CURRENCY)


def _bars(series):
    w, h, gap = 330, 74, 6
    mx = max(v for _, v in series) or 1
    bw = (w - gap * (len(series) - 1)) / len(series)
    out = []
    for i, (lab, v) in enumerate(series):
        bh = max(3, v / mx * (h - 20))
        x = i * (bw + gap)
        last = i == len(series) - 1
        out.append(f'<rect x="{x:.1f}" y="{h - 16 - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" '
                   f'fill="{"#0A84FF" if last else "rgba(255,255,255,.28)"}"/>'
                   f'<text x="{x + bw / 2:.1f}" y="{h - 2}" text-anchor="middle" font-size="9" '
                   f'fill="rgba(255,255,255,{.95 if last else .5})">{lab}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">{"".join(out)}</svg>'


def build_html(s, today):
    q, qa = content.quote_of_day(today)
    hist_title, hist, exact = content.history_for(today)
    mom = s["mom_pct"]
    mom_html = (f'<span class="chip {"up" if mom >= 0 else "down"}">{"▲" if mom >= 0 else "▼"} {abs(mom):.0f}%</span>'
                if mom is not None else "")
    att_d = s["attendance_30"] - s["attendance_prev"]
    nxt = s["upcoming"][0] if s["upcoming"] else None
    today_lines = []
    for r in s["rehearsals_today"][:3]:
        today_lines.append(f'<div class="li"><b>{e(r["time"])}</b> репетиция {e(r["group_name"])}</div>')
    for b in s["birthdays"][:2]:
        today_lines.append(f'<div class="li">🎂 День рождения: <b>{e(b["name"])}</b> · {e(b["group_name"])}</div>')
    for f in s["followups"][:2]:
        today_lines.append(f'<div class="li">📞 {e(f["company"] or f["name"])}: {e(f["next_step"])}</div>')
    if s["unread"]:
        today_lines.append(f'<div class="li">💬 Непрочитанных от танцоров: <b>{s["unread"]}</b></div>')
    if not today_lines:
        today_lines.append('<div class="li">Свободный день. Отличный повод поставить новый номер.</div>')
    hist_html = "".join(f'<div class="hi"><span class="yr">{y}</span><span>{e(t)}</span></div>' for y, t in hist[:2])
    ours = s["our_history"][-1] if s["our_history"] else None
    if ours:
        hist_html += (f'<div class="hi"><span class="yr acc">{ours["date"][:4]}</span>'
                      f'<span>Inspire: {e(ours["title"])} · {e(ours["venue"])}</span></div>')
    greet = f"Доброе утро{', ' + e(LEADER) if LEADER else ''}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}
body{{width:393px;height:852px;overflow:hidden;font-family:-apple-system,"SF Pro Display",Inter,"Helvetica Neue",sans-serif;
color:#fff;background:#07070c;position:relative;-webkit-font-smoothing:antialiased}}
.bg{{position:absolute;inset:0;background:
radial-gradient(60% 40% at 15% 8%,#5e2bff 0%,transparent 70%),
radial-gradient(55% 35% at 95% 22%,#ff2d87 0%,transparent 70%),
radial-gradient(70% 40% at 50% 100%,#0a84ff 0%,transparent 70%),#07070c;filter:saturate(1.15)}}
.wrap{{position:relative;padding:50px 16px 0;display:flex;flex-direction:column;gap:8px}}
.top{{display:flex;justify-content:space-between;align-items:flex-end}}
.date{{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;opacity:.7}}
h1{{font-size:29px;font-weight:800;letter-spacing:-.02em;line-height:1.05}}
.greet{{font-size:15px;opacity:.85;margin-top:2px}}
.logo{{font-size:12px;font-weight:700;letter-spacing:.2em;padding:6px 10px;border-radius:99px;
background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25)}}
.g{{background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);border-radius:22px;
padding:10px 13px;backdrop-filter:blur(30px);box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.k{{font-size:10.5px;font-weight:600;opacity:.65;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}}
.v{{font-size:21px;white-space:nowrap;font-weight:750;letter-spacing:-.02em;margin-top:3px;font-variant-numeric:tabular-nums}}
.s{{font-size:11.5px;opacity:.7;margin-top:2px}}
.chip{{font-size:10.5px;font-weight:700;padding:1px 6px;border-radius:99px;margin-right:4px}}
.up{{background:rgba(48,209,88,.25);color:#5cf08a}} .down{{background:rgba(255,69,58,.25);color:#ff8a80}}
.h{{font-size:12.5px;font-weight:700;margin-bottom:4px;display:flex;justify-content:space-between}}
.h span{{opacity:.6;font-weight:500}}
.li{{font-size:12.5px;line-height:1.3;padding:3px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-top:1px solid rgba(255,255,255,.08)}}
.li:first-of-type{{border-top:0}}
.q{{font-size:14.5px;line-height:1.3;font-weight:600;letter-spacing:-.01em}}
.qa{{font-size:12px;opacity:.65;margin-top:6px}}
.hi{{display:flex;gap:10px;font-size:12px;line-height:1.3;padding:2px 0}}
.yr{{font-weight:800;color:#ffd60a;min-width:36px;font-variant-numeric:tabular-nums}} .yr.acc{{color:#64d2ff}}
.foot{{text-align:center;font-size:10.5px;opacity:.45;margin-top:2px}}
</style></head><body><div class="bg"></div><div class="wrap">
<div class="top"><div><div class="date">{WD[today.weekday()]}, {today.day} {content.MONTHS[today.month - 1]}</div>
<h1>{e(COLLECTIVE)} · сводка</h1><div class="greet">{greet}</div></div></div>
<div class="grid">
<div class="g"><div class="k">Поступления, месяц</div><div class="v">{m(s["income_month"])}</div>
<div class="s">{mom_html}вчера +{m(s["income_yesterday"])}</div></div>
<div class="g"><div class="k">Прибыль, месяц</div><div class="v">{m(s["profit_month"])}</div>
<div class="s">расходы {m(s["expense_month"])}</div></div>
<div class="g"><div class="k">Ждём оплат</div><div class="v">{m(s["receivables"])}</div>
<div class="s">{len(s["debtors"])} проект(ов) не закрыто</div></div>
<div class="g"><div class="k">Посещаемость 30 дн</div><div class="v">{s["attendance_30"]:.0f}%</div>
<div class="s">{"+" if att_d >= 0 else "−"}{abs(att_d):.1f} п.п. · {s["dancers_active"]} активных</div></div>
</div>
<div class="g"><div class="h">Поступления за 12 месяцев <span>год: {m(s["income_year"])}</span></div>{_bars(s["income_12m"])}</div>
<div class="g"><div class="h">Сегодня <span>воронка {m(s["pipeline"])}</span></div>{"".join(today_lines[:5])}
{f'<div class="li">⭐ Ближайшее: <b>{e(nxt["title"])}</b> · {e(nxt["date"][8:10])}.{e(nxt["date"][5:7])} · 👥 {nxt["ready"]}/{nxt["dancers_needed"]}</div>' if nxt else ""}</div>
<div class="g"><div class="h">Цитата дня</div><div class="q">«{e(q)}»</div><div class="qa">— {e(qa)}</div></div>
<div class="g"><div class="h">{"Этот день в истории" if exact else "Скоро в календаре"} <span>{e(hist_title)}</span></div>{hist_html}</div>
<div class="foot">Inspire · {s["dancers_tg"]} танцоров на связи в боте</div>
</div></body></html>"""


def render_jpeg(out_path=None, today=None):
    from playwright.sync_api import sync_playwright
    today = today or date.today()
    s = stats.collect(today)
    out_path = out_path or os.path.join(STORAGE, f"summary_{today.isoformat()}.jpg")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    exe = os.environ.get("CHROMIUM_PATH")  # если Playwright-браузер другой версии — укажите путь вручную
    with sync_playwright() as p:
        b = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        pg = b.new_page(viewport={"width": 393, "height": 852}, device_scale_factor=3)
        pg.set_content(build_html(s, today), wait_until="networkidle")
        pg.screenshot(path=out_path, type="jpeg", quality=90)
        b.close()
    return out_path


def text_summary(today=None):
    """Короткая текстовая подпись к картинке (и запасной вариант, если браузер недоступен)."""
    today = today or date.today()
    s = stats.collect(today)
    q, qa = content.quote_of_day(today)
    ht, hist, _ = content.history_for(today)
    mom = f" ({'+' if s['mom_pct'] >= 0 else ''}{s['mom_pct']:.0f}% к прошлому месяцу)" if s["mom_pct"] is not None else ""
    lines = [f"☀️ <b>{COLLECTIVE} · {today.strftime('%d.%m.%Y')}</b>",
             f"💶 Месяц: {m(s['income_month'])}{mom}, прибыль {m(s['profit_month'])}",
             f"⏳ Ждём оплат: {m(s['receivables'])} · воронка {m(s['pipeline'])}",
             f"💃 Посещаемость 30 дн: {s['attendance_30']:.0f}% · в боте {s['dancers_tg']}/{s['dancers_total']}"]
    if s["birthdays"]:
        lines.append("🎂 " + ", ".join(b["name"] for b in s["birthdays"]))
    if s["unread"]:
        lines.append(f"💬 Непрочитанных: {s['unread']}")
    lines.append(f"\n<i>«{q}»</i> — {qa}")
    if hist:
        lines.append(f"📜 {ht}: {hist[0][0]} — {hist[0][1]}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_jpeg())
    print(text_summary())
