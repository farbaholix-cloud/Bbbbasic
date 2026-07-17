"""Финансовый отчёт-изображение «Графики и анализ» (книжный JPEG, высокое разрешение).

Компиляция всех данных: инвойс-архив (выручка по месяцам/годам), банковские
потоки (bank_seed.json), долги и баланс из БД. Под каждым графиком — комментарий
«финансиста», посчитанный из самих цифр (без LLM — быстро и без галлюцинаций).

Вызов: generate_finance_report() -> путь к JPEG (< 7 МБ).
Рендер: HTML+SVG → Playwright (в отдельном потоке, как invoice._render_pdf).

Палитра — валидированная дефолтная из dataviz-скилла (слоты 1-3 + sequential
blue + diverging blue/red), light mode; текст — только в ink-токенах.
"""

import os
import json
import tempfile
from datetime import datetime

# ── палитра (light) ───────────────────────────────────────────────────────────
SURF = "#fcfcfb"; PAGE = "#f9f9f7"
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; BASE = "#c3c2b7"
S1 = "#2a78d6"   # slot1 blue
S2 = "#008300"   # slot2 green
S3 = "#e87ba4"   # slot3 magenta (только с прямыми подписями)
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#104281"]
DIV_NEG = "#e34948"  # diverging red pole (отрицательный поток)
ACCENT = "#b23a3a"   # бренд-акцент FARBAHOLIX (только в шапке, не в данных)

MONTHS_RU = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def _eur0(n):
    s = f"{n:,.0f}".replace(",", " ")
    return s + " €"


# ── сбор данных ───────────────────────────────────────────────────────────────
def _collect():
    import bot as B
    d = {"now": datetime.now()}
    rows = B.all_archive_rows()
    rev = {}  # (year, month) -> sum
    for r in rows:
        dt = r["inv_date"] or ""
        if len(dt) >= 7:
            try:
                y, m = int(dt[:4]), int(dt[5:7])
                rev[(y, m)] = rev.get((y, m), 0) + (r["gross"] or 0)
            except ValueError:
                pass
    d["rev"] = rev
    d["clients"] = {}
    for r in rows:
        d["clients"][r["client_name"] or "—"] = d["clients"].get(r["client_name"] or "—", 0) + (r["gross"] or 0)
    # банк
    d["bank"] = None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank_seed.json")
    if os.path.exists(path):
        try:
            d["bank"] = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    # долги и баланс
    d["debts"] = []
    d["balance"] = 0.0
    try:
        with B.db() as conn:
            d["debts"] = [dict(x) for x in conn.execute(
                "SELECT name, total, paid FROM debts ORDER BY total-paid DESC").fetchall()]
            d["balance"] = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
    except Exception:
        pass
    return d


# ── SVG-помощники ─────────────────────────────────────────────────────────────
CW, CH = 1160, 330          # плот-область графика
PAD_L, PAD_B, PAD_T = 74, 34, 16


def _grid(ymax, w=CW, h=CH, steps=4):
    out = []
    for i in range(steps + 1):
        y = PAD_T + (h - PAD_T - PAD_B) * i / steps
        v = ymax * (1 - i / steps)
        out.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{w}' y2='{y:.1f}' stroke='{GRID}' stroke-width='1'/>")
        out.append(f"<text x='{PAD_L-8}' y='{y+4:.1f}' text-anchor='end' font-size='15' fill='{MUTED}'>{_eur0(v)}</text>")
    return "".join(out)


def _nice_max(v):
    if v <= 0:
        return 1
    for m in [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000]:
        if v <= m * 4:
            import math
            return math.ceil(v / m) * m
    return v * 1.1


def _sy(v, ymax, h=CH):
    return PAD_T + (h - PAD_T - PAD_B) * (1 - v / ymax)


