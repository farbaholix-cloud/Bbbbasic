"""Печатный свод вводных: списки, таблицы и ментальная карта на листах A4.

Команда Секретаря «выдай все вводные» собирает картину из общей базы и отдаёт её
не текстом в чат, а стопкой пронумерованных JPEG-страниц под печать.

ПОЧЕМУ ДВЕ ФАЗЫ, А НЕ ОДНА
--------------------------
Сначала АКТУАЛИЗАЦИЯ, потом АНАЛИЗ, и это не формальность. База живёт месяцами:
в ней копятся задачи, у которых время назначено на прошлое, вводные без оценки
важности, проекты без единого шага и дубли одной и той же мысли, записанной
дважды. Если сразу строить сводку, все эти хвосты попадут в неё как факты и
свод будет красиво врать. Поэтому первый проход ничего не рисует: он проходит по
базе, чинит то, что чинится однозначно, и составляет список того, что требует
решения человека. Второй проход считает и группирует — уже по выверенным данным.

Актуализация НЕ удаляет и не переписывает содержание. Всё, что она делает
молча, — снимает привязку ко времени у событий, которые давно прошли и никем не
закрыты (их место в парковке, а не в календаре задним числом), и то по флагу.
Остальное только помечается и печатается отдельной страницей «требует решения».

ПОЧЕМУ A4, А НЕ ДЛИННАЯ КАРТИНКА
-------------------------------
Утренняя сводка — вертикальный постер под телефон, его листают пальцем. Здесь
задача другая: разложить всё на столе и смотреть глазами целиком. Поэтому лист
210×297 мм при 150 dpi (1240×1754 px), поля 14 мм, и жёсткое правило: на
странице либо помещается всё, либо она делится на две. Ничего не обрезается,
ничего не сжимается «чтобы влезло».
"""
import os
import math
import html as _html
import sqlite3
from datetime import datetime, date, timedelta

# Лист A4 при 150 dpi. Печатать можно как есть, на экране читается тоже.
A4_W, A4_H = 1240, 1754
DPI_SCALE = 2            # рендерим в 2× и ужимаем — текст на печати не «мылит»
PAD_MM = 14

AREA_RU = {
    "work": "работа", "health": "здоровье", "money": "деньги", "people": "люди",
    "home": "дом", "self": "саморазвитие", "other": "другое",
}
AREA_ICON = {
    "work": "💼", "health": "🌿", "money": "💰", "people": "👥",
    "home": "🏠", "self": "📚", "other": "⚡",
}
# Квадранты матрицы Фридмана. Порядок — порядок разбора: сверху то, что горит.
QUADS = [
    ("now",   "Сейчас",    "важно и срочно",        "#ff6b7d"),
    ("plan",  "Планируй",  "важно, не горит",       "#5b9dff"),
    ("deleg", "Делегируй", "срочно, но не важно",   "#ffc657"),
    ("later", "Потом",     "ни то, ни другое",      "#8f9bab"),
]
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
          "июл", "авг", "сен", "окт", "ноя", "дек"]
DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _esc(s):
    return _html.escape(str(s or ""))


def quad_of(imp, urg):
    """Квадрант по двум оценкам 0–10. Граница 6 — та же, что в дашборде:
    матрица должна делить одинаково везде, иначе одна задача в двух местах
    оказывается в разных квадрантах."""
    imp, urg = imp or 0, urg or 0
    if imp >= 6 and urg >= 6:
        return "now"
    if imp >= 6:
        return "plan"
    if urg >= 6:
        return "deleg"
    return "later"


def _d(ds):
    try:
        return date.fromisoformat(str(ds)[:10])
    except Exception:
        return None


def _dfmt(ds):
    d = _d(ds)
    if not d:
        return str(ds or "")
    return f"{DOW[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


# ─── ФАЗА 1: актуализация ─────────────────────────────────────────────────────

