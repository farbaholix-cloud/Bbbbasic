"""Свод: выгрузка ВСЕЙ базы на бумагу в удобном для чтения виде.

Страницы A4, пронумерованные, печатаются и раскладываются на столе.

ЧЕМ ЭТА ВЕРСИЯ ОТЛИЧАЕТСЯ ОТ ПЕРВОЙ
-----------------------------------
Первая версия была устроена по таблицам базы: лист «матрица», лист «проекты»,
лист «календарь». Это раскладка ХРАНЕНИЯ, а не раскладка мышления, и она отвечала
на вопрос «что лежит в таблице chaos», которого человек себе не задаёт. Плюс
половина листа оставалась пустой, потому что каждая таблица шла в одну колонку.

Теперь ось документа — вопрос, на который отвечает лист:

    Пульт      — в каком я состоянии прямо сейчас?
    Лента      — что и когда меня ждёт?
    Работа     — из чего состоят мои проекты?
    Внимание   — что я держу в голове и насколько это важно?
    Деньги     — кому я должен и что регулярно уходит?
    Люди       — кто есть кто и что по бюрократии?
    Карта      — как всё это связано?

Главная структурная перемена — ЛЕНТА. Раньше календарь и деньги жили на разных
листах, хотя вопрос у них один: что произойдёт 22 сентября. Теперь всё, у чего
есть дата, слито в одну хронологию — события, напоминания, регулярные платежи,
сроки долгов и бюрократических дел. Один поток, отсортированный по дате.

ПЛОТНОСТЬ
---------
Всё, что можно, идёт в две колонки, а разбивка на листы считается не «по N строк
на лист», а по ВЫСОТЕ: каждый блок объявляет, сколько строк он займёт, и
наполнение листа копится до ёмкости. Поэтому проект из двенадцати шагов и проект
из двух занимают столько места, сколько им нужно, и лист закрывается заполненным,
а не на пятом элементе, потому что «пять» было записано в константе.

ДВЕ ФАЗЫ
--------
Сначала АКТУАЛИЗАЦИЯ: проходит по базе, чинит однозначное и собирает список того,
что требует решения человека (хвосты в прошлом, вводные без оценки, проекты без
шагов, дубли). Только потом АНАЛИЗ считает и группирует. Порядок принципиален:
иначе накопившиеся хвосты попадут в свод как факты, и он будет красиво врать.
"""
import os
import math
import html as _html
import sqlite3
from datetime import datetime, date, timedelta

A4_W, A4_H = 1240, 1754
DPI_SCALE = 2
PAD_MM = 13
PAD = int(PAD_MM / 25.4 * 150)

# Ёмкость листа в «строках» — из неё считается разбивка. 17 px на строку при
# двух колонках: (1754 − поля − шапка − подвал) / 17 × 2, с запасом вниз.
BODY_H = A4_H - PAD * 2 - 86
LINES_PER_COL = int(BODY_H / 17.5)
CAP = LINES_PER_COL * 2

AREA_RU = {"work": "работа", "health": "здоровье", "money": "деньги",
           "people": "люди", "home": "дом", "self": "саморазвитие", "other": "другое"}
AREA_ICON = {"work": "💼", "health": "🌿", "money": "💰", "people": "👥",
             "home": "🏠", "self": "📚", "other": "⚡"}
QUADS = [("now", "Сейчас", "важно и срочно", "#d6455a"),
         ("plan", "Планируй", "важно, не горит", "#2f6fd0"),
         ("deleg", "Делегируй", "срочно, не важно", "#c2871b"),
         ("later", "Потом", "ни то, ни другое", "#79838f")]
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
          "июл", "авг", "сен", "окт", "ноя", "дек"]
DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _esc(s):
    return _html.escape(str(s or ""))


def quad_of(imp, urg):
    """Квадрант по двум оценкам. Граница 6 — та же, что в дашборде: матрица
    обязана делить одинаково везде, иначе одна задача попадёт в разные клетки."""
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
    return f"{d.day:02d}.{d.month:02d} {DOW[d.weekday()]}" if d else str(ds or "")


def _eur(v):
    try:
        return f"{v:,.0f} €".replace(",", " ")
    except Exception:
        return "—"


def _rows(conn, sql, args=()):
    """Запрос, переживающий отсутствие таблицы: база растёт со временем, и свод
    не должен падать целиком из-за одной ещё не созданной таблицы."""
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


# ─── ФАЗА 1: актуализация ─────────────────────────────────────────────────────