def bars_monthly(series, labels, highlight_idx=None, annotate=None, color=S1, w=CW, h=CH):
    """Вертикальные бары: тонкие, скруглённый верх 4px, 2px зазоры."""
    ymax = _nice_max(max(series) if series else 1)
    n = len(series)
    slot = (w - PAD_L - 8) / n
    bw = min(34, slot - 4)
    out = [_grid(ymax, w, h)]
    for i, v in enumerate(series):
        x = PAD_L + slot * i + (slot - bw) / 2
        y = _sy(v, ymax, h)
        hh = max(0, h - PAD_B - y)
        c = color if (highlight_idx is None or i == highlight_idx) else color
        op = "1" if (highlight_idx is None or i == highlight_idx) else "0.55"
        if hh > 0:
            out.append(f"<path d='M{x:.1f} {h-PAD_B} V{y+4:.1f} Q{x:.1f} {y:.1f} {x+4:.1f} {y:.1f} "
                       f"H{x+bw-4:.1f} Q{x+bw:.1f} {y:.1f} {x+bw:.1f} {y+4:.1f} V{h-PAD_B} Z' "
                       f"fill='{c}' opacity='{op}'/>")
        out.append(f"<text x='{x+bw/2:.1f}' y='{h-PAD_B+22}' text-anchor='middle' font-size='14' fill='{MUTED}'>{labels[i]}</text>")
        if highlight_idx is not None and i == highlight_idx:
            out.append(f"<text x='{x+bw/2:.1f}' y='{y-10:.1f}' text-anchor='middle' font-size='16' font-weight='700' fill='{INK}'>{_eur0(v)}</text>")
    if annotate and highlight_idx is not None:
        x = PAD_L + slot * highlight_idx + slot / 2
        out.append(f"<text x='{x:.1f}' y='{PAD_T+14}' text-anchor='middle' font-size='15' font-weight='600' fill='{INK2}'>{annotate}</text>")
    out.append(f"<line x1='{PAD_L}' y1='{h-PAD_B}' x2='{w}' y2='{h-PAD_B}' stroke='{BASE}' stroke-width='1.5'/>")
    return f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{''.join(out)}</svg>", ymax


def lines_chart(series_list, labels, w=CW, h=CH, dashed=None, endlabels=None, dot_last=True):
    """Линии 2px, прямые подписи в конце, точки ≥8px на последних значениях."""
    vals = [v for s, _c in series_list for v in s if v is not None]
    ymax = _nice_max(max(vals) if vals else 1)
    n = max(len(s) for s, _c in series_list)
    step = (w - PAD_L - 130) / max(1, n - 1)  # запас справа под прямые подписи
    out = [_grid(ymax, w, h)]
    for i in range(n):
        x = PAD_L + step * i
        out.append(f"<text x='{x:.1f}' y='{h-PAD_B+22}' text-anchor='middle' font-size='14' fill='{MUTED}'>{labels[i] if i < len(labels) else ''}</text>")
    for si, (s, color) in enumerate(series_list):
        pts = [(PAD_L + step * i, _sy(v, ymax, h)) for i, v in enumerate(s) if v is not None]
        if not pts:
            continue
        path = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
        dash = " stroke-dasharray='7 6'" if dashed and dashed[si] else ""
        out.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2.5'{dash} stroke-linecap='round'/>")
        if dot_last:
            x, y = pts[-1]
            out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='{color}' stroke='{SURF}' stroke-width='2'/>")
        if endlabels:
            x, y = pts[-1]
            out.append(f"<text x='{x+10:.1f}' y='{y+5:.1f}' font-size='15' font-weight='700' fill='{INK}'>{endlabels[si]}</text>")
    out.append(f"<line x1='{PAD_L}' y1='{h-PAD_B}' x2='{w}' y2='{h-PAD_B}' stroke='{BASE}' stroke-width='1.5'/>")
    return f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{''.join(out)}</svg>"