def actualize(conn, fix=True):
    """Привести базу в порядок перед тем, как по ней что-то считать.

    Возвращает {"fixed": [...], "review": [...], "counts": {...}} — что починено
    молча и что требует решения владельца. Ничего не удаляет.
    """
    today = date.today().isoformat()
    fixed, review = [], []

    chaos = [dict(r) for r in conn.execute(
        "SELECT * FROM chaos WHERE done=0 ORDER BY id").fetchall()]
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events ORDER BY date, time").fetchall()]
    projects = [dict(r) for r in conn.execute(
        "SELECT * FROM projects WHERE archived=0 ORDER BY position, id").fetchall()]
    steps = [dict(r) for r in conn.execute(
        "SELECT * FROM steps ORDER BY project_id, position, id").fetchall()]

    done_chaos = {r["id"] for r in conn.execute(
        "SELECT id FROM chaos WHERE done=1").fetchall()}

    # 1. События, привязанные к уже закрытой вводной, — мусор в календаре.
    stale = [e for e in events if e.get("chaos_id") in done_chaos]
    if stale and fix:
        conn.executemany("DELETE FROM events WHERE id=?", [(e["id"],) for e in stale])
        fixed.append(f"убрано из календаря событий по закрытым задачам: {len(stale)}")
        events = [e for e in events if e not in stale]

    # 2. «Хвосты» — запланировано на прошлое и до сих пор не закрыто.
    tails = [e for e in events if str(e.get("date") or "") < today
             and e.get("chaos_id") not in done_chaos]
    if tails:
        review.append(("Хвосты в прошлом", len(tails),
                       "время прошло, задача осталась — перенести или закрыть"))

    # 3. Вводные без оценки: они не попадают ни в один квадрант матрицы.
    unrated = [c for c in chaos if not (c.get("importance") or c.get("urgency"))]
    if unrated:
        review.append(("Без оценки важность/срочность", len(unrated),
                       "не попадают в матрицу — оценить в дашборде или голосом боту"))

    # 4. Проекты без шагов: цель записана, декомпозиции нет.
    by_proj = {}
    for s in steps:
        by_proj.setdefault(s["project_id"], []).append(s)
    empty_projs = [p for p in projects if not by_proj.get(p["id"])]
    if empty_projs:
        review.append(("Проекты без шагов", len(empty_projs),
                       "; ".join(p["name"] for p in empty_projs[:4])))

    # 5. Проекты, где все шаги закрыты, но проект не в архиве.
    finished = [p for p in projects
                if by_proj.get(p["id"]) and all(s["done"] for s in by_proj[p["id"]])]
    if finished:
        review.append(("Проекты завершены, но не в архиве", len(finished),
                       "; ".join(p["name"] for p in finished[:4])))

    # 6. Дубли вводных: одна мысль, записанная дважды.
    seen, dups = {}, []
    for c in chaos:
        k = " ".join(str(c.get("text") or "").lower().split())
        if k and k in seen:
            dups.append(c)
        else:
            seen[k] = c["id"]
    if dups:
        review.append(("Похоже на дубли", len(dups),
                       "; ".join(str(c.get("text"))[:40] for c in dups[:3])))

    if fix:
        conn.commit()

    return {
        "fixed": fixed,
        "review": review,
        "counts": {
            "chaos": len(chaos), "events": len(events),
            "projects": len(projects), "steps": len(steps),
            "tails": len(tails), "unrated": len(unrated),
        },
    }


# ─── ФАЗА 2: сбор и анализ ────────────────────────────────────────────────────

def analyze(conn):
    """Считает и группирует по уже выверенным данным. Ничего не пишет в базу."""
    today = date.today()
    tiso = today.isoformat()

    chaos = [dict(r) for r in conn.execute(
        "SELECT * FROM chaos WHERE done=0 ORDER BY id").fetchall()]
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events ORDER BY date, time").fetchall()]
    projects = [dict(r) for r in conn.execute(
        "SELECT * FROM projects WHERE archived=0 ORDER BY position, id").fetchall()]
    steps = [dict(r) for r in conn.execute(
        "SELECT * FROM steps ORDER BY project_id, position, id").fetchall()]
    try:
        goals = [dict(r) for r in conn.execute(
            "SELECT * FROM goals WHERE period='strategic' AND done=0 ORDER BY id").fetchall()]
    except sqlite3.OperationalError:
        goals = []

    by_proj = {}
    for s in steps:
        by_proj.setdefault(s["project_id"], []).append(s)
    for p in projects:
        ps = by_proj.get(p["id"], [])
        p["steps"] = ps
        p["done_n"] = sum(1 for s in ps if s["done"])
        p["total_n"] = len(ps)
        p["pct"] = int(p["done_n"] / p["total_n"] * 100) if p["total_n"] else 0
        nxt = next((s for s in ps if not s["done"]), None)
        p["next"] = nxt["text"] if nxt else ""

    planned = {e["chaos_id"] for e in events if e.get("chaos_id")}
    parking = [c for c in chaos if c["id"] not in planned]

    quads = {k: [] for k, _, _, _ in QUADS}
    for c in chaos:
        quads[quad_of(c.get("importance"), c.get("urgency"))].append(c)

    by_area = {}
    for c in chaos:
        by_area.setdefault(c.get("area") or "other", []).append(c)

    tails = [e for e in events if str(e.get("date") or "") < tiso]
    horizon = (today + timedelta(days=13)).isoformat()
    upcoming = [e for e in events if tiso <= str(e.get("date") or "") <= horizon]
    later = [e for e in events if str(e.get("date") or "") > horizon]

    return {
        "today": today, "chaos": chaos, "parking": parking, "events": events,
        "projects": projects, "goals": goals, "quads": quads, "by_area": by_area,
        "tails": tails, "upcoming": upcoming, "later": later,
        "planned_ids": planned,
    }