def actualize(conn, fix=True):
    """Привести базу в порядок до того, как по ней считать. Ничего не удаляет из
    содержания: чинит только очевидный мусор, остальное помечает."""
    today = date.today().isoformat()
    fixed, review = [], []

    chaos = _rows(conn, "SELECT * FROM chaos WHERE done=0 ORDER BY id")
    events = _rows(conn, "SELECT * FROM events ORDER BY date, time")
    projects = _rows(conn, "SELECT * FROM projects WHERE archived=0 ORDER BY position, id")
    steps = _rows(conn, "SELECT * FROM steps ORDER BY project_id, position, id")
    done_ids = {r["id"] for r in _rows(conn, "SELECT id FROM chaos WHERE done=1")}

    stale = [e for e in events if e.get("chaos_id") in done_ids]
    if stale and fix:
        conn.executemany("DELETE FROM events WHERE id=?", [(e["id"],) for e in stale])
        conn.commit()
        fixed.append(f"из календаря убрано событий по закрытым задачам: {len(stale)}")
        events = [e for e in events if e not in stale]

    tails = [e for e in events if str(e.get("date") or "") < today]
    if tails:
        review.append(("Хвосты в прошлом", len(tails), "перенести или закрыть"))
    unrated = [c for c in chaos if not (c.get("importance") or c.get("urgency"))]
    if unrated:
        review.append(("Без оценки важность/срочность", len(unrated),
                       "не попадают в матрицу"))

    by_proj = {}
    for s in steps:
        by_proj.setdefault(s["project_id"], []).append(s)
    empty = [p for p in projects if not by_proj.get(p["id"])]
    if empty:
        review.append(("Проекты без шагов", len(empty),
                       "; ".join(p["name"] for p in empty)))
    finished = [p for p in projects
                if by_proj.get(p["id"]) and all(s["done"] for s in by_proj[p["id"]])]
    if finished:
        review.append(("Завершены, но не в архиве", len(finished),
                       "; ".join(p["name"] for p in finished)))

    seen, dups = set(), []
    for c in chaos:
        k = " ".join(str(c.get("text") or "").lower().split())
        (dups.append(c) if k and k in seen else seen.add(k))
    if dups:
        review.append(("Похоже на дубли", len(dups),
                       "; ".join(str(c.get("text")) for c in dups)))

    return {"fixed": fixed, "review": review,
            "counts": {"chaos": len(chaos), "events": len(events),
                       "projects": len(projects), "steps": len(steps),
                       "tails": len(tails), "unrated": len(unrated)}}


# ─── ФАЗА 2: сбор и анализ ────────────────────────────────────────────────────

def _next_payment_date(p, today):
    """Ближайшая дата регулярного платежа. Для разовых — своя дата; для
    ежемесячных — ближайшее число: этого месяца, если ещё не прошло, иначе
    следующего. Без этого платежи не встали бы в ленту рядом с делами."""
    if p.get("date"):
        return _d(p["date"])
    day = int(p.get("day") or 0)
    if not day:
        return None
    y, m = today.year, today.month
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    try:
        cand = date(y, m, min(day, last))
    except ValueError:
        return None
    if cand < today:
        m, y = (1, y + 1) if m == 12 else (m + 1, y)
        last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        cand = date(y, m, min(day, last))
    return cand