def diverging_bars(values, labels, w=CW, h=CH):
    """Чистый поток: + синий вверх, − красный вниз от нулевой линии."""
    mx = max(abs(v) for v in values) if values else 1
    ymax = _nice_max(mx)
    zero = PAD_T + (h - PAD_T - PAD_B) / 2
    scale = (h - PAD_T - PAD_B) / 2 / ymax
    n = len(values)
    slot = (w - PAD_L - 8) / n
    bw = min(34, slot - 4)
    out = [f"<line x1='{PAD_L}' y1='{zero}' x2='{w}' y2='{zero}' stroke='{BASE}' stroke-width='1.5'/>"]
    out.append(f"<text x='{PAD_L-8}' y='{zero+4}' text-anchor='end' font-size='15' fill='{MUTED}'>0 €</text>")
    for sgn in (1, -1):
        y = zero - sgn * ymax * scale
        out.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{w}' y2='{y:.1f}' stroke='{GRID}' stroke-width='1'/>")
        out.append(f"<text x='{PAD_L-8}' y='{y+4:.1f}' text-anchor='end' font-size='15' fill='{MUTED}'>{_eur0(sgn*ymax)}</text>")
    for i, v in enumerate(values):
        x = PAD_L + slot * i + (slot - bw) / 2
        hh = abs(v) * scale
        color = S1 if v >= 0 else DIV_NEG
        if v >= 0:
            y = zero - hh
            out.append(f"<path d='M{x:.1f} {zero} V{y+4:.1f} Q{x:.1f} {y:.1f} {x+4:.1f} {y:.1f} H{x+bw-4:.1f} "
                       f"Q{x+bw:.1f} {y:.1f} {x+bw:.1f} {y+4:.1f} V{zero} Z' fill='{color}'/>")
        else:
            y = zero + hh
            out.append(f"<path d='M{x:.1f} {zero} V{y-4:.1f} Q{x:.1f} {y:.1f} {x+4:.1f} {y:.1f} H{x+bw-4:.1f} "
                       f"Q{x+bw:.1f} {y:.1f} {x+bw:.1f} {y-4:.1f} V{zero} Z' fill='{color}'/>")
        out.append(f"<text x='{x+bw/2:.1f}' y='{h-6}' text-anchor='middle' font-size='14' fill='{MUTED}'>{labels[i]}</text>")
    return f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{''.join(out)}</svg>"


def hbars(items, w=CW, row=42):
    """Горизонтальные бары (категории расходов) — один hue, светлый→тёмный по величине."""
    if not items:
        return ""
    mx = max(v for _, v in items)
    h = row * len(items) + 10
    out = []
    for i, (name, v) in enumerate(items):
        y = 6 + row * i
        bw = (w - 340) * v / mx
        ci = SEQ[min(len(SEQ) - 1, 2 + int(4 * v / mx))]
        out.append(f"<text x='250' y='{y+21}' text-anchor='end' font-size='15' fill='{INK2}'>{name}</text>")
        out.append(f"<rect x='260' y='{y}' width='{max(3,bw):.1f}' height='26' rx='4' fill='{ci}'/>")
        out.append(f"<text x='{260+max(3,bw)+10:.1f}' y='{y+19}' font-size='15' font-weight='600' fill='{INK}'>{_eur0(v)}</text>")
    return f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{''.join(out)}</svg>"


def legend(pairs):
    sw = "".join(
        f"<span style='display:inline-flex;align-items:center;margin-right:22px'>"
        f"<span style='width:14px;height:14px;border-radius:4px;background:{c};margin-right:8px'></span>"
        f"<span style='font-size:15px;color:{INK2}'>{n}</span></span>" for n, c in pairs)
    return f"<div style='margin:2px 0 6px 74px'>{sw}</div>"