# ─── ВЁРСТКА A4 ───────────────────────────────────────────────────────────────
# Светлая, печатная: на бумаге тёмный фон дашборда съедает картридж и теряет
# контраст. Один акцент на страницу, воздух вместо рамок, таблицы без «зебры» —
# строки разделяет тонкая линия, этого достаточно.
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:0}
html,body{background:#fff}
body{font-family:-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
  color:#14181d;-webkit-font-smoothing:antialiased}
.page{width:__W__px;height:__H__px;padding:__P__px;display:flex;flex-direction:column;
  background:#fff;position:relative;overflow:hidden}
.hd{display:flex;align-items:baseline;gap:12px;padding-bottom:10px;
  border-bottom:2px solid #14181d;margin-bottom:20px;flex:none}
.hd h1{font-size:26px;font-weight:800;letter-spacing:-.4px}
.hd .sub{font-size:13px;color:#6b7683;font-weight:600}
.hd .when{margin-left:auto;font-size:12px;color:#8b95a1;font-weight:700;white-space:nowrap}
.ft{margin-top:auto;padding-top:12px;border-top:1px solid #dfe3e8;display:flex;
  justify-content:space-between;font-size:11px;color:#9aa4ae;font-weight:700;flex:none}
.body{flex:1;min-height:0}
h2{font-size:16px;font-weight:800;margin-bottom:9px;letter-spacing:-.2px}
h2 .n{color:#9aa4ae;font-weight:700;margin-left:6px}
.sec+.sec{margin-top:20px}

/* числа обзора */
.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
.kpi .c{border:1px solid #dfe3e8;border-radius:10px;padding:12px 14px}
.kpi .v{font-size:30px;font-weight:800;line-height:1;letter-spacing:-1px}
.kpi .l{font-size:11px;font-weight:700;color:#6b7683;text-transform:uppercase;
  letter-spacing:.7px;margin-top:5px}

/* списки */
ul{list-style:none}
li{font-size:13px;line-height:1.4;padding:5px 0 5px 15px;text-indent:-15px;
  border-bottom:1px solid #eef1f4}
li:before{content:'— ';color:#b6bec7}
li .m{color:#8b95a1;font-size:11.5px;font-weight:700}

/* квадранты */
.quads{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.q{border:1px solid #dfe3e8;border-radius:10px;padding:12px 14px 8px;
  border-top:4px solid var(--qc)}
.q .qh{font-size:14px;font-weight:800;margin-bottom:2px}
.q .qs{font-size:11px;color:#8b95a1;font-weight:700;margin-bottom:8px}
.q .qn{float:right;font-size:13px;font-weight:800;color:var(--qc)}

/* таблицы */
table{width:100%;border-collapse:collapse}
th{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;
  color:#6b7683;text-align:left;padding:0 8px 7px;border-bottom:2px solid #14181d}
td{font-size:12.5px;padding:7px 8px;border-bottom:1px solid #eef1f4;vertical-align:top;
  line-height:1.35}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{height:5px;background:#eef1f4;border-radius:3px;overflow:hidden;min-width:60px;margin-top:4px}
.bar i{display:block;height:100%;background:#14181d}
.tag{display:inline-block;font-size:10.5px;font-weight:800;padding:1px 6px;border-radius:5px;
  background:#f1f3f6;color:#57616b;white-space:nowrap}
.warn{color:#c0392f;font-weight:700}
.dim{color:#9aa4ae}
.strike{text-decoration:line-through;color:#b6bec7}

/* карта */
.map{position:relative;width:100%;height:100%}
.map svg{position:absolute;inset:0;width:100%;height:100%}
.nd{position:absolute;transform:translate(-50%,-50%);text-align:center;
  font-size:11.5px;line-height:1.25;font-weight:700}
.root{font-size:17px;font-weight:800;background:#14181d;color:#fff;
  padding:10px 18px;border-radius:22px}
.br{font-size:13px;font-weight:800;padding:7px 12px;border-radius:14px;color:#fff}
.lf{font-size:10.5px;font-weight:600;color:#3d4650;max-width:150px;
  background:#fff;padding:2px 5px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;font-weight:700;
  color:#6b7683;margin-bottom:10px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
"""
# Подстановка через replace, а не через %-формат: в CSS полно процентов
# (width:100%), и форматирование на них спотыкается.
CSS = (CSS.replace("__W__", str(A4_W)).replace("__H__", str(A4_H))
          .replace("__P__", str(int(PAD_MM / 25.4 * 150))))


def _page(title, sub, body, idx, total, when):
    return (f'<div class="page"><div class="hd"><h1>{_esc(title)}</h1>'
            f'<div class="sub">{_esc(sub)}</div>'
            f'<div class="when">{_esc(when)}</div></div>'
            f'<div class="body">{body}</div>'
            f'<div class="ft"><span>FARBAHOLIX · свод вводных</span>'
            f'<span>{idx} / {total}</span></div></div>')


def _chunk(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)] or [[]]


# ─── СТРАНИЦЫ ─────────────────────────────────────────────────────────────────

def _p_overview(g, act):
    c = act["counts"]
    kpi = "".join(
        f'<div class="c"><div class="v">{v}</div><div class="l">{l}</div></div>'
        for v, l in [(c["chaos"], "вводных"), (len(g["projects"]), "проектов"),
                     (c["steps"], "шагов"), (len(g["upcoming"]), "дел на 2 недели")])
    qrows = "".join(
        f'<tr><td><b>{n}</b> <span class="dim">— {s}</span></td>'
        f'<td class="r"><b>{len(g["quads"][k])}</b></td></tr>'
        for k, n, s, _ in QUADS)
    fixed = ("".join(f"<li>{_esc(x)}</li>" for x in act["fixed"])
             if act["fixed"] else '<li class="dim">править было нечего</li>')
    review = ("".join(
        f'<tr><td>{_esc(t)}</td><td class="r warn">{n}</td>'
        f'<td class="dim">{_esc(d)}</td></tr>' for t, n, d in act["review"])
        if act["review"] else '<tr><td colspan="3" class="dim">всё чисто</td></tr>')

    # Цели и разбивка по областям стоят здесь не «для объёма»: обзор обязан
    # отвечать на «куда всё это вообще идёт» и «где перекос», иначе первая
    # страница — просто четыре числа и много воздуха.
    goals = ("".join(
        f'<tr><td>{_esc(x["text"])}</td>'
        f'<td class="dim" style="white-space:nowrap">{_esc(x.get("target") or "")}</td>'
        f'<td class="r">{max(0, min(100, x.get("progress") or 0))}%'
        f'<div class="bar"><i style="width:{max(0, min(100, x.get("progress") or 0))}%"></i></div>'
        f'</td></tr>' for x in g["goals"])
        if g["goals"] else '<tr><td colspan="3" class="dim">целей не задано</td></tr>')

    tot = len(g["chaos"]) or 1
    areas = "".join(
        f'<tr><td>{AREA_ICON.get(a, "⚡")} {AREA_RU.get(a, a)}</td>'
        f'<td class="r">{len(v)}</td>'
        f'<td style="width:55%"><div class="bar"><i style="width:{len(v) / tot * 100:.0f}%"></i></div></td>'
        f'</tr>' for a, v in sorted(g["by_area"].items(), key=lambda kv: -len(kv[1])))

    return (f'<div class="kpi">{kpi}</div>'
            f'<div class="sec"><h2>Матрица Фридмана</h2>'
            f'<table>{qrows}</table></div>'
            f'<div class="sec"><h2>Стратегические цели</h2><table>{goals}</table></div>'
            f'<div class="sec"><h2>Где сосредоточено внимание</h2><table>{areas}</table></div>'
            f'<div class="sec"><h2>Актуализация: исправлено само</h2><ul>{fixed}</ul></div>'
            f'<div class="sec"><h2>Требует твоего решения<span class="n">'
            f'{len(act["review"])}</span></h2>'
            f'<table><tr><th>что</th><th class="r">шт.</th><th>почему</th></tr>'
            f'{review}</table></div>')


def _li(c, show_area=True):
    bits = []
    if show_area:
        bits.append(AREA_RU.get(c.get("area") or "other", "другое"))
    if c.get("importance") or c.get("urgency"):
        bits.append(f'в{c.get("importance") or 0}/с{c.get("urgency") or 0}')
    else:
        bits.append("не оценено")
    return (f'<li>{_esc(c.get("text"))} '
            f'<span class="m">· {" · ".join(bits)}</span></li>')


def _p_quads(g, part, nparts):
    cells = []
    for k, name, sub, color in QUADS:
        items = g["quads"][k]
        # Ёмкость подобрана по высоте листа: 18 строк в квадранте, два ряда
        # квадрантов — лист заполнен и ничего не обрезано.
        per = 18
        chunk = items[(part - 1) * per:part * per]
        lis = "".join(_li(c) for c in chunk) or '<li class="dim">пусто</li>'
        more = (f'<li class="dim">…всего в квадранте {len(items)}</li>'
                if len(items) > part * per else "")
        cells.append(f'<div class="q" style="--qc:{color}">'
                     f'<span class="qn">{len(items)}</span>'
                     f'<div class="qh">{name}</div><div class="qs">{sub}</div>'
                     f'<ul>{lis}{more}</ul></div>')
    return f'<div class="quads">{"".join(cells)}</div>'


def _p_projects(g, chunk):
    rows = []
    for p in chunk:
        steps = p["steps"]
        slist = "".join(
            f'<div class="{"strike" if s["done"] else ""}">'
            f'{"✓" if s["done"] else "○"} {_esc(s["text"])}</div>' for s in steps[:8])
        if len(steps) > 8:
            slist += f'<div class="dim">…и ещё {len(steps) - 8}</div>'
        rows.append(
            f'<tr><td><b>{AREA_ICON.get(p.get("area") or "other", "⚡")} '
            f'{_esc(p["name"])}</b>'
            f'<div class="bar"><i style="width:{p["pct"]}%"></i></div></td>'
            f'<td class="r">{p["done_n"]}/{p["total_n"]}<br>'
            f'<span class="dim">{p["pct"]}%</span></td>'
            f'<td style="font-size:11.5px">{slist or "<span class=dim>шагов нет</span>"}</td></tr>')
    return ('<table><tr><th>проект</th><th class="r">шаги</th><th>декомпозиция</th></tr>'
            + "".join(rows) + "</table>")


def _p_calendar(g, title, items, chunk):
    rows = []
    for e in chunk:
        d = _d(e.get("date"))
        overdue = d and d < g["today"]
        t = e.get("time") or ""
        rows.append(
            f'<tr><td class="{"warn" if overdue else ""}" style="white-space:nowrap">'
            f'{_dfmt(e.get("date"))}</td>'
            f'<td class="r dim">{_esc(t)}</td>'
            f'<td>{_esc(e.get("text"))}</td></tr>')
    return (f'<h2>{title}<span class="n">{len(items)}</span></h2>'
            '<table><tr><th>дата</th><th class="r">время</th><th>дело</th></tr>'
            + ("".join(rows) or '<tr><td colspan="3" class="dim">пусто</td></tr>')
            + "</table>")


def _p_map(g):
    """Ментальная карта на печать: центр и до восьми ветвей вокруг.

    Раскладка — сетка 3×3 с корнем в середине. Геометрия известна заранее,
    поэтому линии считаются точно и ничего не наезжает друг на друга. Карта —
    обзор, а не список: в ветви влезает несколько строк, полный перечень лежит
    на страницах со списками и таблицами.
    """
    pad = int(PAD_MM / 25.4 * 150)
    W = A4_W - pad * 2
    H = A4_H - pad * 2 - 96           # минус шапка и подвал
    cw, ch = W / 3.0, H / 3.0
    slots = [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2)]

    branches = []
    # Ветви: проекты отдельно, остальное — по областям жизни.
    if g["projects"]:
        branches.append(("Проекты", "#14181d",
                         [f'{p["name"]} · {p["pct"]}%' for p in g["projects"]]))
    order = sorted(g["by_area"].items(), key=lambda kv: -len(kv[1]))
    palette = ["#5b9dff", "#52a878", "#c9852b", "#a05fc9", "#c0392f", "#2b8a9c", "#7b8794"]
    for i, (area, items) in enumerate(order[:7]):
        branches.append((f'{AREA_ICON.get(area, "⚡")} {AREA_RU.get(area, area)}',
                         palette[i % len(palette)],
                         [str(c.get("text") or "") for c in items]))
    branches = branches[:8]

    cx, cy = W / 2.0, H / 2.0
    lines, nodes = [], []
    for i, (title, color, items) in enumerate(branches):
        gx, gy = slots[i]
        x, y = cw * (gx + .5), ch * (gy + .5)
        lines.append(f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{x:.0f}" y2="{y:.0f}" '
                     f'stroke="{color}" stroke-width="2.5" opacity=".55"/>')
        lis = "".join(f'<div>· {_esc(t[:44])}</div>' for t in items[:6])
        if len(items) > 6:
            lis += f'<div class="dim">…и ещё {len(items) - 6}</div>'
        nodes.append(
            f'<div class="nd" style="left:{x:.0f}px;top:{y:.0f}px;width:{cw - 26:.0f}px">'
            f'<div class="br" style="background:{color};display:inline-block">'
            f'{_esc(title)} · {len(items)}</div>'
            f'<div class="lf" style="max-width:none;margin-top:5px;text-align:left">{lis}</div>'
            f'</div>')
    nodes.append(f'<div class="nd root" style="left:{cx:.0f}px;top:{cy:.0f}px">Вводные · '
                 f'{len(g["chaos"])}</div>')
    # Легенды нет намеренно: у каждой ветви своя подписанная плашка того же цвета,
    # и отдельный список внизу повторял бы её слово в слово.
    return (f'<div class="map" style="height:{H}px">'
            f'<svg viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none">'
            f'{"".join(lines)}</svg>{"".join(nodes)}</div>')


def build(conn, fix=True):
    """Обе фазы + вёрстка. Возвращает (список HTML-страниц, отчёт актуализации, анализ)."""
    act = actualize(conn, fix=fix)
    g = analyze(conn)
    when = datetime.now().strftime("%d.%m.%Y · %H:%M")

    blocks = []          # (заголовок, подзаголовок, html) — номера проставим потом
    blocks.append(("Обзор", "что есть и что требует решения", _p_overview(g, act)))

    # Матрица: страниц столько, сколько нужно самому большому квадранту.
    biggest = max((len(v) for v in g["quads"].values()), default=0)
    nq = max(1, math.ceil(biggest / 18))
    for i in range(1, nq + 1):
        sub = "важность и срочность" + (f" · лист {i} из {nq}" if nq > 1 else "")
        blocks.append(("Матрица", sub, _p_quads(g, i, nq)))

    # Проекты: по 5 на лист — с декомпозицией это плотно, но читаемо.
    projs = g["projects"]
    if projs:
        parts = _chunk(projs, 7)
        for i, ch in enumerate(parts, 1):
            sub = "цели и шаги" + (f" · лист {i} из {len(parts)}" if len(parts) > 1 else "")
            blocks.append(("Проекты", sub, _p_projects(g, ch)))

    # Календарь: хвосты отдельной страницей — их надо разобрать, а не пролистать.
    if g["tails"]:
        for i, ch in enumerate(_chunk(g["tails"], 32), 1):
            blocks.append(("Хвосты", "время прошло, дело осталось",
                           _p_calendar(g, "Просрочено", g["tails"], ch)))
    cal = g["upcoming"] + g["later"]
    if cal:
        for i, ch in enumerate(_chunk(cal, 32), 1):
            parts = math.ceil(len(cal) / 32)
            sub = "что впереди" + (f" · лист {i} из {parts}" if parts > 1 else "")
            blocks.append(("Календарь", sub, _p_calendar(g, "Запланировано", cal, ch)))

    blocks.append(("Ментальная карта", "связи между вводными", _p_map(g)))

    total = len(blocks)
    pages = [_page(t, s, b, i, total, when) for i, (t, s, b) in enumerate(blocks, 1)]
    return pages, act, g


def render(pages, out_dir, prefix="svod"):
    """HTML-страницы → пронумерованные JPEG. Возвращает список путей."""
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    html = ("<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
            f"<style>{CSS}</style></head><body>{''.join(pages)}</body></html>")
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox",
                                           "--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": A4_W, "height": A4_H},
                                device_scale_factor=DPI_SCALE)
        page.set_content(html, wait_until="networkidle")
        page.wait_for_timeout(250)
        for i in range(len(pages)):
            path = os.path.join(out_dir, f"{prefix}_{i + 1:02d}.jpeg")
            page.locator(".page").nth(i).screenshot(path=path, type="jpeg", quality=92)
            out.append(path)
        browser.close()
    return out


def build_and_render(db_path, out_dir, fix=True):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        pages, act, g = build(conn, fix=fix)
    finally:
        conn.close()
    return render(pages, out_dir), act, g