def analyze(conn):
    """Собрать всё, что есть в базе, и разложить по смыслу. В базу не пишет."""
    today = date.today()
    tiso = today.isoformat()

    chaos = _rows(conn, "SELECT * FROM chaos WHERE done=0 ORDER BY id")
    events = _rows(conn, "SELECT * FROM events ORDER BY date, time")
    projects = _rows(conn, "SELECT * FROM projects WHERE archived=0 ORDER BY position, id")
    steps = _rows(conn, "SELECT * FROM steps ORDER BY project_id, position, id")
    goals = _rows(conn, "SELECT * FROM goals WHERE period='strategic' AND done=0 ORDER BY id")
    contacts = _rows(conn, "SELECT * FROM contacts ORDER BY name")
    debts = _rows(conn, "SELECT * FROM debts ORDER BY kind, due_date")
    payments = _rows(conn, "SELECT * FROM payments WHERE active=1 ORDER BY day")
    reminders = _rows(conn, "SELECT * FROM reminders WHERE sent=0 ORDER BY due_at")
    cases = _rows(conn, "SELECT * FROM bureau_cases WHERE status!='done' ORDER BY due_date")
    invoices = _rows(conn, "SELECT * FROM invoice_archive ORDER BY inv_date DESC")
    leads = _rows(conn, "SELECT * FROM leads ORDER BY updated_at DESC")
    fin = _rows(conn, "SELECT COALESCE(SUM(amount),0) t FROM finance")
    cash = _rows(conn, "SELECT COALESCE(SUM(amount),0) t FROM finance WHERE account='cash'")
    card = _rows(conn, "SELECT COALESCE(SUM(amount),0) t FROM finance WHERE account='card'")
    hap = _rows(conn, "SELECT * FROM happiness_log ORDER BY id DESC LIMIT 1")
    done_chaos = _rows(conn, "SELECT * FROM chaos WHERE done=1 ORDER BY id DESC")
    arch_projects = _rows(conn, "SELECT * FROM projects WHERE archived=1 ORDER BY archived_at DESC")
    done_cases = _rows(conn, "SELECT * FROM bureau_cases WHERE status='done' ORDER BY updated_at DESC")

    by_proj = {}
    for s in steps:
        by_proj.setdefault(s["project_id"], []).append(s)
    for p in projects:
        ps = by_proj.get(p["id"], [])
        p["steps"] = ps
        p["done_n"] = sum(1 for s in ps if s["done"])
        p["total_n"] = len(ps)
        p["pct"] = int(p["done_n"] / p["total_n"] * 100) if p["total_n"] else 0

    quads = {k: [] for k, _, _, _ in QUADS}
    for c in chaos:
        quads[quad_of(c.get("importance"), c.get("urgency"))].append(c)
    for k in quads:
        quads[k].sort(key=lambda c: -((c.get("importance") or 0) + (c.get("urgency") or 0)))

    by_area = {}
    for c in chaos:
        by_area.setdefault(c.get("area") or "other", []).append(c)

    # ЛЕНТА: всё, у чего есть дата, в одном потоке. Смысл в том, что вопрос
    # «что меня ждёт 22-го» не делится на календарный и денежный.
    line = []
    for e in events:
        d = _d(e.get("date"))
        if d:
            line.append({"d": d, "t": e.get("time") or "", "kind": "дело",
                         "text": e.get("text"), "sum": None})
    for r in reminders:
        d = _d(str(r.get("due_at"))[:10])
        if d:
            line.append({"d": d, "t": str(r.get("due_at"))[11:16], "kind": "напоминание",
                         "text": r.get("text"), "sum": None})
    for p in payments:
        d = _next_payment_date(p, today)
        if d:
            line.append({"d": d, "t": "", "kind": "платёж",
                         "text": (p.get("icon") or "") + " " + str(p.get("title") or ""),
                         "sum": -abs(p.get("amount") or 0)})
    for x in debts:
        d = _d(x.get("due_date"))
        if d:
            rest = max(0, (x.get("total") or 0) - (x.get("paid") or 0))
            line.append({"d": d, "t": "", "kind": "долг",
                         "text": x.get("name"), "sum": -rest})
    for c in cases:
        d = _d(c.get("due_date"))
        if d:
            line.append({"d": d, "t": "", "kind": "бюрократия",
                         "text": c.get("title") or c.get("topic"), "sum": None})
    line.sort(key=lambda x: (x["d"], x["t"] or "99:99"))

    return {"today": today, "chaos": chaos, "events": events, "projects": projects,
            "goals": goals, "quads": quads, "by_area": by_area, "contacts": contacts,
            "debts": debts, "payments": payments, "reminders": reminders,
            "cases": cases, "invoices": invoices, "leads": leads, "line": line,
            "past": [x for x in line if x["d"] < today],
            "future": [x for x in line if x["d"] >= today],
            "balance": fin[0]["t"] if fin else 0,
            "cash": cash[0]["t"] if cash else 0,
            "card": card[0]["t"] if card else 0,
            "happiness": hap[0] if hap else None,
            "done_chaos": done_chaos, "arch_projects": arch_projects,
            "done_cases": done_cases}