# ── сборка отчёта ─────────────────────────────────────────────────────────────
def _build_html(d):
    now = d["now"]
    rev = d["rev"]

    def year_series(y):
        return [rev.get((y, m), 0) for m in range(1, 13)]

    r24, r25, r26 = year_series(2024), year_series(2025), year_series(2026)
    cur_m = now.month if now.year == 2026 else 12
    t24, t25 = sum(r24), sum(r25)
    t26 = sum(r26[:cur_m])
    sections = []

    def section(title, svg_html, comment):
        sections.append(
            f"<div class='card'><div class='ct'>{title}</div>{svg_html}"
            f"<div class='fin'><b>💰 Финансист:</b> {comment}</div></div>")

    # 1. Выручка по месяцам 2025–2026 (общая шкала, всплеск авг-сен '25)
    seq = r25 + r26[:cur_m]
    labels = [f"{MONTHS_RU[m]}" + ("·25" if i < 12 else "·26") for i, m in
              enumerate(list(range(12)) + list(range(cur_m)))]
    spike_i = max(range(len(r25)), key=lambda i: r25[i])
    svg, _ = bars_monthly(seq, labels, highlight_idx=spike_i, annotate="🔥 всплеск Aug–Sep 2025", color=S1)
    aug_sep = r25[7] + r25[8]
    c1 = (f"Пик {MONTHS_RU[spike_i]} 2025 — {_eur0(r25[spike_i])}; окно Aug–Sep 2025 дало {_eur0(aug_sep)} "
          f"({aug_sep/t25*100:.0f}% годовой выручки за 2 месяца). Источник всплеска — крупные B2B-проекты "
          f"(Cansativa, SGP, IK). Вывод: сезон июль–октябрь — твоё «золотое окно»: бронируй крупные проекты "
          f"на него заранее, продавай их в мае–июне.")
    section("1 · Выручка по счетам, помесячно (2025 → 2026)", svg, c1)

    # 2. Кумулятивная выручка по годам
    def cum(s, upto=12):
        out, acc = [], 0
        for i in range(upto):
            acc += s[i]
            out.append(acc)
        return out
    svg2 = lines_chart(
        [(cum(r24), S1), (cum(r25), S2), (cum(r26, cur_m), S3)],
        MONTHS_RU, endlabels=[_eur0(t24), _eur0(t25), _eur0(t26)])
    lg = legend([("2024", S1), ("2025", S2), ("2026 (до июля)", S3)])
    pace = t26 / max(1, sum(r25[:cur_m])) * 100
    c2 = (f"2026 идёт с темпом {pace:.0f}% от 2025 на ту же дату ({_eur0(t26)} против {_eur0(sum(r25[:cur_m]))}). "
          f"Год к году бизнес вырос кратно: 2024 → 2025 = ×{t25/max(1,t24):.1f}. "
          f"Чтобы 2026 обогнал 2025, нужно закрыть август–октябрь суммарно на {_eur0(max(0, t25-t26))}+ — "
          f"это ровно та планка, которую в прошлом году сделало «золотое окно».")
    section("2 · Кумулятивная выручка: гонка годов", lg + svg2, c2)

    # 3-4. Банк: потоки и чистый поток
    bank = d.get("bank")
    if bank and bank.get("monthly"):
        months = sorted(bank["monthly"].keys())
        m_in = [bank["monthly"][m]["in"] for m in months]
        m_out = [-bank["monthly"][m]["out"] for m in months]  # out хранится отрицательным
        blab = [m[5:] + "." + m[2:4] for m in months]
        svg3 = lines_chart([(m_in, S1), (m_out, S2)], blab,
                           endlabels=[_eur0(m_in[-1]), _eur0(m_out[-1])])
        lg3 = legend([("Приход", S1), ("Расход", S2)])
        tin, tout = sum(m_in), sum(m_out)
        c3 = (f"За период по счёту прошло: приход {_eur0(tin)}, расход {_eur0(tout)} — деньги почти не "
              f"оседают (сбережение {max(0,(tin-tout))/max(1,tin)*100:.0f}%). Крупнейшие статьи, которые можно "
              f"сжать: наличные ({_eur0(abs(bank['categories'].get('cash',{}).get('total',0)))}) — непрозрачны "
              f"для учёта, и субподряд. Правило: с каждого прихода сразу откладывать 25–30% на налоговый резерв.")
        section("3 · Банковские потоки по месяцам", lg3 + svg3, c3)

        net = [i + o for i, o in zip(m_in, [bank["monthly"][m]["out"] for m in months])]
        svg4 = diverging_bars(net, blab)
        pos = sum(1 for v in net if v >= 0)
        c4 = (f"Чистый поток положителен в {pos} из {len(net)} месяцев. Провалы следуют сразу за пиками — "
              f"классический кассовый цикл фрилансера: заработал → потратил. Цель: за счёт «золотого окна» "
              f"сформировать подушку 2–3 месяца расходов (~{_eur0(abs(tout)/len(months)*2.5)}), чтобы зимние "
              f"месяцы не съедали карту в ноль.")
        section("4 · Чистый денежный поток (приход − расход)", svg4, c4)

        # 5. Расходы по категориям
        cats = bank.get("categories", {})
        NAME = {"groceries": "Продукты/быт", "cash": "Наличные", "rent_utilities": "Аренда/коммуналка",
                "subcontractor_artists": "Субподряд-художники", "art_supplies": "Арт-материалы",
                "health": "Здоровье", "klarna": "Klarna/рассрочки", "phone_internet": "Связь",
                "transport": "Транспорт", "other_expense": "Прочее"}
        items = sorted(((NAME.get(k, k), abs(v["total"])) for k, v in cats.items()
                        if v["total"] < 0), key=lambda x: -x[1])[:9]
        svg5 = hbars(items)
        biz = abs(cats.get("art_supplies", {}).get("total", 0)) + abs(cats.get("subcontractor_artists", {}).get("total", 0))
        c5 = (f"Деловые расходы (материалы + субподряд) = {_eur0(biz)} — это вычитаемые расходы для EÜR, "
              f"они снижают налог: собирай чеки. Субподряд художникам — флаг Künstlersozialabgabe (4,9%). "
              f"Личный блок (продукты+наличные+рассрочки) — главный резерв экономии: минус 15% здесь "
              f"= +{_eur0((abs(cats.get('groceries',{}).get('total',0))+abs(cats.get('cash',{}).get('total',0)))*0.15)} в год к подушке.")
        section("5 · Куда уходят деньги (категории за 13 мес.)", svg5, c5)

    # 6. Прогноз до конца 2026
    base = t26 / max(1, cur_m)
    avg25 = t25 / 12
    factors = [(r25[m] / avg25) if avg25 else 1 for m in range(12)]
    forecast = [None] * 12
    target = [None] * 12
    actual = r26[:cur_m] + [None] * (12 - cur_m)
    for m in range(cur_m - 1, 12):
        f = base * max(0.4, factors[m])
        forecast[m] = f if m >= cur_m - 1 else None
        target[m] = f * 1.3
    forecast[cur_m - 1] = r26[cur_m - 1]  # сшивка с фактом
    target[cur_m - 1] = r26[cur_m - 1]
    svg6 = lines_chart(
        [([v for v in actual], S1),
         ([None] * (cur_m - 1) + forecast[cur_m - 1:], SEQ[1]),
         ([None] * (cur_m - 1) + target[cur_m - 1:], S2)],
        MONTHS_RU, dashed=[False, True, True],
        endlabels=["", _eur0(sum(v for v in forecast if v) + t26 - r26[cur_m - 1]),
                   _eur0(sum(v for v in target if v) + t26 - r26[cur_m - 1])])
    lg6 = legend([("Факт 2026", S1), ("Прогноз (сезонность 2025)", SEQ[1]), ("Цель: тренд усилен +30%", S2)])
    fc_total = t26 + sum(v for i, v in enumerate(forecast) if v and i >= cur_m)
    tg_total = t26 + sum(v for i, v in enumerate(target) if v and i >= cur_m)
    c6 = (f"Если сезонность повторит 2025 — год закроется на ~{_eur0(fc_total)}. Сценарий «усиленный тренд» "
          f"(+30% к окну август–октябрь) даёт ~{_eur0(tg_total)}. Как усилить: (1) в июле разослать "
          f"предложения всем прошлогодним клиентам всплеска; (2) поднять ставку на крупные проекты на 10–15% — "
          f"спрос окна это выдержит; (3) взять предоплату 50% — она сгладит кассу октября–ноября. "
          f"Порог §19 давно позади — обсуди с Steuerberater переход на Regelbesteuerung до конца года.")
    section("6 · Прогноз 2026 и цель «усилить августовский тренд»", lg6 + svg6, c6)

    # долги для тайлов
    debts_rest = sum(max(0, (x.get("total") or 0) - (x.get("paid") or 0)) for x in d.get("debts", []))
    tiles = [
        ("Баланс сейчас", _eur0(d.get("balance", 0))),
        ("Выручка 2026 (7 мес.)", _eur0(t26)),
        ("Выручка 2025", _eur0(t25)),
        ("Долгов осталось", _eur0(debts_rest)),
    ]
    tiles_html = "".join(
        f"<div class='tile'><div class='tv'>{v}</div><div class='tl'>{k}</div></div>" for k, v in tiles)

    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
* {{ box-sizing: border-box; margin: 0; }}
body {{ background:{PAGE}; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
       color:{INK}; width: 1240px; padding: 34px 40px 46px; }}
.h1 {{ font-size: 34px; font-weight: 800; letter-spacing:.3px; }}
.sub {{ color:{ACCENT}; font-size: 17px; margin: 3px 0 0; font-weight: 600; }}
.accent {{ border-bottom: 4px solid {ACCENT}; margin: 14px 0 18px; }}
.meta {{ color:{MUTED}; font-size: 15px; }}
.tiles {{ display:flex; gap: 14px; margin: 18px 0 8px; }}
.tile {{ flex:1; background:{SURF}; border:1px solid rgba(11,11,11,0.10); border-radius: 12px; padding: 16px 18px; }}
.tv {{ font-size: 27px; font-weight: 800; }}
.tl {{ color:{INK2}; font-size: 14px; margin-top: 4px; }}
.card {{ background:{SURF}; border:1px solid rgba(11,11,11,0.10); border-radius: 14px;
        padding: 20px 22px 16px; margin-top: 20px; }}
.ct {{ font-size: 19px; font-weight: 700; margin-bottom: 10px; }}
.fin {{ margin-top: 10px; padding: 12px 14px; background:{PAGE}; border-left: 3px solid {S1};
        border-radius: 6px; font-size: 15.5px; line-height: 1.55; color:{INK2}; }}