# ─── ВЁРСТКА ──────────────────────────────────────────────────────────────────
# Светлая и плотная. Тёмный фон дашборда на бумаге съедает картридж и теряет
# контраст, а воздух между строками на экране уместен, на листе — расточителен.
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:0}
html,body{background:#fff}
body{font-family:-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;color:#161a1f;
  -webkit-font-smoothing:antialiased}
.page{width:__W__px;height:__H__px;padding:__P__px;display:flex;flex-direction:column;
  background:#fff;overflow:hidden}
.hd{display:flex;align-items:baseline;gap:10px;padding-bottom:7px;
  border-bottom:2px solid #161a1f;margin-bottom:13px;flex:none}
.hd h1{font-size:21px;font-weight:800;letter-spacing:-.3px}
.hd .sub{font-size:11.5px;color:#6b7683;font-weight:600}
.hd .when{margin-left:auto;font-size:10.5px;color:#95a0ab;font-weight:700;white-space:nowrap}
.ft{margin-top:auto;padding-top:8px;border-top:1px solid #e3e7eb;display:flex;
  justify-content:space-between;font-size:10px;color:#a6b0ba;font-weight:700;flex:none}
.body{flex:1;min-height:0}
h2{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;
  color:#161a1f;margin:0 0 5px;padding-bottom:3px;border-bottom:1px solid #161a1f}
h2 .n{float:right;color:#95a0ab;font-weight:700}
h3{font-size:11.5px;font-weight:800;margin:0 0 2px}

/* две колонки — основной приём экономии места */
.c2{column-count:2;column-gap:20px;column-fill:auto;height:100%}
.one{max-width:__ONE__px}
.c2>*{break-inside:avoid}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px 20px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px 18px}
.blk{break-inside:avoid;margin-bottom:12px}

/* строки-списки */
.r{font-size:11px;line-height:1.3;padding:2.5px 0;border-bottom:1px solid #f0f2f5;
  display:flex;gap:6px;align-items:baseline}
.r .tx{flex:1;min-width:0}
.r .m{color:#98a2ac;font-size:9.5px;font-weight:700;white-space:nowrap}
.r .d{color:#6b7683;font-weight:700;font-size:10px;white-space:nowrap;min-width:52px}
.r .s{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
.r.hot .d{color:#d6455a}
.r.dn .tx{text-decoration:line-through;color:#b4bcc5}
.neg{color:#c0392f}
.pos{color:#1f7a4d}
.dim{color:#98a2ac}

/* числовые плитки */
.kpi{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:13px}
.kpi .c{border:1px solid #e3e7eb;border-radius:8px;padding:7px 9px}
.kpi .v{font-size:21px;font-weight:800;line-height:1;letter-spacing:-.6px}
.kpi .l{font-size:9px;font-weight:700;color:#6b7683;text-transform:uppercase;
  letter-spacing:.4px;margin-top:3px}

/* квадранты */
.q{border-top:3px solid var(--qc);padding-top:5px;break-inside:avoid;margin-bottom:11px}
.q .qh{font-size:11.5px;font-weight:800;display:flex;justify-content:space-between}
.q .qh b{color:var(--qc)}
.q .qs{font-size:9.5px;color:#98a2ac;font-weight:700;margin-bottom:3px}

/* прогресс */
.bar{height:3px;background:#eef1f4;border-radius:2px;overflow:hidden;margin-top:3px}
.bar i{display:block;height:100%;background:#161a1f}

/* карта */
.map{position:relative;width:100%}
.map svg{position:absolute;inset:0;width:100%;height:100%}
.nd{position:absolute;transform:translate(-50%,-50%);text-align:center}
.root{font-size:15px;font-weight:800;background:#161a1f;color:#fff;
  padding:8px 15px;border-radius:18px;display:inline-block}
.br{font-size:11px;font-weight:800;padding:4px 9px;border-radius:11px;color:#fff;
  display:inline-block;white-space:nowrap}
.lf{font-size:9.5px;font-weight:600;color:#454e58;text-align:left;margin-top:4px;
  line-height:1.32}
"""
CSS = (CSS.replace("__W__", str(A4_W)).replace("__H__", str(A4_H))
          .replace("__P__", str(PAD))
          .replace("__ONE__", str(int((A4_W - PAD * 2) * 0.62))))


SUBTITLES = {
    "Хвосты": "время прошло, дело осталось",
    "Лента": "дела, напоминания, платежи и сроки в одном потоке",
    "Работа": "проекты и шаги",
    "Внимание": "матрица важность/срочность",
    "Деньги": "долги, платежи, счета, лиды",
    "Люди и дела": "контакты и бюрократия",
    "Архив": "закрытое и заархивированное",
}


def _page(title, sub, body, idx, total, when):
    return (f'<div class="page"><div class="hd"><h1>{_esc(title)}</h1>'
            f'<div class="sub">{_esc(sub)}</div><div class="when">{_esc(when)}</div></div>'
            f'<div class="body">{body}</div>'
            f'<div class="ft"><span>FARBAHOLIX · свод базы</span>'
            f'<span>{idx} / {total}</span></div></div>')


def pack(blocks, cap=CAP):
    """Разложить блоки по листам по ВЫСОТЕ, а не по счёту, СКВОЗНЫМ потоком.

    blocks — [(строк, html, раздел)]. Два правила, и оба про экономию бумаги:

    1. Считаем высоту, а не элементы. Из-за счёта «N штук на лист» первая версия
       закрывала страницу на пятом проекте, оставляя две трети листа белыми.
    2. Раздел не требует собственного листа. Короткие «Деньги» и «Люди»
       доливаются на один лист друг за другом, и его заголовок перечисляет то,
       что на нём лежит. Раньше каждый раздел начинал новый лист — отсюда и
       бралась бумага, занятая на треть.
    """
    pages, cur, used, secs = [], [], 0, []
    for n, html, sec in blocks:
        if cur and used + n > cap:
            pages.append(("".join(cur), used, secs))
            cur, used, secs = [], 0, []
        cur.append(html)
        used += n
        if sec and sec not in secs:
            secs.append(sec)
    if cur:
        pages.append(("".join(cur), used, secs))
    return pages


def sheet_body(body, used):
    """Число колонок — от объёма, а не из константы.

    column-fill:auto заполняет первую колонку до низа и только потом берётся за
    вторую. Значит на коротком листе вся правая половина оставалась белой, и
    выглядело это поломкой, а не замыслом. Теперь: не набралось на полную
    колонку — верстаем в одну, во всю ширину; набралось — в две."""
    return f'<div class="{"c2" if used > LINES_PER_COL else "one"}">{body}</div>' 


# ─── СТРАНИЦЫ ─────────────────────────────────────────────────────────────────

def _row(d="", tx="", m="", s="", cls=""):
    return (f'<div class="r {cls}">'
            + (f'<span class="d">{_esc(d)}</span>' if d else "")
            + f'<span class="tx">{_esc(tx)}</span>'
            + (f'<span class="m">{_esc(m)}</span>' if m else "")
            + (f'<span class="s">{s}</span>' if s else "") + "</div>")


def p_pult(g, act, insight=""):
    """Пульт: всё состояние на одном листе. Отвечает на «где я сейчас»."""
    c = act["counts"]
    debts_rest = sum(max(0, (x.get("total") or 0) - (x.get("paid") or 0)) for x in g["debts"])
    pay_sum = sum(abs(x.get("amount") or 0) for x in g["payments"])
    kpi = [(c["chaos"], "вводных"), (len(g["projects"]), "проектов"),
           (c["steps"], "шагов"), (len(g["future"]), "впереди"),
           (_eur(g["balance"]), "баланс"), (_eur(debts_rest), "долги")]
    kpi_html = "".join(f'<div class="c"><div class="v">{v}</div><div class="l">{l}</div></div>'
                       for v, l in kpi)

    qmax = max((len(v) for v in g["quads"].values()), default=0) or 1
    quads = "".join(
        f'<div class="q" style="--qc:{col}"><div class="qh">{nm}<b>{len(g["quads"][k])}</b></div>'
        f'<div class="qs">{sub}</div>'
        f'<div class="bar"><i style="width:{len(g["quads"][k]) / qmax * 100:.0f}%;'
        f'background:{col}"></i></div></div>'
        for k, nm, sub, col in QUADS)

    tot = len(g["chaos"]) or 1
    areas = "".join(
        f'<div class="r"><span class="tx">{AREA_ICON.get(a, "⚡")} {AREA_RU.get(a, a)}</span>'
        f'<span class="m">{len(v)}</span></div>'
        f'<div class="bar"><i style="width:{len(v) / tot * 100:.0f}%"></i></div>'
        for a, v in sorted(g["by_area"].items(), key=lambda kv: -len(kv[1]))[:7])

    goals = "".join(
        f'<div class="r"><span class="tx">{_esc(x["text"])}</span>'
        f'<span class="m">{max(0, min(100, x.get("progress") or 0))}%</span></div>'
        f'<div class="bar"><i style="width:{max(0, min(100, x.get("progress") or 0))}%"></i></div>'
        for x in g["goals"]) or '<div class="r dim"><span class="tx">целей не задано</span></div>'

    fixed = "".join(_row(tx=x) for x in act["fixed"]) or \
        '<div class="r dim"><span class="tx">править было нечего</span></div>'
    review = "".join(
        f'<div class="r"><span class="tx">{_esc(t)}</span>'
        f'<span class="m neg">{n}</span></div>'
        f'<div class="r dim" style="padding-top:0"><span class="tx">{_esc(dsc)}</span></div>'
        for t, n, dsc in act["review"]) or \
        '<div class="r dim"><span class="tx">всё чисто</span></div>'

    ins = (f'<div class="blk"><h2>Что бросается в глаза</h2>'
           f'<div style="font-size:11px;line-height:1.4">{_esc(insight)}</div></div>'
           if insight else "")

    next7 = [x for x in g["future"] if (x["d"] - g["today"]).days <= 7][:12]
    soon = "".join(
        _row(d=_dfmt(x["d"].isoformat()), tx=x["text"], m=x["kind"],
             s=(f'<span class="neg">{_eur(x["sum"])}</span>' if x["sum"] else ""))
        for x in next7) or '<div class="r dim"><span class="tx">на неделе пусто</span></div>'

    return (f'<div class="kpi">{kpi_html}</div>'
            f'<div class="g3">'
            f'<div><div class="blk"><h2>Внимание</h2>{quads}</div></div>'
            f'<div><div class="blk"><h2>Ближайшие 7 дней</h2>{soon}</div>'
            f'<div class="blk"><h2>Цели</h2>{goals}</div></div>'
            f'<div><div class="blk"><h2>Перекос по областям</h2>{areas}</div>'
            f'<div class="blk"><h2>Деньги</h2>'
            f'{_row(tx="наличные", s=_eur(g["cash"]))}{_row(tx="карта", s=_eur(g["card"]))}'
            f'{_row(tx="долги, остаток", s=f"<span class=neg>{_eur(debts_rest)}</span>")}'
            f'{_row(tx="регулярно в месяц", s=f"<span class=neg>{_eur(pay_sum)}</span>")}</div>'
            f'<div class="blk"><h2>Актуализация</h2>{fixed}</div>'
            f'<div class="blk"><h2>Требует решения</h2>{review}</div>'
            f'{ins}</div></div>')


def b_line(items, sec, today, past=False):
    """Блоки ленты, сгруппированные по месяцам: дата сама по себе плохо читается
    списком в двести строк, а месяц — естественная единица планирования."""
    blocks, cur_m, rows = [], None, []
    for x in items:
        m = (x["d"].year, x["d"].month)
        if m != cur_m:
            if rows:
                blocks.append((len(rows) + 2, f'<div class="blk"><h2>{cur_t}</h2>{"".join(rows)}</div>', sec))
            cur_m, rows = m, []
            cur_t = f"{MONTHS[m[1] - 1]} {m[0]}" + (" · прошло" if past else "")
        hot = x["d"] < today
        rows.append(_row(d=_dfmt(x["d"].isoformat()) + (" " + x["t"] if x["t"] else ""),
                         tx=x["text"], m=x["kind"],
                         s=(f'<span class="neg">{_eur(x["sum"])}</span>' if x["sum"] else ""),
                         cls="hot" if hot else ""))
    if rows:
        blocks.append((len(rows) + 2, f'<div class="blk"><h2>{cur_t}</h2>{"".join(rows)}</div>', sec))
    return blocks


def b_projects(g):
    blocks = []
    for p in g["projects"]:
        steps = "".join(
            _row(tx=("✓ " if s["done"] else "○ ") + str(s["text"]),
                 cls="dn" if s["done"] else "") for s in p["steps"])
        head = (f'<h3>{AREA_ICON.get(p.get("area") or "other", "⚡")} {_esc(p["name"])}'
                f'<span class="m" style="float:right">{p["done_n"]}/{p["total_n"]} · {p["pct"]}%</span></h3>'
                f'<div class="bar" style="margin-bottom:3px"><i style="width:{p["pct"]}%"></i></div>')
        blocks.append((len(p["steps"]) + 3,
                       f'<div class="blk">{head}{steps or chr(60) + "div class=r dim" + chr(62) + chr(60) + "span class=tx" + chr(62) + "шагов нет</span></div>"}</div>', 'Работа'))
    return blocks


def b_quads(g):
    blocks = []
    for k, nm, sub, col in QUADS:
        items = g["quads"][k]
        rows = "".join(_row(tx=x.get("text"),
                            m=f'{AREA_RU.get(x.get("area") or "other", "")} · '
                              f'в{x.get("importance") or 0}/с{x.get("urgency") or 0}')
                       for x in items)
        blocks.append((len(items) + 3,
                       f'<div class="q" style="--qc:{col}">'
                       f'<div class="qh">{nm}<b>{len(items)}</b></div>'
                       f'<div class="qs">{sub}</div>{rows}</div>', 'Внимание'))
    return blocks


def b_money(g):
    blocks = []
    d_rows = "".join(
        _row(tx=(x.get("icon") or "") + " " + str(x.get("name") or ""),
             m=(("долгосрочный" if x.get("kind") == "long" else "текущий")
                + (f' · {_eur(x["monthly"])}/мес' if x.get("monthly") else "")),
             s=f'<span class="neg">{_eur(max(0, (x.get("total") or 0) - (x.get("paid") or 0)))}</span>')
        for x in g["debts"])
    if g["debts"]:
        blocks.append((len(g["debts"]) + 2, f'<div class="blk"><h2>Долги</h2>{d_rows}</div>', 'Деньги'))
    p_rows = "".join(
        _row(tx=(x.get("icon") or "") + " " + str(x.get("title") or ""),
             m=(f'{x["day"]} числа' if x.get("day") else (x.get("date") or "")),
             s=f'<span class="neg">{_eur(abs(x.get("amount") or 0))}</span>')
        for x in g["payments"])
    if g["payments"]:
        blocks.append((len(g["payments"]) + 2,
                       f'<div class="blk"><h2>Регулярные платежи</h2>{p_rows}</div>', 'Деньги'))
    i_rows = "".join(
        _row(d=str(x.get("inv_date") or "")[:10], tx=x.get("client_name"),
             m=("оплачен" if x.get("paid") else "ждёт"),
             s=_eur(x.get("gross") or 0)) for x in g["invoices"])
    if g["invoices"]:
        blocks.append((len(g["invoices"]) + 2,
                       f'<div class="blk"><h2>Счета · последние</h2>{i_rows}</div>', 'Деньги'))
    l_rows = "".join(
        _row(tx=x.get("name"), m=f'{x.get("stage") or ""} · {x.get("city") or ""}',
             s=_eur(x.get("budget_est") or 0) if x.get("budget_est") else "")
        for x in g["leads"])
    if g["leads"]:
        blocks.append((len(g["leads"]) + 2, f'<div class="blk"><h2>Лиды в работе</h2>{l_rows}</div>', 'Деньги'))
    return blocks


def b_people(g):
    blocks = []
    rows = "".join(_row(tx=x.get("name"), m=str(x.get("note") or ""))
                   for x in g["contacts"])
    if g["contacts"]:
        blocks.append((len(g["contacts"]) + 2, f'<div class="blk"><h2>Люди</h2>{rows}</div>', 'Люди и дела'))
    c_rows = "".join(
        _row(d=str(x.get("due_date") or "")[:10], tx=x.get("title") or x.get("topic"),
             m=f'{x.get("status")} · {x.get("next_step") or ""}')
        for x in g["cases"])
    if g["cases"]:
        blocks.append((len(g["cases"]) + 2,
                       f'<div class="blk"><h2>Бюрократические дела</h2>{c_rows}</div>', 'Люди и дела'))
    return blocks


def b_archive(g):
    """Закрытое и заархивированное. Это тоже информация: «выгрузка» без архива —
    выгрузка половины. Место ей в конце, чтобы не мешать живому."""
    blocks = []
    if g["done_chaos"]:
        rows = "".join(_row(tx=x.get("text"),
                            m=AREA_RU.get(x.get("area") or "other", ""), cls="dn")
                       for x in g["done_chaos"])
        blocks.append((len(g["done_chaos"]) + 2,
                       f'<div class="blk"><h2>Закрытые вводные'
                       f'<span class="n">{len(g["done_chaos"])}</span></h2>{rows}</div>', 'Архив'))
    if g["arch_projects"]:
        rows = "".join(_row(d=str(x.get("archived_at") or "")[:10], tx=x.get("name"), cls="dn")
                       for x in g["arch_projects"])
        blocks.append((len(g["arch_projects"]) + 2,
                       f'<div class="blk"><h2>Архив проектов'
                       f'<span class="n">{len(g["arch_projects"])}</span></h2>{rows}</div>', 'Архив'))
    if g["done_cases"]:
        rows = "".join(_row(tx=x.get("title") or x.get("topic"), m="закрыто", cls="dn")
                       for x in g["done_cases"])
        blocks.append((len(g["done_cases"]) + 2,
                       f'<div class="blk"><h2>Закрытые дела'
                       f'<span class="n">{len(g["done_cases"])}</span></h2>{rows}</div>', 'Архив'))
    return blocks


def p_map(g):
    """Карта: центр и до восьми ветвей по сетке 3×3. Геометрия известна заранее,
    поэтому линии считаются точно и ничего не наезжает."""
    W = A4_W - PAD * 2
    H = BODY_H
    cw, ch = W / 3.0, H / 3.0
    slots = [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2)]
    palette = ["#2f6fd0", "#1f7a4d", "#c2871b", "#8b4fc9", "#c0392f", "#27808f", "#6b7683"]

    branches = []
    if g["projects"]:
        branches.append(("Проекты", "#161a1f",
                         [f'{p["name"]} · {p["pct"]}%' for p in g["projects"]]))
    for i, (a, items) in enumerate(sorted(g["by_area"].items(), key=lambda kv: -len(kv[1]))[:7]):
        branches.append((f'{AREA_ICON.get(a, "⚡")} {AREA_RU.get(a, a)}',
                         palette[i % len(palette)],
                         [str(c.get("text") or "") for c in items]))
    branches = branches[:8]

    cx, cy = W / 2.0, H / 2.0
    lines, nodes = [], []
    for i, (title, color, items) in enumerate(branches):
        gx, gy = slots[i]
        x, y = cw * (gx + .5), ch * (gy + .5)
        lines.append(f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{x:.0f}" y2="{y:.0f}" '
                     f'stroke="{color}" stroke-width="2" opacity=".5"/>')
        lis = "".join(f'<div>· {_esc(t)}</div>' for t in items)
        wide = ' style="column-count:2;column-gap:10px"' if len(items) > 8 else ""
        nodes.append(
            f'<div class="nd" style="left:{x:.0f}px;top:{y:.0f}px;width:{cw - 22:.0f}px">'
            f'<div class="br" style="background:{color}">{_esc(title)} · {len(items)}</div>'
            f'<div class="lf"{wide}>{lis}</div></div>')
    nodes.append(f'<div class="nd" style="left:{cx:.0f}px;top:{cy:.0f}px">'
                 f'<div class="root">Вводные · {len(g["chaos"])}</div></div>')
    return (f'<div class="map" style="height:{H}px">'
            f'<svg viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none">'
            f'{"".join(lines)}</svg>{"".join(nodes)}</div>')


def _insight_sync(g, act):
    """Один абзац «что бросается в глаза» — единственное место свода, где нужна
    модель: всё остальное считается кодом и в интерпретации не нуждается.

    Модель здесь СИЛЬНЕЕ дежурной: разглядеть перекос и противоречие в срезе
    базы — задача на рассуждение, а не на пересказ, и haiku на ней заметно
    беднее. Сводка от этого не задерживается: абзац строится один раз на свод.
    Цифр модель не считает — они уже посчитаны и переданы готовыми.
    """
    try:
        import subprocess
        cli = os.path.expanduser("~/.local/bin/claude")
        if not os.path.exists(cli):
            return ""
        quad_n = {k: len(v) for k, v in g["quads"].items()}
        stats = (
            f'вводных {len(g["chaos"])}; по квадрантам: сейчас {quad_n["now"]}, '
            f'планируй {quad_n["plan"]}, делегируй {quad_n["deleg"]}, потом {quad_n["later"]}; '
            f'проектов {len(g["projects"])}, из них без шагов '
            f'{sum(1 for p in g["projects"] if not p["total_n"])}; '
            f'шагов всего {sum(p["total_n"] for p in g["projects"])}, закрыто '
            f'{sum(p["done_n"] for p in g["projects"])}; '
            f'по областям: ' + ", ".join(f'{AREA_RU.get(a, a)} {len(v)}'
                                         for a, v in sorted(g["by_area"].items(), key=lambda kv: -len(kv[1]))) + "; "
            f'хвостов в прошлом {len(g["past"])}; впереди дел {len(g["future"])}; '
            f'баланс {g["balance"]:.0f} €, долгов остаток '
            f'{sum(max(0, (x.get("total") or 0) - (x.get("paid") or 0)) for x in g["debts"]):.0f} €, '
            f'регулярных платежей {len(g["payments"])} на '
            f'{sum(abs(x.get("amount") or 0) for x in g["payments"]):.0f} € в месяц; '
            f'требует решения: ' + ("; ".join(f"{t} — {n}" for t, n, _ in act["review"]) or "нечего")
        )
        prompt = (
            "Ниже срез базы личного планирования художника-фрилансера. Цифры уже посчитаны — "
            "НЕ пересчитывай и не повторяй их подряд списком.\n\n" + stats + "\n\n"
            "Напиши 3–4 коротких предложения по-русски: что в этой картине бросается в глаза. "
            "Ищи перекосы и противоречия — квадрант, который переполнен; область жизни, из которой "
            "всё вымылось; проекты без движения; расходы против остатка; хвосты, которых слишком "
            "много. Пиши как человек, который смотрит на разложенные листы, а не как отчёт. "
            "Без вступлений, без «рекомендую», без списка. Только наблюдения, каждое с опорой "
            "на конкретное число из среза. Если картина ровная — так и скажи одним предложением."
        )
        r = subprocess.run([cli, "-p", "--model", "sonnet", "--tools", ""],
                           input=prompt, capture_output=True, text=True, timeout=120)
        out = (r.stdout or "").strip()
        return "" if out.startswith("Error:") else out[:700]
    except Exception:
        return ""


def build(conn, fix=True, insight=True):
    """Обе фазы + вёрстка. Возвращает (страницы, отчёт актуализации, анализ)."""
    act = actualize(conn, fix=fix)
    g = analyze(conn)
    when = datetime.now().strftime("%d.%m.%Y · %H:%M")
    note = _insight_sync(g, act) if insight else ""

    # Всё содержимое — один сквозной поток блоков. Разделы не требуют
    # собственных листов: короткие «Деньги» и «Люди» лягут на один, и его
    # заголовок перечислит оба. Отдельные листы только у Пульта (своя раскладка
    # в три колонки) и у Карты (своя геометрия).
    flow = []
    flow += b_line(g["past"], "Хвосты", g["today"], past=True)
    flow += b_line(g["future"], "Лента", g["today"])
    flow += b_projects(g)
    flow += b_quads(g)
    flow += b_money(g)
    flow += b_people(g)
    flow += b_archive(g)

    sheets = [("Пульт", "состояние на сегодня", p_pult(g, act, note))]
    for body, used, secs in pack(flow):
        # До трёх разделов перечисляем в заголовке — это подсказка, что на листе.
        # Больше трёх перечислять бессмысленно: строка длиннее самого заголовка
        # и читается хуже, чем честное «Свод» с расшифровкой в подзаголовке.
        if len(secs) <= 3:
            title = " · ".join(secs) or "Свод"
            sub = SUBTITLES.get(secs[0], "") if len(secs) == 1 else ""
        else:
            title, sub = "Свод", ", ".join(s.lower() for s in secs)
        sheets.append((title, sub, sheet_body(body, used)))
    sheets.append(("Карта", "как всё связано", p_map(g)))

    total = len(sheets)
    pages = [_page(t, s, b, i, total, when) for i, (t, s, b) in enumerate(sheets, 1)]
    return pages, act, g


def render(pages, out_dir, prefix="svod"):
    """HTML-страницы → пронумерованные JPEG."""
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.startswith(prefix) and old.endswith(".jpeg"):
            try:
                os.remove(os.path.join(out_dir, old))
            except Exception:
                pass
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
            page.locator(".page").nth(i).screenshot(path=path, type="jpeg", quality=90)
            out.append(path)
        browser.close()
    return out


def build_and_render(db_path, out_dir, fix=True, insight=True):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        pages, act, g = build(conn, fix=fix, insight=insight)
    finally:
        conn.close()
    return render(pages, out_dir), act, g