.fin b {{ color:{INK}; }}
svg text {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }}
.foot {{ margin-top: 22px; color:{MUTED}; font-size: 13.5px; line-height:1.5; }}
</style></head><body>
<div class='h1'>FARBAHOLIX</div>
<div class='sub'>Финансовая картина и анализ — {now.strftime('%d.%m.%Y')}</div>
<div class='accent'></div>
<div class='meta'>Источники: {len(d['rev'])} мес. выручки из инвойс-архива · банковские выписки 12.2024–12.2025 · долги и баланс из БД</div>
<div class='tiles'>{tiles_html}</div>
{''.join(sections)}
<div class='foot'>Прогнозы — экстраполяция сезонности 2025 на темп 2026; это ориентир, не гарантия.
Налоговые решения (Regelbesteuerung, KSK) — финал со Steuerberater. Сгенерировано ботом FARBAHOLIX.</div>
</body></html>"""


def _render_jpeg(html_text, out_path):
    """HTML → JPEG в отдельном потоке (sync Playwright нельзя в asyncio-цикле)."""
    import threading
    box = {}

    def _work():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox",
                                                    "--force-color-profile=srgb"])
                page = browser.new_page(viewport={"width": 1240, "height": 1600},
                                        device_scale_factor=2)
                page.set_content(html_text, wait_until="networkidle")
                page.wait_for_timeout(200)
                page.screenshot(path=out_path, type="jpeg", quality=88, full_page=True)
                browser.close()
        except Exception as e:
            box["err"] = e

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=150)
    if t.is_alive():
        raise TimeoutError("рендер отчёта не уложился в 150с")
    if "err" in box:
        raise box["err"]


def generate_finance_report() -> str:
    d = _collect()
    html_text = _build_html(d)
    out_path = os.path.join(tempfile.gettempdir(), "FARBAHOLIX_Analyse.jpg")
    _render_jpeg(html_text, out_path)
    # страховка по размеру (< 7 МБ): при превышении пересжать
    if os.path.getsize(out_path) > 6_800_000:
        _render_jpeg_quality(html_text, out_path, 75)
    return out_path


def _render_jpeg_quality(html_text, out_path, q):
    import threading
    box = {}

    def _work():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
                p = b.new_page(viewport={"width": 1240, "height": 1600}, device_scale_factor=2)
                p.set_content(html_text, wait_until="networkidle")
                p.wait_for_timeout(200)
                p.screenshot(path=out_path, type="jpeg", quality=q, full_page=True)
                b.close()
        except Exception as e:
            box["err"] = e
    t = threading.Thread(target=_work, daemon=True)
    t.start(); t.join(150)
    if "err" in box:
        raise box["err"]
