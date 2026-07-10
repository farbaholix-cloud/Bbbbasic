import json
import sqlite3
import os
import math
import time
import secrets
import calendar
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from wisdom import today_wisdom

DB = os.path.join(os.path.dirname(__file__), "friedman.db")
PORT = 8765
VERSION = "1.15"  # видимая метка сборки — меняется с каждым деплоем


@contextmanager
def db():
    # Контекст-менеджер: коммитит при успехе, откатывает при ошибке и ВСЕГДА закрывает
    # соединение. Раньше соединения не закрывались — на каждый HTTP-запрос утекал
    # дескриптор, сервер постепенно тормозил (это и спровоцировало гонку с оптимизмом).
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_session_token():
    """Стабильный токен сессии (переживает рестарт), хранится в settings."""
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM settings WHERE key='dash_token'").fetchone()
        if row and row["value"]:
            return row["value"]
        tok = secrets.token_urlsafe(24)
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dash_token', ?)", (tok,))
        return tok


SESSION_TOKEN = get_session_token()

# Авто-блокировка по бездействию: пока дашборд открыт, он пингует сервер (polling +
# keepalive). Свернул/закрыл приложение → visibilitychange шлёт /api/lock и гасит сессию
# сразу. IDLE_TIMEOUT — это лишь страховка: держим его щедрым, чтобы длинные диалоги
# (ввод карточки, крутилки) не роняли сессию посреди действия.
IDLE_TIMEOUT = 900
_last_seen = 0.0


def is_circle(points):
    """Похож ли нарисованный штрих на круг: замкнутость + ровный радиус + ~полный оборот."""
    try:
        pts = [(float(p[0]), float(p[1])) for p in points]
    except (TypeError, ValueError, IndexError):
        return False
    if len(pts) < 10:
        return False
    cx = sum(x for x, _ in pts) / len(pts)
    cy = sum(y for _, y in pts) / len(pts)
    radii = [math.hypot(x - cx, y - cy) for x, y in pts]
    r = sum(radii) / len(radii)
    if r < 22:  # слишком маленький — скорее точка/каракуля
        return False
    std = (sum((ri - r) ** 2 for ri in radii) / len(radii)) ** 0.5
    if std / r > 0.48:  # радиус скачет — не круг (терпимее к овалам/дрожи)
        return False
    winding = 0.0
    for i in range(1, len(pts)):
        a0 = math.atan2(pts[i - 1][1] - cy, pts[i - 1][0] - cx)
        a1 = math.atan2(pts[i][1] - cy, pts[i][0] - cx)
        d = a1 - a0
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        winding += d
    if abs(winding) < 1.3 * math.pi:  # хватает ~235° оборота (не нужен идеально полный круг)
        return False
    sx, sy = pts[0]
    ex, ey = pts[-1]
    if math.hypot(ex - sx, ey - sy) > r * 1.6:  # концы не слишком далеко — примерно замкнуто
        return False
    return True


def ensure_schema(conn):
    """Idempotent migrations so the dashboard never crashes on an old DB."""
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT, date TEXT, time TEXT, chaos_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        kind TEXT DEFAULT 'current',
        total REAL DEFAULT 0,
        paid REAL DEFAULT 0,
        due_date TEXT,
        monthly REAL DEFAULT 0,
        icon TEXT DEFAULT '💳',
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount REAL NOT NULL,
        account TEXT DEFAULT 'card',
        kind TEXT DEFAULT 'recurring',
        recur TEXT DEFAULT 'monthly',
        day INTEGER DEFAULT 1,
        date TEXT,
        icon TEXT DEFAULT '💸',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    # chaos importance/urgency for the Eisenhower matrix (1..10)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chaos)").fetchall()]
    if cols:
        if "importance" not in cols:
            conn.execute("ALTER TABLE chaos ADD COLUMN importance INTEGER DEFAULT 0")
        if "urgency" not in cols:
            conn.execute("ALTER TABLE chaos ADD COLUMN urgency INTEGER DEFAULT 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS kanban_columns (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, color TEXT DEFAULT '#5b9dff',
      position INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
      status TEXT DEFAULT 'prospective', deadline TEXT
    )""")
    kcols = [r[1] for r in conn.execute("PRAGMA table_info(kanban_columns)").fetchall()]
    if 'status' not in kcols:
        conn.execute("ALTER TABLE kanban_columns ADD COLUMN status TEXT DEFAULT 'prospective'")
    if 'deadline' not in kcols:
        conn.execute("ALTER TABLE kanban_columns ADD COLUMN deadline TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS kanban_cards (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      column_id INTEGER, project_id INTEGER, chaos_id INTEGER,
      title TEXT NOT NULL, description TEXT,
      checked INTEGER DEFAULT 0, position INTEGER DEFAULT 0,
      color TEXT, archived INTEGER DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, archived_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS project_meta (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, color TEXT DEFAULT '#5b9dff',
      status TEXT DEFAULT 'current', archived INTEGER DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS happiness_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      work INTEGER DEFAULT 5, friendship INTEGER DEFAULT 5,
      health INTEGER DEFAULT 5, wellbeing INTEGER DEFAULT 5,
      hobby INTEGER DEFAULT 5, love INTEGER DEFAULT 5,
      note TEXT, logged_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # events: project link + morning brief flag + priority + comment
    ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    if ev_cols:
        if "project_id" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN project_id INTEGER")
        if "morning_brief" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN morning_brief INTEGER DEFAULT 0")
        if "importance" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN importance INTEGER DEFAULT 0")
        if "urgency" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN urgency INTEGER DEFAULT 0")
        if "comment" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
        if "time_end" not in ev_cols:
            conn.execute("ALTER TABLE events ADD COLUMN time_end TEXT")
    # steps: drag position + project move + comment
    st_cols = [r[1] for r in conn.execute("PRAGMA table_info(steps)").fetchall()]
    if st_cols:
        if "position" not in st_cols:
            conn.execute("ALTER TABLE steps ADD COLUMN position INTEGER DEFAULT 0")
        if "comment" not in st_cols:
            conn.execute("ALTER TABLE steps ADD COLUMN comment TEXT")
    # chaos: project link + drag position + comment
    ch_cols = [r[1] for r in conn.execute("PRAGMA table_info(chaos)").fetchall()]
    if ch_cols:
        if "project_id" not in ch_cols:
            conn.execute("ALTER TABLE chaos ADD COLUMN project_id INTEGER")
        if "position" not in ch_cols:
            conn.execute("ALTER TABLE chaos ADD COLUMN position INTEGER DEFAULT 0")
        if "comment" not in ch_cols:
            conn.execute("ALTER TABLE chaos ADD COLUMN comment TEXT")
    # kanban cards: comment
    kc_cols = [r[1] for r in conn.execute("PRAGMA table_info(kanban_cards)").fetchall()]
    if kc_cols and "comment" not in kc_cols:
        conn.execute("ALTER TABLE kanban_cards ADD COLUMN comment TEXT")
    # goals: стратегические цели на «Мостике» — ручной прогресс + горизонт
    conn.execute("""CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL, area TEXT DEFAULT 'work', period TEXT DEFAULT 'week',
        done INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    g_cols = [r[1] for r in conn.execute("PRAGMA table_info(goals)").fetchall()]
    if "progress" not in g_cols:
        conn.execute("ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0")
    if "target" not in g_cols:
        conn.execute("ALTER TABLE goals ADD COLUMN target TEXT")
    # projects: morning brief flag
    pr_cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    if pr_cols:
        if "morning_brief" not in pr_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN morning_brief INTEGER DEFAULT 0")
        if "archived" not in pr_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN archived INTEGER DEFAULT 0")
        if "archived_at" not in pr_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN archived_at TEXT")
    if not conn.execute("SELECT 1 FROM kanban_columns LIMIT 1").fetchone():
        conn.executemany("INSERT INTO kanban_columns(name,color,position) VALUES(?,?,?)", [
            ("Идеи","#5b9dff",0),("В работе","#ff9aa6",1),
            ("На паузе","#ffd07a",2),("Готово","#52e08a",3)])


# Миграции один раз при старте (ensure_schema идемпотентна). Раньше этот вызов стоял
# ВЫШЕ определения функции и тихо падал с NameError — из-за чего новые колонки (position,
# archived) появлялись только после первой операции с долгами. Теперь — гарантированно.
try:
    with db() as _conn:
        ensure_schema(_conn)
except Exception:
    pass


# ─── planned spend from recurring + planned payments + current debts ──────────

def _month_iter(d0, d1):
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def payment_occurrences(p, d0, d1):
    """All dates in [d0,d1] when payment p is due."""
    out = []
    if p["kind"] == "planned" and p["date"]:
        try:
            dt = datetime.strptime(p["date"][:10], "%Y-%m-%d").date()
            if d0 <= dt <= d1:
                out.append(dt)
        except ValueError:
            pass
        return out
    recur = (p["recur"] or "monthly")
    day = p["day"] or 1
    if recur == "monthly":
        for y, m in _month_iter(d0, d1):
            last = calendar.monthrange(y, m)[1]
            dd = min(day, last)
            dt = date(y, m, dd)
            if d0 <= dt <= d1:
                out.append(dt)
    elif recur == "weekly":
        cur = d0
        while cur <= d1:
            if cur.weekday() == (day % 7):
                out.append(cur)
            cur += timedelta(days=1)
    return out


def planned_spend(conn, d0, d1):
    """Returns list of {date,title,amount,icon} due in [d0,d1], sorted."""
    items = []
    for p in conn.execute("SELECT * FROM payments WHERE active=1").fetchall():
        for dt in payment_occurrences(p, d0, d1):
            items.append({"date": dt.isoformat(), "title": p["title"],
                          "amount": float(p["amount"]), "icon": p["icon"] or "💸"})
    for d in conn.execute("SELECT * FROM debts WHERE kind='current' AND due_date IS NOT NULL").fetchall():
        try:
            dt = datetime.strptime(d["due_date"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if d0 <= dt <= d1:
            items.append({"date": dt.isoformat(), "title": d["name"],
                          "amount": float(d["total"]), "icon": d["icon"] or "🔴"})
    # долгосрочные долги (рассрочки Klarna) — ежемесячный платёж в день due_date
    for d in conn.execute("SELECT * FROM debts WHERE kind='long' AND monthly>0 AND due_date IS NOT NULL").fetchall():
        try:
            base = datetime.strptime(d["due_date"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        for y, m in _month_iter(d0, d1):
            dd = min(base.day, calendar.monthrange(y, m)[1])
            dt = date(y, m, dd)
            if d0 <= dt <= d1:
                items.append({"date": dt.isoformat(), "title": d["name"],
                              "amount": float(d["monthly"]), "icon": d["icon"] or "💳"})
    items.sort(key=lambda x: x["date"])
    return items


def bump_rev():
    """Монотонный счётчик ревизий данных. Растёт на КАЖДУЮ мутацию (в своей транзакции,
    после коммита самой записи). Каждый снимок get_data() несёт текущий rev. Клиент
    применяет снимок ТОЛЬКО если его rev не меньше уже применённого — поэтому
    устаревший ответ (кэш iOS, опоздавший запрос, гонка) физически не может откатить UI."""
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('data_rev','1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")


def _read_rev(conn):
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='data_rev'").fetchone()
        return int(row["value"]) if row and row["value"] else 0
    except Exception:
        return 0


def get_data():
    with db() as conn:
        # id DESC как финальный тай-брейк: created_at имеет посекундную точность, и
        # две карточки, созданные в одну секунду, иначе встают в произвольном порядке —
        # из-за этого свежедобавленная карточка «прыгала»/исчезала после синхронизации.
        chaos = [dict(r) for r in conn.execute(
            "SELECT * FROM chaos ORDER BY done, position ASC, created_at DESC, id DESC").fetchall()]
        _projs = {dict(p)["id"]: {**dict(p), "steps": []}
                  for p in conn.execute(
                      "SELECT * FROM projects WHERE COALESCE(archived,0)=0 ORDER BY created_at DESC, id DESC").fetchall()}
        for s in conn.execute("SELECT * FROM steps ORDER BY project_id, COALESCE(position,0) ASC, id ASC").fetchall():
            if s["project_id"] in _projs:
                _projs[s["project_id"]]["steps"].append(dict(s))
        projects = list(_projs.values())
        # chaos — единый источник истины для важности/срочности: событие, рождённое
        # из вводной, наследует её оценку, чтобы календарь и приоритизация не расходились
        chaos_pri = {c["id"]: (c.get("importance", 0) or 0, c.get("urgency", 0) or 0)
                     for c in chaos}
        cards = []
        for r in conn.execute("SELECT * FROM events").fetchall():
            d = dict(r)
            imp = d.get("importance", 0) or 0
            urg = d.get("urgency", 0) or 0
            cid = d.get("chaos_id")
            if cid and cid in chaos_pri:
                imp, urg = chaos_pri[cid]
            cards.append({"kind": "event", "id": d["id"], "date": d["date"],
                          "time": d.get("time") or "", "text": d["text"],
                          "time_end": d.get("time_end") or "",
                          "chaos_id": cid,
                          "project_id": d.get("project_id"),
                          "morning_brief": d.get("morning_brief", 0) or 0,
                          "importance": imp,
                          "urgency": urg,
                          "comment": d.get("comment") or ""})
        try:
            for r in conn.execute("SELECT * FROM reminders WHERE sent=0").fetchall():
                cards.append({"kind": "reminder", "id": r["id"], "date": r["due_at"][:10],
                              "time": r["due_at"][11:16], "text": "⏰ " + r["text"]})
        except sqlite3.OperationalError:
            pass
        try:
            balance = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
            cash = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'").fetchone()[0]
            card = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='card'").fetchone()[0]
            fin_log = [dict(r) for r in conn.execute(
                "SELECT id, amount, comment, account, created_at FROM finance ORDER BY id DESC LIMIT 25").fetchall()]
        except sqlite3.OperationalError:
            balance, cash, card, fin_log = 0, 0, 0, []
        debts = [dict(r) for r in conn.execute("SELECT * FROM debts ORDER BY kind, due_date").fetchall()]
        payments = [dict(r) for r in conn.execute(
            "SELECT * FROM payments WHERE active=1 ORDER BY kind, day").fetchall()]
        today = date.today()
        spend_today = planned_spend(conn, today, today)
        spend_week = planned_spend(conn, today, today + timedelta(days=6))
        kanban_cols = [dict(r) for r in conn.execute(
            "SELECT * FROM kanban_columns WHERE archived=0 ORDER BY position").fetchall()]
        kanban_cards = [dict(r) for r in conn.execute(
            "SELECT * FROM kanban_cards WHERE archived=0 ORDER BY column_id,position").fetchall()]
        kanban_archived = [dict(r) for r in conn.execute(
            "SELECT * FROM kanban_cards WHERE archived=1 ORDER BY archived_at DESC, id DESC").fetchall()]
        # КОРЕНЬ СНЕП-БЭКА ползунков счастья: logged_at = CURRENT_TIMESTAMP имеет точность
        # до секунды. При быстром изменении нескольких узлов (несколько INSERT в одну
        # секунду) «ORDER BY logged_at DESC LIMIT 1» возвращал ПРОИЗВОЛЬНУЮ строку из этой
        # секунды — нередко более старую, и значение откатывалось. id (AUTOINCREMENT)
        # монотонен и однозначно указывает на последнюю запись, поэтому сортируем по нему.
        hap_row = conn.execute(
            "SELECT * FROM happiness_log ORDER BY id DESC LIMIT 1").fetchone()
        happiness = dict(hap_row) if hap_row else {"work":5,"friendship":5,"health":5,"wellbeing":5,"hobby":5,"love":5}
        happiness_history = [dict(r) for r in conn.execute(
            "SELECT work,friendship,health,wellbeing,hobby,love,logged_at FROM happiness_log ORDER BY id DESC LIMIT 365").fetchall()]
        try:
            sgoals = [dict(r) for r in conn.execute(
                "SELECT * FROM goals WHERE period='strategic' AND done=0 ORDER BY id").fetchall()]
        except sqlite3.OperationalError:
            sgoals = []
        rev = _read_rev(conn)
    return {"chaos": chaos, "projects": projects, "cards": cards, "sgoals": sgoals,
            "balance": balance, "cash": cash, "card": card, "fin_log": fin_log,
            "debts": debts, "payments": payments,
            "spend_today": spend_today, "spend_week": spend_week,
            "kanban_cols": kanban_cols, "kanban_cards": kanban_cards,
            "kanban_archived": kanban_archived,
            "happiness": happiness, "happiness_history": happiness_history,
            "wisdom": today_wisdom(), "rev": rev}


# ─── planning APIs (kept compatible with the bot) ─────────────────────────────

def api_move(payload):
    kind = payload["kind"]
    new_date = payload["date"]
    with db() as conn:
        if kind == "event":
            # ключ передан → значение ставится как есть (пустая строка снимает время);
            # ключа нет → поле не трогаем
            sets, vals = ["date=?"], [new_date]
            if "time" in payload:
                sets.append("time=?"); vals.append(payload.get("time") or "")
            if "time_end" in payload:
                sets.append("time_end=?"); vals.append(payload.get("time_end") or "")
            conn.execute(f"UPDATE events SET {', '.join(sets)} WHERE id=?",
                         (*vals, payload["id"]))
        elif kind == "reminder":
            row = conn.execute("SELECT due_at FROM reminders WHERE id=?", (payload["id"],)).fetchone()
            if row:
                t = row["due_at"][11:] or "09:00"
                conn.execute("UPDATE reminders SET due_at=? WHERE id=?", (f"{new_date} {t}", payload["id"]))
        elif kind == "chaos":
            row = conn.execute("SELECT text FROM chaos WHERE id=?", (payload["id"],)).fetchone()
            if row:
                conn.execute("INSERT INTO events (text, date, time, time_end, chaos_id) VALUES (?,?,?,?,?)",
                             (row["text"], new_date, payload.get("time", ""),
                              payload.get("time_end", ""), payload["id"]))
    return {"ok": True}


def api_event_delete(payload):
    with db() as conn:
        row = conn.execute("SELECT chaos_id FROM events WHERE id=?", (payload["id"],)).fetchone()
        if row and row["chaos_id"]:
            conn.execute("DELETE FROM events WHERE chaos_id=?", (row["chaos_id"],))
            conn.execute("DELETE FROM kanban_cards WHERE chaos_id=?", (row["chaos_id"],))
            conn.execute("DELETE FROM chaos WHERE id=?", (row["chaos_id"],))
        else:
            conn.execute("DELETE FROM events WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_unplan(payload):
    with db() as conn:
        if payload["kind"] == "event":
            conn.execute("DELETE FROM events WHERE id=?", (payload["id"],))
        elif payload["kind"] == "reminder":
            conn.execute("UPDATE reminders SET sent=1 WHERE id=?", (payload["id"],))
        elif payload["kind"] == "chaos":
            conn.execute("DELETE FROM events WHERE chaos_id=?", (payload["id"],))
            conn.execute("DELETE FROM kanban_cards WHERE chaos_id=?", (payload["id"],))
            conn.execute("DELETE FROM chaos WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_complete(payload):
    with db() as conn:
        if payload["kind"] == "event":
            row = conn.execute("SELECT chaos_id FROM events WHERE id=?", (payload["id"],)).fetchone()
            if row and row["chaos_id"]:
                conn.execute("UPDATE chaos SET done=1 WHERE id=?", (row["chaos_id"],))
            conn.execute("DELETE FROM events WHERE id=?", (payload["id"],))
        elif payload["kind"] == "reminder":
            conn.execute("UPDATE reminders SET sent=1 WHERE id=?", (payload["id"],))
        elif payload["kind"] == "chaos":
            conn.execute("UPDATE chaos SET done=1 WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_rate(payload):
    imp = max(0, min(10, int(payload.get("importance", 5))))
    urg = max(0, min(10, int(payload.get("urgency", 5))))
    pri = "high" if (imp >= 6 and urg >= 6) else ("low" if (imp < 6 and urg < 6) else "mid")
    with db() as conn:
        conn.execute("UPDATE chaos SET importance=?, urgency=?, priority=? WHERE id=?",
                     (imp, urg, pri, payload["id"]))
    return {"ok": True}


def api_steps(path, payload):
    with db() as conn:
        if path == "/api/step_toggle":
            conn.execute("UPDATE steps SET done = 1 - done WHERE id=?", (payload["id"],))
        elif path == "/api/step_delete":
            conn.execute("DELETE FROM steps WHERE id=?", (payload["id"],))
        elif path == "/api/step_add":
            conn.execute("INSERT INTO steps (project_id, text) VALUES (?,?)",
                         (payload["project_id"], payload["text"]))
        elif path == "/api/step_rename":
            new_text = (payload.get("text") or "").strip()
            if new_text:
                conn.execute("UPDATE steps SET text=? WHERE id=?", (new_text, payload["id"]))
        elif path == "/api/proj_rename":
            conn.execute("UPDATE projects SET name=? WHERE id=?", (payload["name"], payload["id"]))
        elif path == "/api/proj_delete":
            conn.execute("DELETE FROM steps WHERE project_id=?", (payload["id"],))
            conn.execute("DELETE FROM projects WHERE id=?", (payload["id"],))
        elif path == "/api/proj_archive":
            # Достигнутая цель уходит в общий архив (данные сохраняются, из активных пропадает)
            conn.execute("UPDATE projects SET archived=1, archived_at=datetime('now') WHERE id=?",
                         (payload["id"],))
        elif path == "/api/step_reorder":
            ids = payload.get("ids") or []
            for i, sid in enumerate(ids):
                conn.execute("UPDATE steps SET position=? WHERE id=?", (i, sid))
        elif path == "/api/step_move":
            sid = payload["id"]
            new_pid = payload["project_id"]
            conn.execute("UPDATE steps SET project_id=? WHERE id=?", (new_pid, sid))
            ids = payload.get("ids") or []
            for i, step_id in enumerate(ids):
                conn.execute("UPDATE steps SET position=? WHERE id=?", (i, step_id))
        elif path == "/api/proj_add":
            name = (payload.get("name") or "").strip()
            if name:
                conn.execute("INSERT INTO projects (name, area) VALUES (?, 'work')", (name,))
    return {"ok": True}


def api_sgoal_add(payload):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False}
    with db() as conn:
        conn.execute("INSERT INTO goals (text, period, progress, target) VALUES (?,?,?,?)",
                     (text, "strategic", int(payload.get("progress") or 0),
                      (payload.get("target") or "").strip() or None))
    return {"ok": True}


def api_sgoal_update(payload):
    sets, vals = [], []
    if "text" in payload:
        sets.append("text=?"); vals.append((payload.get("text") or "").strip())
    if "progress" in payload:
        sets.append("progress=?"); vals.append(max(0, min(100, int(payload.get("progress") or 0))))
    if "target" in payload:
        sets.append("target=?"); vals.append((payload.get("target") or "").strip() or None)
    if "done" in payload:
        sets.append("done=?"); vals.append(1 if payload.get("done") else 0)
    if not sets:
        return {"ok": False}
    with db() as conn:
        conn.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id=?", (*vals, payload["id"]))
    return {"ok": True}


def api_sgoal_delete(payload):
    with db() as conn:
        conn.execute("DELETE FROM goals WHERE id=?", (payload["id"],))
    return {"ok": True}


# ─── finance APIs ─────────────────────────────────────────────────────────────

def api_finance_add(payload):
    try:
        amount = float(payload["amount"])
    except (KeyError, ValueError, TypeError):
        return {"ok": False, "error": "bad amount"}
    account = payload.get("account") if payload.get("account") in ("cash", "card") else "card"
    comment = (payload.get("comment") or "").strip() or "коррекция"
    with db() as conn:
        conn.execute("INSERT INTO finance (amount, comment, account) VALUES (?,?,?)",
                     (amount, comment, account))
    return {"ok": True}


def api_finance_delete(payload):
    with db() as conn:
        conn.execute("DELETE FROM finance WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_debt_add(payload):
    with db() as conn:
        ensure_schema(conn)
        conn.execute("""INSERT INTO debts (name, kind, total, paid, due_date, monthly, icon, note)
            VALUES (?,?,?,?,?,?,?,?)""", (
            (payload.get("name") or "Долг").strip(),
            payload.get("kind") if payload.get("kind") in ("current", "long") else "current",
            float(payload.get("total") or 0),
            float(payload.get("paid") or 0),
            payload.get("due_date") or None,
            float(payload.get("monthly") or 0),
            payload.get("icon") or ("🏦" if payload.get("kind") == "long" else "🔴"),
            payload.get("note") or ""))
    return {"ok": True}


def api_debt_update(payload):
    """Явная семантика ключей: передан ключ — пишем, нет — не трогаем.
    «Возврат» реализуется через paid (клиент присылает новое значение)."""
    sets, vals = [], []
    if "name" in payload:
        sets.append("name=?"); vals.append((payload.get("name") or "").strip() or "Долг")
    if "total" in payload:
        sets.append("total=?"); vals.append(max(0.0, float(payload.get("total") or 0)))
    if "paid" in payload:
        sets.append("paid=?"); vals.append(max(0.0, float(payload.get("paid") or 0)))
    if "due_date" in payload:
        sets.append("due_date=?"); vals.append((payload.get("due_date") or "").strip() or None)
    if "monthly" in payload:
        sets.append("monthly=?"); vals.append(max(0.0, float(payload.get("monthly") or 0)))
    if not sets:
        return {"ok": False}
    with db() as conn:
        conn.execute(f"UPDATE debts SET {', '.join(sets)} WHERE id=?", (*vals, payload["id"]))
    return {"ok": True}


def api_debt_delete(payload):
    with db() as conn:
        conn.execute("DELETE FROM debts WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_payment_add(payload):
    with db() as conn:
        ensure_schema(conn)
        conn.execute("""INSERT INTO payments (title, amount, account, kind, recur, day, date, icon)
            VALUES (?,?,?,?,?,?,?,?)""", (
            (payload.get("title") or "Платёж").strip(),
            float(payload.get("amount") or 0),
            payload.get("account") if payload.get("account") in ("cash", "card") else "card",
            payload.get("kind") if payload.get("kind") in ("recurring", "planned") else "recurring",
            payload.get("recur") if payload.get("recur") in ("monthly", "weekly") else "monthly",
            int(payload.get("day") or 1),
            payload.get("date") or None,
            payload.get("icon") or "💸"))
    return {"ok": True}


def api_payment_delete(payload):
    with db() as conn:
        conn.execute("UPDATE payments SET active=0 WHERE id=?", (payload["id"],))
    return {"ok": True}


def api_kcard_add(payload):
    with db() as conn:
        conn.execute("INSERT INTO kanban_cards(column_id,title,color,description) VALUES(?,?,?,?)",
            (payload["col"], payload["title"], payload.get("color",""), payload.get("desc","")))
    return {"ok": True}

def api_kcard_check(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_cards SET checked=? WHERE id=?",
            (1 if payload.get("checked") else 0, payload["id"]))
    return {"ok": True}

def api_kcard_archive(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_cards SET archived=1, archived_at=datetime('now') WHERE id=?", (payload["id"],))
    return {"ok": True}

def api_kcard_unarchive(payload):
    with db() as conn:
        # если колонка карточки была удалена — вернём в первую доступную
        row = conn.execute("SELECT column_id FROM kanban_cards WHERE id=?", (payload["id"],)).fetchone()
        col_id = row["column_id"] if row else None
        exists = col_id is not None and conn.execute(
            "SELECT 1 FROM kanban_columns WHERE id=? AND archived=0", (col_id,)).fetchone()
        if not exists:
            first = conn.execute(
                "SELECT id FROM kanban_columns WHERE archived=0 ORDER BY position LIMIT 1").fetchone()
            if first:
                conn.execute("UPDATE kanban_cards SET column_id=? WHERE id=?", (first["id"], payload["id"]))
        conn.execute("UPDATE kanban_cards SET archived=0, archived_at=NULL WHERE id=?", (payload["id"],))
    return {"ok": True}

def api_kcard_delete(payload):
    with db() as conn:
        conn.execute("DELETE FROM kanban_cards WHERE id=?", (payload["id"],))
    return {"ok": True}

def api_kcard_move(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_cards SET column_id=? WHERE id=?", (payload["col"], payload["id"]))
    return {"ok": True}

def api_kcard_rename(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_cards SET title=? WHERE id=?", (payload["title"], payload["id"]))
    return {"ok": True}

def api_kcol_add(payload):
    COLORS = ["#5b9dff","#ff9aa6","#ffd07a","#52e08a","#b18bff","#41e3d4","#ff7ac0"]
    with db() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM kanban_columns").fetchone()[0]
        color = COLORS[pos % len(COLORS)]
        conn.execute("INSERT INTO kanban_columns(name,color,position) VALUES(?,?,?)",
            (payload["name"], color, pos))
    return {"ok": True}

def api_kcol_setstatus(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_columns SET status=? WHERE id=?",
            (payload["status"], payload["id"]))
    return {"ok": True}

def api_kcol_setdeadline(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_columns SET deadline=? WHERE id=?",
            (payload.get("deadline") or None, payload["id"]))
    return {"ok": True}

def api_kcol_rename(payload):
    with db() as conn:
        conn.execute("UPDATE kanban_columns SET name=? WHERE id=?",
            (payload["name"], payload["id"]))
    return {"ok": True}

def api_kcol_delete(payload):
    with db() as conn:
        conn.execute("DELETE FROM kanban_cards WHERE column_id=?", (payload["id"],))
        conn.execute("DELETE FROM kanban_columns WHERE id=?", (payload["id"],))
    return {"ok": True}

def api_chaos_add(payload):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False}
    area = payload.get("area") if payload.get("area") in (
        "work", "health", "money", "people", "home", "self", "other") else "other"
    with db() as conn:
        min_pos = conn.execute(
            "SELECT COALESCE(MIN(position), 1) FROM chaos WHERE done=0"
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO chaos (text, area, priority, importance, urgency, position) VALUES (?,?,?,?,?,?)",
            (text, area, "mid", 0, 0, min_pos - 1)
        )
        # опциональное расписание в стиле iOS-календаря: дата + начало/конец (или весь день)
        if payload.get("date"):
            conn.execute(
                "INSERT INTO events (text, date, time, time_end, chaos_id) VALUES (?,?,?,?,?)",
                (text, payload["date"], payload.get("time") or "",
                 payload.get("time_end") or "", cur.lastrowid)
            )
    return {"ok": True}


def api_chaos_reorder(payload):
    ids = payload.get("ids") or []
    with db() as conn:
        for i, cid in enumerate(ids):
            conn.execute("UPDATE chaos SET position=? WHERE id=?", (i, cid))
    return {"ok": True}


def api_chaos_rename(payload):
    with db() as conn:
        conn.execute("UPDATE chaos SET text=? WHERE id=?", (payload["text"], payload["id"]))
    return {"ok": True}


def api_event_update(payload):
    with db() as conn:
        if "morning_brief" in payload:
            conn.execute("UPDATE events SET morning_brief=? WHERE id=?",
                         (1 if payload["morning_brief"] else 0, payload["id"]))
        if "project_id" in payload:
            conn.execute("UPDATE events SET project_id=? WHERE id=?",
                         (payload["project_id"] or None, payload["id"]))
        if "text" in payload and (payload["text"] or "").strip():
            new_text = payload["text"].strip()
            conn.execute("UPDATE events SET text=? WHERE id=?", (new_text, payload["id"]))
            # если событие порождено вводной — синхронизируем исходный текст
            row = conn.execute("SELECT chaos_id FROM events WHERE id=?", (payload["id"],)).fetchone()
            if row and row["chaos_id"]:
                conn.execute("UPDATE chaos SET text=? WHERE id=?", (new_text, row["chaos_id"]))
        if "importance" in payload and "urgency" in payload:
            imp = max(0, min(10, int(payload["importance"])))
            urg = max(0, min(10, int(payload["urgency"])))
            conn.execute("UPDATE events SET importance=?, urgency=? WHERE id=?",
                         (imp, urg, payload["id"]))
            # событие связано с вводной — пишем оценку и в неё (единый источник истины)
            row = conn.execute("SELECT chaos_id FROM events WHERE id=?", (payload["id"],)).fetchone()
            if row and row["chaos_id"]:
                pri = "high" if (imp >= 6 and urg >= 6) else ("low" if (imp < 6 and urg < 6) else "mid")
                conn.execute("UPDATE chaos SET importance=?, urgency=?, priority=? WHERE id=?",
                             (imp, urg, pri, row["chaos_id"]))
    return {"ok": True}


def api_card_comment(payload):
    """Универсальный комментарий для любой карточки: chaos | event | step | kcard."""
    kind = payload.get("kind")
    cid = payload.get("id")
    comment = (payload.get("comment") or "").strip() or None
    table = {"chaos": "chaos", "event": "events", "step": "steps",
             "kcard": "kanban_cards"}.get(kind)
    if not table or cid is None:
        return {"ok": False}
    with db() as conn:
        conn.execute(f"UPDATE {table} SET comment=? WHERE id=?", (comment, cid))
    return {"ok": True}


def api_chaos_set_project(payload):
    with db() as conn:
        conn.execute("UPDATE chaos SET project_id=? WHERE id=?",
                     (payload.get("project_id") or None, payload["id"]))
    return {"ok": True}


def api_proj_set_morning(payload):
    with db() as conn:
        conn.execute("UPDATE projects SET morning_brief=? WHERE id=?",
                     (1 if payload.get("on") else 0, payload["id"]))
    return {"ok": True}


def api_happiness_save(payload):
    with db() as conn:
        conn.execute("""INSERT INTO happiness_log(work,friendship,health,wellbeing,hobby,love,note)
            VALUES(?,?,?,?,?,?,?)""",
            (payload.get("work",5), payload.get("friendship",5), payload.get("health",5),
             payload.get("wellbeing",5), payload.get("hobby",5), payload.get("love",5),
             payload.get("note","")))
    return {"ok": True}


PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Капитанский мостик</title>
<style>
:root{
  --txt:#f4f6fb;--muted:rgba(235,240,250,.64);--faint:rgba(235,240,250,.42);
  --blue:#5b9dff;--cyan:#41e3d4;--green:#52e08a;--amber:#ffc657;--red:#ff6b7d;--violet:#b18bff;--pink:#ff7ac0;
  --glass:rgba(255,255,255,.08);--glass2:rgba(255,255,255,.13);--rim:rgba(255,255,255,.20);--rim2:rgba(255,255,255,.34);
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;color:var(--txt);-webkit-font-smoothing:antialiased;
  background:#0a0b14;padding:0 0 40px;max-width:560px;margin:0 auto;position:relative;min-height:100vh}
.bgmesh{position:fixed;inset:-20%;z-index:-1;filter:saturate(125%);
  background:
   radial-gradient(46% 32% at 16% 6%, rgba(91,157,255,.6), transparent 60%),
   radial-gradient(44% 30% at 88% 4%, rgba(177,139,255,.55), transparent 60%),
   radial-gradient(54% 34% at 92% 60%, rgba(65,227,212,.4), transparent 62%),
   radial-gradient(56% 36% at 6% 84%, rgba(255,122,192,.4), transparent 60%),
   radial-gradient(50% 30% at 50% 40%, rgba(255,198,87,.16), transparent 60%),
   linear-gradient(165deg,#0e1126,#0a0b14 65%)}
.glass{background:var(--glass);backdrop-filter:blur(30px) saturate(180%);-webkit-backdrop-filter:blur(30px) saturate(180%);
  border:1px solid var(--rim);border-radius:24px;box-shadow:0 8px 30px rgba(0,0,0,.32),inset 0 1px 0 var(--rim2)}
.glass-sm{background:var(--glass);backdrop-filter:blur(20px) saturate(170%);-webkit-backdrop-filter:blur(20px) saturate(170%);
  border:1px solid var(--rim);border-radius:17px;box-shadow:inset 0 1px 0 var(--rim2),0 4px 16px rgba(0,0,0,.2)}
.pos{color:var(--green)} .neg{color:var(--red)}
.wrap{padding:0 14px;padding-top:calc(8px + env(safe-area-inset-top))}
#ptr{position:fixed;left:50%;top:0;transform:translate(-50%,-60px);width:42px;height:42px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:21px;z-index:60;opacity:0;pointer-events:none;
  background:var(--glass2);backdrop-filter:blur(20px) saturate(170%);-webkit-backdrop-filter:blur(20px) saturate(170%);
  border:1px solid var(--rim);box-shadow:0 6px 20px rgba(0,0,0,.35),inset 0 1px 0 var(--rim2)}
#ptr .i{display:block;transition:transform .05s linear}
#ptr.spin .i{animation:ptrspin .8s linear infinite}
@keyframes ptrspin{to{transform:rotate(360deg)}}
.hdr{display:flex;align-items:center;gap:11px;margin:8px 0 14px}
.anchor{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,rgba(91,157,255,.95),rgba(177,139,255,.95));
  display:flex;align-items:center;justify-content:center;font-size:23px;box-shadow:0 8px 20px rgba(91,157,255,.45),inset 0 1px 0 rgba(255,255,255,.5)}
.hdr h1{font-size:20px;font-weight:800;letter-spacing:-.4px}
.hdr .date{font-size:12px;color:var(--muted);margin-top:1px;font-weight:500}
.seg{display:flex;gap:4px;padding:4px;border-radius:18px;margin-bottom:14px}
.seg .s{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:8px 2px;border-radius:13px;font-size:10.5px;font-weight:700;color:var(--muted);cursor:pointer;line-height:1;letter-spacing:-.1px;transition:color .2s,background .2s}
.seg .s .e{font-size:19px;line-height:1;filter:grayscale(.35) opacity(.7);transition:filter .2s}
.seg .s.on{color:#fff;background:linear-gradient(135deg,rgba(255,255,255,.24),rgba(255,255,255,.1));box-shadow:0 5px 15px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.42)}
.seg .s.on .e{filter:none}
.balstrip{display:flex;align-items:center;padding:13px 16px;border-radius:18px;margin-bottom:13px;gap:8px}
.balstrip .lk{font-size:13px;margin-right:4px}
.balstrip .b{flex:1;text-align:center}
.balstrip .b .l{font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.7px;font-weight:800}
.balstrip .b .v{font-size:17px;font-weight:900;letter-spacing:-.4px;margin-top:2px}
.balstrip .dv{width:1px;height:26px;background:var(--rim)}
.wisdom{padding:13px 16px;border-radius:17px;font-style:italic;font-size:13px;font-weight:500;color:#fbeec6;margin-bottom:14px;display:flex;gap:9px;line-height:1.4}
.wisdom .q{font-size:24px;line-height:.7;color:var(--amber);font-style:normal}
.block{padding:16px;margin-bottom:14px}
.bh{display:flex;align-items:center;justify-content:space-between;margin-bottom:13px}
.bh .t{font-size:15px;font-weight:800;display:flex;align-items:center;gap:8px}
.bh .t .sm{font-size:10px;color:var(--faint);font-weight:700}
.bh .cnt{font-size:10.5px;color:var(--muted);font-weight:700;padding:3px 10px;border-radius:12px;background:var(--glass2);border:1px solid var(--rim)}
.cal-seg{display:flex;gap:2px;background:rgba(0,0,0,.25);border:1px solid var(--rim);border-radius:11px;padding:2px}
.cal-seg .cs{font-size:11px;font-weight:700;color:var(--muted);background:transparent;border:none;padding:5px 11px;border-radius:9px;cursor:pointer;transition:background .18s,color .18s}
.cal-seg .cs.on{color:#fff;background:linear-gradient(135deg,var(--blue),var(--violet))}
.cal-msep{font-size:11px;font-weight:800;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;margin:12px 2px 5px}
.cal-msep:first-child{margin-top:0}
.matrix{position:relative;width:100%;height:344px;border-radius:20px;overflow:hidden;border:1px solid var(--rim);
  background:
   radial-gradient(62% 60% at 100% 0%, rgba(255,107,125,.32), transparent 58%),
   radial-gradient(62% 60% at 0% 0%, rgba(255,198,87,.28), transparent 58%),
   radial-gradient(62% 60% at 100% 100%, rgba(91,157,255,.28), transparent 58%),
   radial-gradient(62% 60% at 0% 100%, rgba(235,240,250,.07), transparent 58%),
   rgba(255,255,255,.04)}
.axis-v{position:absolute;left:50%;top:8px;bottom:8px;width:2px;background:rgba(255,255,255,.16);border-radius:2px}
.axis-h{position:absolute;top:50%;left:8px;right:8px;height:2px;background:rgba(255,255,255,.16);border-radius:2px}
.qc{position:absolute;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.3px;display:flex;flex-direction:column;gap:2px;pointer-events:none}
.qc .em{font-size:13px}
.qc .s{font-size:8px;font-weight:600;color:var(--faint);text-transform:none;letter-spacing:0}
.q1{top:11px;right:12px;text-align:right;color:#ff8b98}
.q2{top:11px;left:12px;color:#ffd07a}
.q3{bottom:11px;right:12px;text-align:right;color:#86b8ff}
.q4{bottom:11px;left:12px;color:var(--faint)}
.dot{position:absolute;border-radius:50%;transform:translate(-50%,-50%);border:1.5px solid rgba(255,255,255,.55);
  box-shadow:0 3px 11px rgba(0,0,0,.4),inset 0 1px 2px rgba(255,255,255,.5);cursor:pointer}
.dot.r{background:radial-gradient(circle at 35% 30%,#ff9aa6,#ff5d6c)}
.dot.a{background:radial-gradient(circle at 35% 30%,#ffd98a,#ffb340)}
.dot.b{background:radial-gradient(circle at 35% 30%,#9bc2ff,#5b9dff)}
.dot.g{background:radial-gradient(circle at 35% 30%,rgba(235,240,250,.7),rgba(235,240,250,.35))}
.axl{position:absolute;font-size:8.5px;font-weight:900;letter-spacing:1.5px;color:var(--faint);text-transform:uppercase;pointer-events:none}
.legend{display:flex;gap:11px;margin-top:13px;flex-wrap:wrap;justify-content:center}
.lg{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--muted);font-weight:600}
.lg .d{width:10px;height:10px;border-radius:50%;box-shadow:inset 0 1px 1px rgba(255,255,255,.5)}
.mhint{text-align:center;font-size:10.5px;color:var(--faint);font-weight:600;margin-top:9px}
.task{display:flex;align-items:center;gap:10px;padding:13px 14px;border-radius:15px;margin-bottom:9px}
.task .pdot{width:10px;height:10px;border-radius:50%;flex-shrink:0;box-shadow:inset 0 1px 1px rgba(255,255,255,.5)}
.task .area{font-size:17px}
.task .tx{font-size:14px;font-weight:600;flex:1;line-height:1.3;cursor:pointer}
.task .chev{color:var(--faint);font-size:15px;font-weight:700;cursor:pointer}
.task.dragging{opacity:.35}
.drag-h{flex-shrink:0;padding:4px 8px 4px 0;cursor:grab;touch-action:none;display:flex;flex-direction:column;gap:3.5px;align-items:center;justify-content:center;-webkit-user-select:none;user-select:none}
.drag-h i{display:block;width:14px;height:2px;background:rgba(235,240,250,.3);border-radius:2px;pointer-events:none}
.dot-menu{position:fixed;bottom:0;left:50%;transform:translateX(-50%);max-width:480px;width:100%;background:rgba(18,20,36,.96);border-top:1px solid rgba(255,255,255,.12);border-radius:22px 22px 0 0;padding:20px 18px 36px;z-index:500;backdrop-filter:blur(32px);-webkit-backdrop-filter:blur(32px);max-height:90vh;overflow-y:auto}
.dot-menu .dm-t{font-size:14px;font-weight:700;color:var(--txt);margin-bottom:14px;line-height:1.35;padding-bottom:12px;border-bottom:1px solid var(--rim)}
.dot-menu .dm-btn{display:block;width:100%;padding:13px 14px;border-radius:14px;border:1px solid var(--rim);background:rgba(255,255,255,.06);color:var(--txt);font-size:14px;font-weight:700;text-align:left;margin-bottom:8px;cursor:pointer}
.dot-menu .dm-btn.danger{color:#ff8b98;background:rgba(255,107,125,.1);border-color:rgba(255,107,125,.25)}
.dot-menu .dm-close{color:var(--faint);font-size:13px;font-weight:600;text-align:center;padding:6px 0;cursor:pointer}
.dot-menu .grab{margin-bottom:14px}
.big-add{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;margin:2px 0 12px;padding:20px 16px;border:none;border-radius:18px;
  background:linear-gradient(135deg,#5b9dff,#b18bff);color:#fff;font-size:15px;font-weight:800;letter-spacing:.3px;cursor:pointer;
  box-shadow:0 8px 24px rgba(91,157,255,.34),inset 0 1px 0 rgba(255,255,255,.45);transition:transform .12s}
.big-add .ic{font-size:18px}
.big-add:active{transform:scale(.975)}
.idea-h{display:flex;align-items:center;gap:13px;margin-bottom:15px}
.idea-spark{font-size:30px;filter:drop-shadow(0 4px 12px rgba(255,208,122,.55))}
.idea-txt{width:100%;background:rgba(0,0,0,.28);border:1px solid var(--rim);border-radius:16px;color:var(--txt);font-size:16px;
  padding:14px;resize:none;font-family:inherit;line-height:1.45;outline:none}
.idea-txt:focus{border-color:rgba(91,157,255,.5)}
.idea-lbl{font-size:11px;font-weight:800;color:var(--faint);text-transform:uppercase;letter-spacing:.6px;margin:14px 2px 8px}
/* блок планирования в стиле iOS-календаря (весь день / начало / конец) */
.sched-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 2px;border-bottom:1px solid var(--rim)}
.sched-lbl{font-size:14px;font-weight:600;color:var(--txt);flex-shrink:0}
.sched-inps{display:flex;gap:8px;min-width:0}
.sched-inps input{background:rgba(255,255,255,.07);border:1px solid var(--rim);border-radius:11px;color:#fff;font-size:14px;font-family:inherit;padding:8px 10px;-webkit-appearance:none;color-scheme:dark;min-width:0}
.sched-inps input:focus{border-color:rgba(91,157,255,.5);outline:none}
.idea-chips{display:flex;flex-wrap:wrap;gap:7px}
.idea-chip{font-size:12px;font-weight:700;padding:8px 13px;border-radius:13px;background:var(--glass2);border:1px solid var(--rim);color:var(--muted);cursor:pointer;transition:transform .12s}
.idea-chip:active{transform:scale(.94)}
.idea-chip.on{color:#fff;background:linear-gradient(135deg,rgba(91,157,255,.55),rgba(177,139,255,.55));border-color:rgba(255,255,255,.32)}
.pdot.hi{background:var(--red)} .pdot.mi{background:var(--amber)} .pdot.lo{background:var(--green)} .pdot.none{background:var(--faint)}
.addr{display:flex;align-items:center;gap:9px;padding:13px 14px;border:1.5px dashed var(--rim);border-radius:15px;color:var(--muted);font-size:12.5px;font-weight:700;margin-top:3px;cursor:pointer}
.addr .p{width:22px;height:22px;border-radius:8px;background:linear-gradient(135deg,var(--blue),var(--violet));color:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;box-shadow:inset 0 1px 0 rgba(255,255,255,.4)}
.addr .badge{margin-left:auto;font-size:9px;color:#fff;font-weight:700;background:rgba(91,157,255,.4);padding:4px 9px;border-radius:10px;border:1px solid var(--rim);text-align:right;line-height:1.3}
.cell{padding:11px 13px;border-radius:15px;margin-bottom:9px}
.cell.today{border:1px solid rgba(91,157,255,.55);box-shadow:0 0 18px rgba(91,157,255,.26),inset 0 1px 0 rgba(255,255,255,.25)}
.cell.past{opacity:.72}
.cd{font-size:11.5px;font-weight:800;color:var(--muted);margin-bottom:8px;display:flex;justify-content:space-between}
.cd .td{color:#86b8ff}
.ev{border-radius:11px;padding:8px 11px;margin-bottom:6px;font-size:12px;font-weight:700;display:flex;align-items:center;gap:7px;color:#fff;cursor:pointer;
  background:linear-gradient(135deg,rgba(91,157,255,.85),rgba(91,157,255,.55));border:1px solid rgba(255,255,255,.2);line-height:1.3;word-break:break-word}
.ev .t{font-weight:900;opacity:.95;font-size:10px;flex-shrink:0}
.ev.rem{background:linear-gradient(135deg,rgba(177,139,255,.85),rgba(177,139,255,.5))}
.ev:last-child{margin-bottom:0}
.goal{padding:14px 15px;border-radius:16px;margin-bottom:11px}
.goal:last-child{margin-bottom:0}
.gh{display:flex;align-items:center;gap:9px;margin-bottom:3px;cursor:pointer}
.gh .em{font-size:16px}
.gh .gn{font-size:14px;font-weight:700;flex:1}
.gh .gp{font-size:11.5px;font-weight:800;color:var(--muted)}
.gh .gp b{color:var(--green)}
.gbar{height:8px;border-radius:6px;background:rgba(0,0,0,.28);overflow:hidden;margin-top:9px;border:1px solid rgba(255,255,255,.08)}
.gfill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--green),var(--cyan));box-shadow:0 0 12px rgba(82,224,138,.5)}
.gsteps{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.gstep{font-size:10.5px;font-weight:700;padding:4px 9px;border-radius:10px;background:var(--glass2);border:1px solid var(--rim);color:var(--muted);cursor:pointer;transition:transform .1s,background .15s,color .15s,border-color .15s;-webkit-tap-highlight-color:transparent}
.gstep:active{transform:scale(.92);background:rgba(82,224,138,.22);color:#9ff0bd;border-color:rgba(82,224,138,.5)}
.gstep.done{color:#9ff0bd;border-color:rgba(82,224,138,.4);background:rgba(82,224,138,.14)}
.gstep.done::before{content:'✓ ';font-weight:900}
.gstep.idea{color:#ffd07a;border-color:rgba(255,208,122,.35);background:rgba(255,208,122,.1)}
.gsteps-rows{display:flex;flex-direction:column;gap:5px;margin-top:10px;min-height:8px;transition:background .15s,border-color .15s}
.gsteps-rows.drag-over{background:rgba(91,157,255,.08);border-radius:10px;border:1px dashed rgba(91,157,255,.45);padding:4px}
.gstep-row{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:11px;background:var(--glass2);border:1px solid var(--rim);cursor:default;transition:opacity .15s}
.gstep-row.done .gst{color:#9ff0bd;text-decoration:line-through;opacity:.7}
.gstep-row .gst{flex:1;font-size:11.5px;font-weight:700;color:var(--txt);cursor:pointer;-webkit-tap-highlight-color:transparent}
.gstep-row .drag-sh{display:flex;flex-direction:column;gap:2.5px;padding:3px 4px;opacity:.35;cursor:grab;touch-action:none;flex-shrink:0}
.gstep-row .drag-sh i{display:block;width:13px;height:1.5px;background:var(--txt);border-radius:2px}
.gstep-row.dragging{opacity:.25}
.gstep-row .done-ck{font-size:13px;flex-shrink:0;cursor:pointer;padding:2px 3px;border-radius:6px;-webkit-tap-highlight-color:transparent}
.gstep-row.done .done-ck{color:#9ff0bd}
.gstep-row .gst-act{flex-shrink:0;font-size:12px;line-height:1;padding:5px 6px;border-radius:8px;opacity:.45;cursor:pointer;transition:opacity .12s,background .12s,transform .1s;-webkit-tap-highlight-color:transparent}
.gstep-row .gst-act:active{opacity:1;background:rgba(255,255,255,.12);transform:scale(.88)}
.gstep-row .gst-act.del:active{background:rgba(255,107,125,.2)}
.gstep-row .gst-act.on{opacity:.9}
.sh-proj-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--rim);margin-top:6px;overflow:hidden}
.sh-comment-wrap{padding:10px 0 2px;border-top:1px solid var(--rim);margin-top:6px}
.sh-comment-lbl{font-size:12px;color:var(--muted);font-weight:700;margin-bottom:7px}
.sh-comment{width:100%;box-sizing:border-box;background:rgba(255,255,255,.06);border:1px solid var(--rim);border-radius:12px;color:#fff;font-size:13.5px;font-family:inherit;line-height:1.4;padding:10px 12px;resize:vertical;min-height:42px;outline:none}
.sh-comment:focus{border-color:rgba(91,157,255,.5)}
.cmt-dot{font-size:10px;opacity:.65;margin-left:4px;flex-shrink:0}
.gact{display:flex;gap:7px;margin-top:10px}
.gact button{flex:1;background:var(--glass2);border:1px solid var(--rim);border-radius:10px;color:var(--txt);padding:8px;font-size:11px;font-weight:700;cursor:pointer}
.gact button.danger{color:#ff9aa6}
.fin-cards{display:flex;gap:10px;margin-bottom:14px}
.fc{flex:1;padding:15px 13px;border-radius:19px;position:relative;overflow:hidden;text-align:center}
.fc .glow{position:absolute;width:80px;height:80px;border-radius:50%;filter:blur(26px);opacity:.55;right:-12px;top:-18px}
.fc.cash .glow{background:var(--green)} .fc.card .glow{background:var(--blue)} .fc.total .glow{background:var(--amber)}
.fc .ic{font-size:22px;margin-bottom:8px;display:block}
.fc .l{font-size:9px;color:var(--faint);text-transform:uppercase;letter-spacing:.6px;font-weight:800}
.fc .v{font-size:20px;font-weight:900;letter-spacing:-.6px;margin-top:3px}
.daysum{display:flex;gap:11px;margin-bottom:14px}
.daysum .ds{flex:1;padding:15px 16px;border-radius:18px}
.daysum .ds .l{font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.6px;font-weight:800}
.daysum .ds .v{font-size:23px;font-weight:900;margin-top:5px;letter-spacing:-.6px}
.daysum .ds.today{border-color:rgba(255,198,87,.4)}
.daysum .ds.today .v{color:var(--amber)}
.daysum .ds .mini{font-size:10px;color:var(--muted);margin-top:8px;font-weight:600;line-height:1.6}
.debt{display:flex;align-items:center;gap:11px;padding:13px 14px;border-radius:15px;margin-bottom:9px}
.debt .nm{flex:1}
.debt .nm .t{font-size:13.5px;font-weight:700}
.debt .nm .due-pill{font-size:9px;font-weight:800;padding:3px 8px;border-radius:9px;background:rgba(255,198,87,.16);color:#ffd07a;margin-top:5px;display:inline-block}
.debt .nm .due-pill.urg{background:rgba(255,107,125,.18);color:#ff9aa6}
.debt .nm .due-pill.soon{background:rgba(255,198,87,.16);color:#ffd07a}
.debt .nm .due-pill.ok{background:rgba(91,157,255,.16);color:#86b8ff}
.debt .nm .due-pill.done{background:rgba(82,224,138,.16);color:#52e08a}
.debt.paidrow,.ldebt.paidrow{opacity:.55}
.debt.paidrow .amt{color:var(--muted)}
.debt,.ldebt{cursor:pointer}
.debt .amt{font-size:16px;font-weight:900;color:#ff9aa6}
/* Карта долгов — столбчатый график */
.debtchart{display:flex;gap:10px;align-items:flex-end;overflow-x:auto;padding:8px 2px 4px;min-height:160px;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.debtchart::-webkit-scrollbar{display:none}
.dbar{display:flex;flex-direction:column;align-items:center;gap:6px;flex:0 0 auto;width:52px;cursor:pointer;justify-content:flex-end}
.dbar .dbar-amt{font-size:10px;font-weight:900;color:var(--txt);white-space:nowrap}
.dbar .col{width:40px;border-radius:10px 10px 6px 6px;display:flex;align-items:center;justify-content:center;transition:height .35s,opacity .3s;box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}
.dbar .col.paid{background:transparent;border:2px dashed rgba(82,224,138,.55);box-shadow:none}
.dbar .col.paid .chk{font-size:18px;color:#52e08a;font-weight:900}
.dbar .col.overdue,.dbar .col.urgent{box-shadow:inset 0 1px 0 rgba(255,255,255,.25),0 0 14px rgba(255,107,125,.35)}
.dbar .nm{font-size:9.5px;color:var(--muted);font-weight:700;max-width:52px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center}
.dlegend{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:10px;font-size:10.5px;font-weight:700;color:var(--muted)}
.dlegend span{display:flex;align-items:center;gap:5px}
.dlegend i{width:11px;height:11px;border-radius:3px;display:inline-block}
.dlegend .lg-r{background:linear-gradient(180deg,#ff6b7d,#ff9aa6)}
.dlegend .lg-a{background:linear-gradient(180deg,#ffb648,#ffd07a)}
.dlegend .lg-b{background:linear-gradient(180deg,#5b9dff,#86b8ff)}
.dlegend .lg-ok{background:transparent;border:2px dashed rgba(82,224,138,.6)}
.debt .x{color:var(--faint);font-size:17px;padding:0 2px;cursor:pointer}
.debt.soon{border-color:rgba(255,107,125,.45);box-shadow:0 0 16px rgba(255,107,125,.12),inset 0 1px 0 var(--rim2)}
.ldebt{padding:14px 15px;border-radius:16px;margin-bottom:11px}
.ldebt .lh{display:flex;align-items:center;gap:9px;margin-bottom:9px}
.ldebt .lh .em{font-size:16px}
.ldebt .lh .t{font-size:13.5px;font-weight:700;flex:1}
.ldebt .lh .p{font-size:11.5px;font-weight:800;color:var(--muted)}
.ldebt .lh .x{color:var(--faint);font-size:16px;cursor:pointer}
.ldebt .lbar{height:8px;border-radius:5px;background:rgba(0,0,0,.28);overflow:hidden;border:1px solid rgba(255,255,255,.08)}
.ldebt .lfill{height:100%;border-radius:5px;background:linear-gradient(90deg,var(--amber),var(--pink));box-shadow:0 0 12px rgba(255,122,192,.4)}
.ldebt .lm{font-size:10.5px;color:var(--faint);font-weight:600;margin-top:8px;display:flex;justify-content:space-between}
.ldebt .lm b{color:var(--muted)}
.recur{display:flex;align-items:center;gap:11px;padding:12px 13px;border-radius:14px;margin-bottom:8px}
.recur .ic{width:32px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;background:var(--glass2);border:1px solid var(--rim)}
.recur .nm{flex:1;font-size:13.5px;font-weight:700}
.recur .when{font-size:10px;color:var(--muted);font-weight:700;background:var(--glass2);padding:4px 9px;border-radius:10px;border:1px solid var(--rim)}
.recur .amt{font-size:14.5px;font-weight:900;min-width:52px;text-align:right}
.recur .x{color:var(--faint);font-size:16px;cursor:pointer;padding-left:2px}
.fin-add{padding:17px;margin-bottom:14px}
.ft{font-size:11.5px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:13px}
.fin-row{display:flex;gap:9px;margin-bottom:10px}
.fin-inp,.fin-sel{flex:1;padding:13px 14px;border-radius:13px;color:var(--txt);font-size:13.5px;font-weight:600;background:rgba(0,0,0,.28);border:1px solid var(--rim);-webkit-appearance:none}
.fin-inp::placeholder{color:var(--faint)}
.fin-btns{display:flex;gap:10px;margin-top:3px}
.fbtn{flex:1;border-radius:14px;padding:14px;font-size:14px;font-weight:900;text-align:center;color:#fff;border:1px solid rgba(255,255,255,.25);box-shadow:inset 0 1px 0 rgba(255,255,255,.35);cursor:pointer}
.fbtn.in{background:linear-gradient(135deg,rgba(82,224,138,.95),rgba(65,227,212,.85))}
.fbtn.out{background:linear-gradient(135deg,rgba(255,107,125,.95),rgba(255,122,192,.8))}
.fin-log{padding:17px}
.fl{display:flex;align-items:center;gap:11px;padding:11px 2px;border-bottom:1px solid rgba(255,255,255,.08);font-size:13.5px}
.fl:last-child{border:none}
.fl .amt{font-weight:900;min-width:74px;text-align:right;letter-spacing:-.3px}
.fl .acc{font-size:15px}
.fl .cm{flex:1;color:var(--muted);font-weight:600;font-size:13px}
.fl .dt{font-size:11px;color:var(--faint);font-weight:600}
.fl .x{color:var(--faint);cursor:pointer;font-size:15px;padding:0 2px}
.empty{color:var(--faint);font-size:12.5px;padding:8px 2px;font-weight:600}
.home-ind{width:135px;height:5px;border-radius:3px;background:rgba(255,255,255,.4);margin:14px auto 0}
.page{display:none}.page.on{display:block}
/* bottom sheet */
#sheet-bg{position:fixed;inset:0;background:rgba(5,6,12,.55);backdrop-filter:blur(3px);z-index:40}
#sheet{position:fixed;left:8px;right:8px;bottom:10px;z-index:41;padding:18px 18px calc(20px + env(safe-area-inset-bottom));border-radius:30px;max-width:544px;margin:0 auto;
  transform:translateY(40px);opacity:0;transition:transform .3s cubic-bezier(.2,.8,.2,1),opacity .25s}
.grab{width:42px;height:5px;border-radius:3px;background:var(--rim2);margin:0 auto 16px}
.stitle{font-size:16px;font-weight:800;text-align:center;margin-bottom:3px}
.stitle-row{display:flex;align-items:center;gap:8px;margin-bottom:3px}
.stitle-row .stitle{flex:1;min-width:0;margin:0}
.title-edit-spacer{width:34px;flex-shrink:0}
.title-edit-btn{width:34px;height:34px;flex-shrink:0;border-radius:11px;border:1px solid var(--rim);
  background:rgba(255,255,255,.06);color:rgba(235,240,250,.6);font-size:15px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent}
.title-edit-btn:active{background:rgba(255,255,255,.16);transform:scale(.92)}
.ssub{font-size:12px;color:var(--muted);text-align:center;margin-bottom:16px;font-weight:600}
.slider-row{margin-bottom:16px}
.sl-top{display:flex;justify-content:space-between;font-size:12.5px;font-weight:800;margin-bottom:9px}
.sl-top .val{color:var(--blue)}
input[type=range]{-webkit-appearance:none;width:100%;height:10px;border-radius:6px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);outline:none}
input[type=range].imp{background:linear-gradient(90deg,var(--amber),var(--red))}
input[type=range].urg{background:linear-gradient(90deg,var(--cyan),var(--blue))}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:26px;height:26px;border-radius:50%;background:#fff;box-shadow:0 3px 10px rgba(0,0,0,.45);cursor:pointer}
.sh-quad{display:flex;align-items:center;justify-content:center;gap:8px;padding:11px;border-radius:14px;font-size:13px;font-weight:800;margin:14px 0}
.sh-days{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}
.sh-day{background:rgba(0,0,0,.25);border:1px solid var(--rim);border-radius:12px;color:var(--txt);padding:11px 4px;font-size:13px;font-weight:700;cursor:pointer;text-align:center}
.sh-picker{display:flex;gap:8px;margin-bottom:12px;align-items:stretch}
.sh-picker select{flex:1;background:rgba(0,0,0,.28);border:1px solid var(--rim);border-radius:12px;color:var(--txt);padding:11px;font-size:15px;-webkit-appearance:none;text-align:center}
.sh-picker input[type=date],.sh-picker input[type=time]{flex:1;min-width:0;background:rgba(0,0,0,.28);border:1px solid var(--rim);border-radius:12px;color:var(--txt);padding:11px 8px;font-size:15px;font-weight:700;font-family:inherit;text-align:center;-webkit-appearance:none}
.sh-picker input[type=time]{flex:.8}
.sh-picker button{flex:1.2;background:linear-gradient(135deg,var(--blue),var(--violet));border:none;border-radius:12px;color:#fff;padding:11px 6px;font-size:13px;font-weight:800;cursor:pointer;white-space:nowrap}
.sh-pick-lbl{font-size:11px;color:var(--muted);font-weight:700;text-align:center;margin:2px 0 8px;letter-spacing:.3px}
.sh-actions{display:flex;gap:10px;margin-top:4px}
.sh-btn{flex:1;padding:14px;border-radius:15px;font-size:13.5px;font-weight:800;text-align:center;border:1px solid var(--rim);color:#fff;background:var(--glass2);cursor:pointer}
.sh-btn.prime{background:linear-gradient(135deg,var(--blue),var(--violet));border-color:rgba(255,255,255,.3)}
.sh-btn.danger{color:#ff9aa6}
.sh-divider{height:1px;background:var(--rim);margin:14px 0}
.sh-act{width:100%;padding:15px;border-radius:16px;font-size:14px;font-weight:800;text-align:center;
  border:1px solid var(--rim);color:#fff;background:var(--glass2);cursor:pointer;letter-spacing:.2px}
.sh-act.sh-del{color:var(--red)}
.ui-input{width:100%;margin-top:14px;padding:14px;border-radius:14px;border:1px solid var(--rim);
  background:rgba(0,0,0,.3);color:var(--txt);font-size:16px;font-weight:600;outline:none;-webkit-appearance:none}
.ui-input:focus{border-color:var(--blue)}
.ssub2{font-size:12.5px;color:var(--muted);text-align:center;margin-top:4px;font-weight:600;line-height:1.4}

/* kanban */
.kanban{display:flex;gap:14px;overflow-x:auto;padding-bottom:20px;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.kanban::-webkit-scrollbar{display:none}
.kol{min-width:240px;flex-shrink:0;display:flex;flex-direction:column;gap:9px}
.kol-head{padding:11px 13px;border-radius:16px;font-weight:800;font-size:13px;margin-bottom:2px;border:1px solid rgba(255,255,255,.18)}
.kcard{position:relative;padding:12px 44px 12px 13px;border-radius:15px;cursor:pointer;transition:background .2s,opacity .25s;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.1)}
.kcard.done{background:rgba(10,12,22,.62);opacity:.6}
.kcard .kt{font-size:13px;font-weight:700;line-height:1.42}
.kcard.done .kt{text-decoration:line-through;color:rgba(235,240,250,.4)}
.kcard .kdesc{font-size:11px;color:rgba(235,240,250,.55);margin-top:4px;font-weight:500}
.kcard .krow{display:flex;align-items:center;gap:8px;margin-top:8px}
.kchk{width:20px;height:20px;border-radius:6px;border:2px solid rgba(255,255,255,.3);flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:12px;transition:all .2s}
.kchk.done{background:#52e08a;border-color:#52e08a}
.karch{font-size:10px;color:rgba(235,240,250,.35);background:none;border:none;cursor:pointer;font-weight:700;padding:2px 6px}
.kren{position:absolute;top:8px;right:8px;width:26px;height:26px;border-radius:8px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.13);
  cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:13px;line-height:1;transition:background .18s,transform .12s;flex-shrink:0;z-index:2}
.kren:active{background:rgba(255,255,255,.2);transform:scale(.92)}
.kadd{width:100%;padding:11px;border-radius:14px;background:rgba(255,255,255,.05);border:1px dashed rgba(255,255,255,.2);
  color:rgba(235,240,250,.5);font-weight:700;font-size:12px;cursor:pointer;margin-top:2px;text-align:center}
.kadd:active{background:rgba(255,255,255,.1)}
/* kanban full-width Trello layout */
.kanban-wrap{margin:0 -14px;position:relative}
.kanban-toolbar{display:flex;align-items:center;justify-content:flex-end;padding:0 14px 10px;gap:8px}
.kanban{display:flex;gap:12px;overflow-x:auto;padding:4px 14px 16px;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch}
.kanban::-webkit-scrollbar{display:none}
.kol{min-width:252px;max-width:252px;flex-shrink:0;display:flex;flex-direction:column;gap:9px;
  scroll-snap-align:start;border-radius:18px;padding:12px;
  background:rgba(255,255,255,.06);border:1.5px solid rgba(255,255,255,.10);transition:border-color .35s,box-shadow .35s}
.kol.current{border-color:#52e08a;box-shadow:0 0 0 1px rgba(82,224,138,.25),0 0 20px rgba(82,224,138,.12)}
.kol-head{padding:7px 4px 9px;border-radius:12px;font-weight:800;font-size:13px;display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none}
.kol-head:active{opacity:.75}
.kol-head .kh-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.kol-head .kh-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kol-head .kh-cnt{opacity:.45;font-weight:600;font-size:11px;flex-shrink:0}
.kol-head .kh-more{opacity:.35;font-size:15px;flex-shrink:0;line-height:1}
/* Проекты-как-доски: колонка проекта, шаги — карточки */
.pcol-bar{height:5px;border-radius:4px;background:rgba(0,0,0,.28);overflow:hidden;margin:-2px 2px 4px;border:1px solid rgba(255,255,255,.07)}
.pcol-fill{height:100%;background:linear-gradient(90deg,var(--blue),var(--violet));border-radius:4px;transition:width .3s}
.kcard.pstep{padding:11px 34px 11px 34px;display:block}
.kcard.pstep .pcheck{position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:16px;cursor:pointer;opacity:.85}
.kcard.pstep .pstep-tx{cursor:text;line-height:1.35}
.kcard.pstep .pdel{position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:13px;opacity:.4;cursor:pointer}
.kcard.pstep .gstep-cmt{position:absolute;right:31px;top:50%;transform:translateY(-50%);font-size:13px;opacity:.3;cursor:pointer}
.kcard.pstep .gstep-cmt.on{opacity:.9}
.kcard.pstep.done .pstep-tx{text-decoration:line-through;opacity:.5}
.kcard.pidea{background:rgba(255,208,122,.14);border-color:rgba(255,208,122,.35);font-size:12px;cursor:pointer;padding:10px 13px}
.sgoal{cursor:pointer}
.sg-target{font-size:11px;font-weight:700;color:var(--muted);background:var(--glass2);border:1px solid var(--rim);border-radius:9px;padding:2px 8px}
.kdl{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;
  padding:3px 8px;border-radius:20px;margin-top:0;margin-bottom:2px;cursor:pointer}
.kdl.ok{background:rgba(91,157,255,.18);color:#5b9dff}
.kdl.soon{background:rgba(255,198,87,.2);color:#ffc657}
.kdl.overdue{background:rgba(255,107,125,.2);color:#ff6b7d}
/* toggle — reused in sheet */
.tog{width:52px;height:28px;border-radius:14px;background:rgba(255,255,255,.1);border:1px solid var(--rim);
  cursor:pointer;position:relative;transition:background .3s;flex-shrink:0}
.tog.on{background:linear-gradient(135deg,#52e08a,#5b9dff)}
.tog-k{width:22px;height:22px;border-radius:50%;background:#fff;position:absolute;top:2px;left:2px;
  transition:left .3s;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.tog.on .tog-k{left:26px}
.ptlabel{font-weight:800;font-size:13px;color:var(--muted)}
.ptlabel.on{color:var(--txt)}
.confetti-particle{position:fixed;pointer-events:none;border-radius:3px;animation:confetti-fly 1.1s ease-out forwards;z-index:9999}
@keyframes confetti-fly{0%{transform:translate(0,0) rotate(0deg) scale(1);opacity:1}100%{transform:translate(var(--dx),var(--dy)) rotate(var(--dr)) scale(0);opacity:0}}

/* happiness */
.hmap-wrap{position:relative;width:100%;height:420px;margin-bottom:14px;
  background:radial-gradient(ellipse 80% 65% at 50% 50%,rgba(255,255,255,.04),transparent 72%);border-radius:18px}
.hmap-svg{position:absolute;inset:0;width:100%;height:100%}
.hnode{position:absolute;transform:translate(-50%,-50%);text-align:center;cursor:pointer;z-index:2;transition:transform .15s}
.hnode:active{transform:translate(-50%,-50%) scale(.91)}
.hnode .hc{width:62px;height:62px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:26px;margin:0 auto 5px;
  backdrop-filter:blur(24px) saturate(200%);-webkit-backdrop-filter:blur(24px) saturate(200%);
  border:1.5px solid rgba(255,255,255,.22)}
.hnode.center .hc{width:86px;height:86px;font-size:36px;border-width:2px;border-color:rgba(255,255,255,.3);backdrop-filter:none;-webkit-backdrop-filter:none}
.hnode .hl{font-size:9px;font-weight:900;color:rgba(255,255,255,.55);letter-spacing:.6px;text-shadow:0 1px 6px rgba(0,0,0,.6)}
.hnode .hv{font-size:22px;font-weight:900;line-height:1.15;text-shadow:0 2px 10px rgba(0,0,0,.5)}
.hdyn{margin-top:6px}
.hdyn canvas{border-radius:12px;width:100%;display:block}
.hslider-wrap{padding:14px 16px;border-radius:18px;margin-bottom:10px}
.hslider-label{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-size:13px;font-weight:800}
.hslider-label span{font-size:20px;font-weight:900;color:var(--blue)}
input[type=range].hslider{width:100%;accent-color:var(--blue);height:6px}
.hper-btn{padding:4px 9px;border-radius:9px;font-size:11px;font-weight:700;border:1px solid var(--rim);background:var(--glass2);color:var(--muted);cursor:pointer;-webkit-appearance:none}
.hper-btn.on{background:rgba(91,157,255,.22);border-color:rgba(91,157,255,.45);color:#86b8ff}
.hchart-legend{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:10px;justify-content:center}
.hcl{display:flex;align-items:center;gap:5px;font-size:10.5px;color:var(--muted);font-weight:600}
.hcl .hcld{width:18px;height:3px;border-radius:2px}
/* drum picker */
.drum-sheet{position:fixed;inset:0;z-index:9999;display:flex;align-items:flex-end;background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}
.drum-inner{width:100%;background:#16172a;border-radius:28px 28px 0 0;overflow:hidden;padding-bottom:env(safe-area-inset-bottom,16px)}
.drum-hdr{padding:16px 20px 14px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,255,255,.09)}
.drum-hdr .dm-cancel{font-size:15px;font-weight:700;color:rgba(235,240,250,.4);cursor:pointer}
.drum-hdr .dm-title{font-size:14px;font-weight:900;letter-spacing:.4px}
.drum-hdr .dm-ok{font-size:16px;font-weight:900;color:#5b9dff;cursor:pointer}
.drum-body{position:relative;height:165px;overflow:hidden}
.drum-sel{position:absolute;top:55px;left:16px;right:16px;height:55px;border-radius:13px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.13);z-index:1;pointer-events:none}
.drum-body::before,.drum-body::after{content:'';position:absolute;left:0;right:0;height:60px;z-index:2;pointer-events:none}
.drum-body::before{top:0;background:linear-gradient(to bottom,#16172a,transparent)}
.drum-body::after{bottom:0;background:linear-gradient(to top,#16172a,transparent)}
.drum-scroll{height:165px;overflow-y:scroll;scroll-snap-type:y mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none;overscroll-behavior:contain}
.drum-scroll::-webkit-scrollbar{display:none}
.drum-pad{height:55px}
.drum-item{height:55px;scroll-snap-align:center;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:600;color:rgba(235,240,250,.25);transition:font-size .12s,color .12s,font-weight .12s;user-select:none}
.drum-item.sel{font-size:32px;font-weight:900;color:#f4f6fb}
</style></head>
<body>
<div class="bgmesh"></div>
<div id="ptr"><span class="i">⚓</span></div>
<div class="wrap">
  <div class="hdr">
    <div class="anchor">⚓</div>
    <div><h1>Капитанский мостик</h1><div class="date" id="updated"></div></div>
    <div style="margin-left:auto;font-size:9px;color:rgba(235,240,250,.3);font-weight:700;align-self:flex-start">v__VERSION__</div>
  </div>
  <div class="seg glass-sm" id="seg">
    <div class="s on" data-p="plan"><span class="e">🧭</span>Мостик</div>
    <div class="s" data-p="fin"><span class="e">💰</span>Финансы</div>
    <div class="s" data-p="proj"><span class="e">📁</span>Проекты</div>
    <div class="s" data-p="hap"><span class="e">🤗</span>Счастье</div>
  </div>

  <div class="page on" id="page-plan">
    <div class="balstrip glass-sm" id="balstrip"></div>
    <div class="wisdom glass-sm"><span class="q">“</span><span id="wisdom"></span></div>
    <div class="block glass">
      <div class="bh"><div class="t">💡 Вводные</div></div>
      <button class="big-add" onclick="openIdeaSheet()"><span class="ic">✨</span>Новая вводная</button>
      <div id="chaos"></div>
    </div>
    <div class="block glass">
      <div class="bh"><div class="t">🏔 Стратегические цели <span class="sm">горизонт · прогресс</span></div><div class="cnt" id="sgoal-cnt"></div></div>
      <div id="sgoals"></div>
      <div class="addr" onclick="addSGoal()" style="cursor:pointer">🎯 Новая стратегическая цель</div>
    </div>
    <div class="block glass">
      <div class="bh"><div class="t">🎯 Расстановка приоритетов <span class="sm">важно · срочно</span></div><div class="cnt">приоритеты</div></div>
      <div class="matrix" id="matrix"></div>
      <div class="legend">
        <div class="lg"><span class="d" style="background:var(--red)"></span>сам, сейчас</div>
        <div class="lg"><span class="d" style="background:var(--amber)"></span>в календарь</div>
        <div class="lg"><span class="d" style="background:var(--blue)"></span>делегировать</div>
        <div class="lg"><span class="d" style="background:var(--faint)"></span>отказаться</div>
      </div>
      <div class="mhint">✋ тапни точку или задачу → оцени важность/срочность</div>
    </div>
    <div class="block glass">
      <div class="bh"><div class="t">📅 Прошивка календаря</div>
        <div class="cal-seg" id="cal-seg">
          <button class="cs on" data-r="week" onclick="setCalRange('week')">неделя</button>
          <button class="cs" data-r="month" onclick="setCalRange('month')">месяц</button>
          <button class="cs" data-r="year" onclick="setCalRange('year')">год</button>
        </div></div>
      <div id="cal"></div>
      <div class="addr" style="margin-top:9px;cursor:default">↔ тапни задачу — перенести в день или вернуть на парковку</div>
    </div>
  </div>

  <div class="page" id="page-fin">
    <div class="fin-cards" id="fin-cards"></div>
    <div class="block glass" id="debtchart-block" style="display:none">
      <div class="bh"><div class="t">📊 Карта долгов</div><div class="cnt" id="debt-total"></div></div>
      <div class="debtchart" id="debtchart"></div>
      <div class="dlegend">
        <span><i class="lg-r"></i>срочный</span>
        <span><i class="lg-a"></i>скоро</span>
        <span><i class="lg-b"></i>обычный</span>
        <span><i class="lg-ok"></i>погашен</span>
      </div>
    </div>
    <div class="daysum" id="daysum"></div>
    <div class="block glass">
      <div class="bh"><div class="t">🔴 Текущие задолженности</div><div class="cnt" id="cur-cnt"></div></div>
      <div id="cur-debts"></div>
      <div class="addr" onclick="addDebt('current')"><span class="p">+</span> Добавить задолженность</div>
    </div>
    <div class="block glass">
      <div class="bh"><div class="t">🏦 Долгосрочные долги</div><div class="cnt" id="long-cnt"></div></div>
      <div id="long-debts"></div>
      <div class="addr" onclick="addDebt('long')"><span class="p">+</span> Добавить долгосрочный долг</div>
    </div>
    <div class="block glass">
      <div class="bh"><div class="t">📆 Регулярные платежи</div><div class="cnt" id="pay-cnt"></div></div>
      <div id="payments"></div>
      <div class="addr" onclick="addPayment()"><span class="p">+</span> Добавить регулярный / разовый платёж</div>
    </div>
    <div class="fin-add glass">
      <div class="ft">＋ операция</div>
      <div class="fin-row">
        <select class="fin-sel" id="fin-acc" style="max-width:140px"><option value="cash">💵 Наличные</option><option value="card" selected>💳 Карта</option></select>
        <input class="fin-inp" id="fin-amt" type="number" inputmode="decimal" placeholder="Сумма €"/>
      </div>
      <div class="fin-row"><input class="fin-inp" id="fin-cm" type="text" placeholder="Комментарий"/></div>
      <div class="fin-btns"><div class="fbtn in" onclick="finAdd(1)">+ приход</div><div class="fbtn out" onclick="finAdd(-1)">− расход</div></div>
    </div>
    <div class="fin-log glass">
      <div class="ft">последние операции</div>
      <div id="fin-log"></div>
    </div>
  </div>
  <div class="page" id="page-proj">
    <div class="kanban-wrap">
      <div class="kanban-toolbar">
        <div class="cnt" id="goals-cnt" style="margin-right:auto"></div>
        <div class="btn-sm glass-sm" onclick="addProject()" style="padding:6px 14px;border-radius:10px;cursor:pointer;font-size:12px;font-weight:800">＋ проект</div>
      </div>
      <div class="kanban" id="projboard"></div>
    </div>
  </div>

  <div class="page" id="page-hap">
    <div class="block glass" style="padding:16px">
      <div class="bh"><div class="t">Ты счастлив?</div></div>
      <div class="hmap-wrap" id="hmap-wrap">
        <svg class="hmap-svg" id="hmap-lines" viewBox="0 0 300 360" preserveAspectRatio="none"></svg>
        <div class="hnode center" id="hn-center" style="left:50%;top:50%" onclick="editHappiness()">
          <div class="hc" style="background:radial-gradient(circle at 38% 28%,rgba(72,72,90,1),rgba(6,6,14,1));box-shadow:0 0 0 1.5px rgba(255,255,255,.18),inset 0 1.5px 0 rgba(255,255,255,.32),inset 0 -1px 0 rgba(0,0,0,.85),0 8px 40px rgba(0,0,0,.9),0 2px 8px rgba(0,0,0,.8)">
            <div id="hv-total" style="font-size:30px;font-weight:900;color:#ffd07a;text-shadow:0 2px 14px rgba(255,208,122,.55)">—</div>
          </div>
        </div>
        <div class="hnode" id="hn-work" onclick="editHNode('work')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(91,157,255,.78),rgba(50,100,220,.52));box-shadow:0 0 0 1px rgba(91,157,255,.4),0 0 32px rgba(91,157,255,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">💼</div>
          <div class="hl">РАБОТА</div><div class="hv" id="hv-work">5</div>
        </div>
        <div class="hnode" id="hn-friendship" onclick="editHNode('friendship')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(255,122,192,.78),rgba(200,60,160,.52));box-shadow:0 0 0 1px rgba(255,122,192,.4),0 0 32px rgba(255,122,192,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">🤝</div>
          <div class="hl">ДРУЖБА</div><div class="hv" id="hv-friendship">5</div>
        </div>
        <div class="hnode" id="hn-health" onclick="editHNode('health')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(82,224,138,.78),rgba(30,170,90,.52));box-shadow:0 0 0 1px rgba(82,224,138,.4),0 0 32px rgba(82,224,138,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">🌿</div>
          <div class="hl">ЗДОРОВЬЕ</div><div class="hv" id="hv-health">5</div>
        </div>
        <div class="hnode" id="hn-love" onclick="editHNode('love')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(255,107,125,.78),rgba(200,40,70,.52));box-shadow:0 0 0 1px rgba(255,107,125,.4),0 0 32px rgba(255,107,125,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">❤️</div>
          <div class="hl">ЛЮБОВЬ</div><div class="hv" id="hv-love">5</div>
        </div>
        <div class="hnode" id="hn-wellbeing" onclick="editHNode('wellbeing')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(255,208,122,.78),rgba(200,140,30,.52));box-shadow:0 0 0 1px rgba(255,208,122,.4),0 0 32px rgba(255,208,122,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">💰</div>
          <div class="hl">БЛАГОПОЛУЧИЕ</div><div class="hv" id="hv-wellbeing">5</div>
        </div>
        <div class="hnode" id="hn-hobby" onclick="editHNode('hobby')">
          <div class="hc" style="background:linear-gradient(145deg,rgba(177,139,255,.78),rgba(110,70,210,.52));box-shadow:0 0 0 1px rgba(177,139,255,.4),0 0 32px rgba(177,139,255,.62),0 12px 32px rgba(0,0,0,.55),inset 0 1.5px 0 rgba(255,255,255,.5)">🎨</div>
          <div class="hl">ХОББИ</div><div class="hv" id="hv-hobby">5</div>
        </div>
      </div>
    </div>
    <div class="block glass hdyn">
      <div class="bh">
        <div class="t">📈 Динамика счастья</div>
        <div style="display:flex;gap:4px">
          <button class="hper-btn on" data-p="7">7д</button>
          <button class="hper-btn" data-p="14">14д</button>
          <button class="hper-btn" data-p="month">мес</button>
          <button class="hper-btn" data-p="year">год</button>
        </div>
      </div>
      <canvas id="hchart" height="100"></canvas>
      <div class="hchart-legend" id="hchart-legend"></div>
    </div>
  </div>
  <div class="home-ind"></div>
</div>

<script>
const AREAS={work:"💼",health:"🌿",money:"💰",people:"👥",home:"🏠",self:"📚",other:"⚡"};
const MONTHS=['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const DOW=['пн','вт','ср','чт','пт','сб','вс'];
window.__INIT__=null;let DATA=null;
const openProjects=new Set();

function eur(v){return (v<0?'−':'')+Math.abs(Math.round(v)).toLocaleString('ru')+' €';}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function localISO(d){const p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
async function api(path,body){const r=await fetch(path+'?_t='+Date.now(),{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});if(r.status===401||r.status===403){location.reload();}return r;}

// ─── optimistic mutation engine (Trello-style: instant UI, authoritative sync) ───
// КОРЕНЬ ПРОБЛЕМЫ исчезновения изменений: iOS Safari в режиме PWA кэширует ответы
// GET /api/data даже при no-store и подсовывает старый снимок — он затирал свежие
// правки. Решение: данные тянем ТОЛЬКО через POST (ответы на POST Safari не кэширует
// никогда), а каждая мутация возвращает свежий снимок прямо в ответе — изменение
// подтверждается самой записью и физически не может «исчезнуть».
let _pending=0;            // in-flight background syncs
let _mutSeq=0;             // bumps on every mutation — guards against stale snapshots
let _rev=0;                // highest server revision applied — see bump_rev() on the server
// Снимок принимается, только если его ревизия НЕ СТАРШЕ уже применённой. Устаревший
// ответ (кэш iOS, опоздавший/гоночный запрос) несёт меньший rev и молча отбрасывается —
// откатить свежую правку он физически не может.
function _revOK(j){return !j||j.rev===undefined||j.rev>=_rev;}
function _applyServer(j,seqAtStart){
  if(j&&_pending===0&&_mutSeq===seqAtStart&&_revOK(j)){DATA=j;if(j.rev!==undefined)_rev=j.rev;if(!document.getElementById('sheet'))render();}
}
// Свежий снимок через POST — гарантированно мимо кэша Safari.
async function fetchData(){
  const r=await fetch('/api/data?_t='+Date.now(),{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:'{}'});
  if(r.status===401||r.status===403){location.reload();return null;}
  return r.json();
}
async function load(){
  if(window.__INIT__){DATA=window.__INIT__;if(DATA.rev!==undefined)_rev=DATA.rev;window.__INIT__=null;if(!document.getElementById('sheet'))render();return;}
  const seq=_mutSeq;
  const j=await fetchData();
  _applyServer(j,seq);
}
function _reconcile(){
  // Periodic pull (picks up changes made from the bot). Never clobbers a pending edit.
  if(_pending>0)return;
  const seq=_mutSeq;
  fetchData().then(j=>_applyServer(j,seq)).catch(()=>{});
}
// Apply locally, repaint instantly, sync to server; then adopt the authoritative
// snapshot the write returns (unless a newer mutation has already superseded it).
function mutate(localFn,path,body,paint){
  try{if(localFn)localFn();}catch(_){}
  _mutSeq++; const mySeq=_mutSeq;
  (paint||render)();
  _pending++;
  Promise.resolve(api(path,body))
    .then(r=>r?r.json():null).catch(()=>null)
    .then(j=>{
      if(j&&j.data&&_mutSeq===mySeq&&_revOK(j.data)){DATA=j.data;if(j.data.rev!==undefined)_rev=j.data.rev;if(!document.getElementById('sheet'))(paint||render)();}
    })
    .finally(()=>{_pending--;});
}
const _byId=(arr,id)=>(arr||[]).find(x=>x.id===id);
function _chaos(id){return _byId(DATA.chaos,id);}
function _card(id){return _byId(DATA.cards,id);}
function _proj(id){return _byId(DATA.projects,id);}
function _kcard(id){return _byId(DATA.kanban_cards,id);}
function _kcol(id){return _byId(DATA.kanban_cols,id);}
function _step(id){for(const p of (DATA.projects||[])){const s=_byId(p.steps,id);if(s)return s;}return null;}
function _tmpId(){return -(Date.now()*1000+Math.floor(Math.random()*1000));}

// segmented control
document.querySelectorAll('#seg .s').forEach(s=>s.onclick=()=>{
  document.querySelectorAll('#seg .s').forEach(x=>x.classList.remove('on'));
  s.classList.add('on');
  const p=s.dataset.p;
  ['plan','fin','proj','hap'].forEach(n=>document.getElementById('page-'+n).classList.toggle('on',p===n));
  window.scrollTo(0,0);
  if(p==='hap')requestAnimationFrame(()=>{updateHNodes();drawHLines();drawHChart(_hapHistory);});
});

function quadClass(imp,urg){
  if(imp>=6&&urg>=6)return 'r';
  if(imp>=6&&urg<6)return 'a';
  if(imp<6&&urg>=6)return 'b';
  return 'g';
}
function priClass(c){return c.importance||c.urgency?({r:'hi',a:'mi',b:'lo',g:'lo'})[quadClass(c.importance,c.urgency)]:'none';}
function priLabel(c){
  if(!c.importance&&!c.urgency)return ['none','ОЦЕНИТЬ'];
  const q=quadClass(c.importance,c.urgency);
  return {r:['hi','СЕЙЧАС'],a:['mi','ПЛАН'],b:['lo','ДЕЛЕГ'],g:['lo','ПОТОМ']}[q];
}

function render(){
  const d=DATA;
  document.getElementById('updated').textContent='Обновлено '+new Date().toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'});
  document.getElementById('wisdom').textContent=d.wisdom||'';
  // balance read-only strip
  document.getElementById('balstrip').innerHTML=
    '<span class="lk">🔒</span>'+
    '<div class="b"><div class="l">Наличные</div><div class="v '+((d.cash||0)<0?'neg':'pos')+'">'+eur(d.cash||0)+'</div></div>'+
    '<div class="dv"></div>'+
    '<div class="b"><div class="l">Карта</div><div class="v '+((d.card||0)<0?'neg':'pos')+'">'+eur(d.card||0)+'</div></div>'+
    '<div class="dv"></div>'+
    '<div class="b"><div class="l">Всего</div><div class="v">'+eur(d.balance||0)+'</div></div>';

  const planned=new Set(d.cards.filter(c=>c.chaos_id).map(c=>c.chaos_id));
  const open=d.chaos.filter(c=>!c.done);
  const parking=open.filter(c=>!planned.has(c.id));
  renderMatrix(open);
  // chaos parking — skip DOM rebuild while drag is in progress to preserve drag state
  if(!_dg){
    document.getElementById('chaos').innerHTML=parking.length?parking.map(c=>{
      const td=JSON.stringify({kind:"chaos",id:c.id,text:c.text,imp:c.importance,urg:c.urgency});
      return '<div class="task glass-sm" data-cid="'+c.id+'">'+
        '<span class="drag-h" ontouchstart="_startDrag(event,'+c.id+')" onmousedown="_startDrag(event,'+c.id+')"><i></i><i></i><i></i></span>'+
        '<span class="pdot '+priClass(c)+'"></span>'+
        '<span class="tx" onclick=\'openTask('+td+')\'>'  +esc(c.text)+(c.comment?'<span class="cmt-dot" title="есть комментарий">💬</span>':'')+'</span>'+
        '<span class="chev" onclick=\'openTask('+td+')\'>›</span></div>';
    }).join(''):'<div class="empty">парковка пуста — всё запланировано 🎉</div>';
  }
  // calendar
  renderCal();
  // стратегические цели на «Мостике»
  const sg=d.sgoals||[];
  const scnt=document.getElementById('sgoal-cnt');if(scnt)scnt.textContent=sg.length?sg.length+' в фокусе':'';
  const sgEl=document.getElementById('sgoals');
  if(sgEl)sgEl.innerHTML=sg.length?sg.map(g=>{
    const pct=Math.max(0,Math.min(100,g.progress||0));
    return '<div class="goal glass-sm sgoal" onclick="openSGoal('+g.id+')">'+
      '<div class="gh"><span class="em">🎯</span><span class="gn">'+esc(g.text)+'</span>'+
      '<span class="gp">'+(g.target?'<span class="sg-target">'+esc(g.target)+'</span> · ':'')+'<b>'+pct+'%</b></span></div>'+
      '<div class="gbar"><div class="gfill" style="width:'+pct+'%"></div></div></div>';
  }).join(''):'<div class="empty">целей пока нет — сформулируй 3–7 больших направлений</div>';
  // Проекты как доска
  renderProjectBoard(d);
  renderFinance();
  renderHappiness(d);
}

// ─── Проекты как Trello-доска: каждый проект — колонка, шаги — карточки ───
function renderProjectBoard(d){
  const board=document.getElementById('projboard');if(!board)return;
  const projs=d.projects||[];
  const inWork=projs.filter(p=>!p.steps.length||p.steps.some(s=>!s.done)).length;
  const gc=document.getElementById('goals-cnt');if(gc)gc.textContent=projs.length+' проектов · '+inWork+' в работе';
  if(_sd)return;  // не перерисовываем во время перетаскивания шага
  board.innerHTML=projs.length?projs.map(p=>{
    const steps=p.steps||[];
    const done=steps.filter(s=>s.done).length,total=steps.length;
    const pct=total?Math.round(done/total*100):0;
    const linkedIdeas=(d.chaos||[]).filter(c=>!c.done&&c.project_id===p.id);
    const stepCards=steps.map(s=>
      '<div class="kcard pstep'+(s.done?' done':'')+'" data-step-id="'+s.id+'" data-proj-id="'+p.id+'">'+
        '<span class="pcheck" onclick="event.stopPropagation();stepToggle('+s.id+')">'+(s.done?'☑':'☐')+'</span>'+
        '<span class="pstep-tx" onclick="event.stopPropagation();stepRename('+s.id+')">'+esc(s.text)+'</span>'+
        '<span class="gstep-cmt'+(s.comment?' on':'')+'" onclick="event.stopPropagation();stepComment('+s.id+')" title="Комментарий">💬</span>'+
        '<span class="pdel" onclick="event.stopPropagation();stepDelete('+s.id+')" title="Удалить">🗑</span>'+
      '</div>').join('');
    const ideaCards=linkedIdeas.map(c=>
      '<div class="kcard pidea" onclick=\'openTask('+JSON.stringify({kind:"chaos",id:c.id,text:c.text,imp:c.importance||0,urg:c.urgency||0,proj:p.id})+')\'>'+
      '💡 '+esc(c.text)+'</div>').join('');
    return '<div class="kol pcol" data-proj-id="'+p.id+'">'+
      '<div class="kol-head" onclick="projMenu(event,'+p.id+')">'+
        '<div class="kh-dot" style="background:linear-gradient(135deg,var(--blue),var(--violet))"></div>'+
        '<div class="kh-name">'+(AREAS[p.area]||'⚡')+' '+esc(p.name)+'</div>'+
        '<div class="kh-cnt">'+done+'/'+total+'</div>'+
        '<div class="kh-more">···</div>'+
      '</div>'+
      '<div class="pcol-bar"><div class="pcol-fill" style="width:'+pct+'%"></div></div>'+
      stepCards+ideaCards+
      '<button class="kadd" onclick="stepAdd('+p.id+')">＋ шаг</button>'+
    '</div>';
  }).join(''):'<div class="empty">проектов нет — жми «＋ проект»</div>';
}

async function addProject(){
  const t=await uiPrompt('Название проекта:','',{placeholder:'например, Творчество'});
  if(!t||!t.trim())return;
  mutate(()=>{if(!DATA.projects)DATA.projects=[];DATA.projects.unshift({id:_tmpId(),name:t.trim(),area:'work',steps:[]});},
    '/api/proj_add',{name:t.trim()});
}
function projMenu(ev,id){
  ev.stopPropagation();
  const p=_proj(id);if(!p)return;
  closeSheet();
  const bg=document.createElement('div');bg.id='sheet-bg';bg.onclick=closeSheet;document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  const done=(p.steps||[]).filter(s=>s.done).length,total=(p.steps||[]).length;
  sheet.innerHTML='<div class="grab"></div>'+
    '<div class="stitle-row"><span class="title-edit-spacer"></span><div class="stitle">'+(AREAS[p.area]||'⚡')+' '+esc(p.name)+'</div><span class="title-edit-spacer"></span></div>'+
    '<div class="ssub">'+done+' из '+total+' шагов готово</div>'+
    '<div class="sh-actions" style="flex-direction:column;gap:8px">'+
    '<button class="sh-btn" id="pm-add">＋ Шаг</button>'+
    '<button class="sh-btn" id="pm-ren">✏️ Переименовать проект</button>'+
    '<button class="sh-btn" id="pm-arch">🏆 В архив (завершён)</button>'+
    '<button class="sh-btn danger" id="pm-del">🗑 Удалить проект</button></div>';
  document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  _swipeDismiss(sheet,closeSheet);
  sheet.querySelector('#pm-add').onclick=()=>{closeSheet();stepAdd(id);};
  sheet.querySelector('#pm-ren').onclick=()=>{closeSheet();projRename(id,p.name);};
  sheet.querySelector('#pm-arch').onclick=()=>{closeSheet();
    mutate(()=>{DATA.projects=(DATA.projects||[]).filter(x=>x.id!==id);},'/api/proj_archive',{id});};
  sheet.querySelector('#pm-del').onclick=()=>{closeSheet();projDel(id,p.name);};
}

// ─── стратегические цели (Мостик) ───
function _sgoal(id){return (DATA.sgoals||[]).find(g=>g.id===id);}
async function addSGoal(){
  const t=await uiPrompt('Стратегическая цель (крупно, на месяцы):','');
  if(!t||!t.trim())return;
  const target=await uiPrompt('Горизонт (напр. «до дек 2026», можно пусто):','');
  mutate(()=>{if(!DATA.sgoals)DATA.sgoals=[];DATA.sgoals.push({id:_tmpId(),text:t.trim(),target:(target||'').trim(),progress:0});},
    '/api/sgoal_add',{text:t.trim(),target:(target||'').trim()});
}
function openSGoal(id){
  const g=_sgoal(id);if(!g)return;
  closeSheet();
  const bg=document.createElement('div');bg.id='sheet-bg';bg.onclick=closeSheet;document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  const pct=Math.max(0,Math.min(100,g.progress||0));
  sheet.innerHTML='<div class="grab"></div>'+
    '<div class="stitle-row"><span class="title-edit-spacer"></span><div class="stitle">🎯 '+esc(g.text)+'</div><span class="title-edit-spacer"></span></div>'+
    '<div class="ssub">'+(g.target?'горизонт: '+esc(g.target):'горизонт не задан')+'</div>'+
    '<div class="slider-row" style="margin-top:14px"><div class="sl-top"><span>Прогресс</span><span class="val" id="sg-val">'+pct+'%</span></div>'+
    '<input type="range" min="0" max="100" step="5" value="'+pct+'" id="sg-prog" class="urg"></div>'+
    '<div class="sh-actions" style="flex-direction:column;gap:8px">'+
    '<button class="sh-btn" id="sg-done">🏆 Достигнута</button>'+
    '<button class="sh-btn" id="sg-ren">✏️ Название</button>'+
    '<button class="sh-btn" id="sg-target">📅 Горизонт</button>'+
    '<button class="sh-btn danger" id="sg-del">🗑 Удалить</button></div>';
  document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  _swipeDismiss(sheet,closeSheet);
  const slider=sheet.querySelector('#sg-prog'),val=sheet.querySelector('#sg-val');
  slider.oninput=()=>{val.textContent=slider.value+'%';};
  slider.onchange=()=>{const p=+slider.value;mutate(()=>{const x=_sgoal(id);if(x)x.progress=p;},'/api/sgoal_update',{id,progress:p});};
  sheet.querySelector('#sg-done').onclick=()=>{closeSheet();
    mutate(()=>{DATA.sgoals=(DATA.sgoals||[]).filter(x=>x.id!==id);},'/api/sgoal_update',{id,done:1});};
  sheet.querySelector('#sg-ren').onclick=async()=>{
    const t=await uiPrompt('Название цели:',g.text);
    if(t&&t.trim())mutate(()=>{const x=_sgoal(id);if(x)x.text=t.trim();},'/api/sgoal_update',{id,text:t.trim()});};
  sheet.querySelector('#sg-target').onclick=async()=>{
    const t=await uiPrompt('Горизонт (напр. «до дек 2026»):',g.target||'');
    if(t!==null)mutate(()=>{const x=_sgoal(id);if(x)x.target=t.trim();},'/api/sgoal_update',{id,target:t.trim()});};
  sheet.querySelector('#sg-del').onclick=()=>{closeSheet();
    mutate(()=>{DATA.sgoals=(DATA.sgoals||[]).filter(x=>x.id!==id);},'/api/sgoal_delete',{id});};
}

function renderMatrix(open){
  const m=document.getElementById('matrix');
  const W=m.clientWidth||340,H=344,PAD=30;
  let html='<div class="axis-v"></div><div class="axis-h"></div>'+
    '<div class="qc q1"><span class="em">🔴</span>Сейчас<span class="s">важно·срочно</span></div>'+
    '<div class="qc q2"><span class="em">🟡</span>Планируй<span class="s">важно·не срочно</span></div>'+
    '<div class="qc q3"><span class="em">🔵</span>Делегируй<span class="s">не важно·срочно</span></div>'+
    '<div class="qc q4"><span class="em">⚪</span>Удали<span class="s">не важно·не срочно</span></div>'+
    '<div class="axl" style="bottom:5px;left:50%;transform:translateX(-50%)">срочность →</div>'+
    '<div class="axl" style="left:4px;top:50%;transform:translateY(-50%) rotate(-90deg);transform-origin:left">важность →</div>';
  const rated=open.filter(c=>c.importance||c.urgency);
  rated.forEach(c=>{
    const x=PAD+(c.urgency/10)*(W-2*PAD);
    const y=H-PAD-(c.importance/10)*(H-2*PAD);
    const sz=13+Math.round((Math.max(c.importance,c.urgency)/10)*11);
    html+='<div class="dot '+quadClass(c.importance,c.urgency)+'" style="left:'+x+'px;top:'+y+'px;width:'+sz+'px;height:'+sz+'px" '+
      'onclick=\'openDotMenu(event,'+c.id+')\'></div>';
  });
  if(!rated.length){
    html+='<div class="axl" style="left:50%;top:50%;transform:translate(-50%,-50%);font-size:11px;letter-spacing:0;color:var(--faint)">оцени задачи — точки появятся здесь</div>';
  }
  m.innerHTML=html;
}

let _calRange='week';
function setCalRange(r){
  _calRange=r;
  document.querySelectorAll('#cal-seg .cs').forEach(b=>b.classList.toggle('on',b.dataset.r===r));
  renderCal();
}
function renderCal(){
  const now=new Date();const dow=(now.getDay()+6)%7;
  const mon=new Date(now);mon.setDate(now.getDate()-dow);mon.setHours(0,0,0,0);
  const todayISO=localISO(now);
  // границы выбранного диапазона: неделя (пн–вс) / месяц / год
  let start,end;
  if(_calRange==='month'){start=new Date(now.getFullYear(),now.getMonth(),1);end=new Date(now.getFullYear(),now.getMonth()+1,1);}
  else if(_calRange==='year'){start=new Date(now.getFullYear(),0,1);end=new Date(now.getFullYear()+1,0,1);}
  else {start=new Date(mon);end=new Date(mon);end.setDate(mon.getDate()+7);}
  const startISO=localISO(start),endISO=localISO(end);
  const dates=new Set();
  if(_calRange==='week'){for(let i=0;i<7;i++){const dd=new Date(mon);dd.setDate(mon.getDate()+i);const ds=localISO(dd);if(ds>=todayISO)dates.add(ds);}}
  DATA.cards.forEach(c=>{if(c.date&&c.date>=startISO&&c.date<endISO)dates.add(c.date);});
  const sorted=[...dates].sort();
  let html='';
  let curMonth=-1;
  for(const ds of sorted){
    const dd=new Date(ds+'T00:00');
    const evs=DATA.cards.filter(e=>e.date===ds);
    if(!evs.length)continue;
    // в режиме «год» — разделители по месяцам
    if(_calRange==='year'&&dd.getMonth()!==curMonth){curMonth=dd.getMonth();html+='<div class="cal-msep">'+MONTHS[curMonth]+'</div>';}
    const today=ds===todayISO;const past=ds<todayISO;
    const inWeek=dd>=mon&&(dd-mon)<7*864e5;
    const showMonth=_calRange!=='week'||!inWeek;
    const label=DOW[(dd.getDay()+6)%7]+' '+dd.getDate()+(showMonth?' '+MONTHS[dd.getMonth()]:'')+(past?' ⚠️':'')+(today?' · сегодня':'');
    html+='<div class="cell glass-sm '+(today?'today':'')+' '+(past?'past':'')+'">'+
      '<div class="cd"><span class="'+(today?'td':'')+'">'+label+'</span></div>'+
      evs.map(e=>{
        const tdata={kind:e.kind,id:e.id,text:e.text};
        if(e.kind==='event'){tdata.mb=e.morning_brief||0;tdata.proj=e.project_id||null;tdata.imp=e.importance||0;tdata.urg=e.urgency||0;}
        const mbDot=e.morning_brief?'<span style="font-size:9px;opacity:.7;margin-left:4px">🌅</span>':'';
        const cmtDot=e.comment?'<span class="cmt-dot" title="есть комментарий">💬</span>':'';
        let priDot='';
        if(e.kind==='event'&&(e.importance||e.urgency)){
          const q=quadClass(e.importance||0,e.urgency||0);
          const col=({r:'#ff9aa6',a:'#ffd07a',b:'#86b8ff',g:'var(--muted)'})[q]||'var(--muted)';
          priDot='<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:'+col+';margin-left:5px;flex-shrink:0;vertical-align:middle"></span>';
        }
        const tBadge=e.time?'<span class="t">'+e.time+(e.time_end?'–'+e.time_end:'')+'</span> ':'';
        return '<div class="ev '+(e.kind==='reminder'?'rem':'')+'" onclick=\'openTask('+JSON.stringify(tdata)+')\'>'+
          tBadge+esc(e.text)+mbDot+cmtDot+priDot+'</div>';
      }).join('')+'</div>';
  }
  const emptyMsg={week:'на этой неделе пусто',month:'в этом месяце пусто',year:'в этом году пусто'}[_calRange];
  document.getElementById('cal').innerHTML=html||'<div class="empty">'+emptyMsg+'</div>';
}

function renderFinance(){
  const d=DATA;
  document.getElementById('fin-cards').innerHTML=
    '<div class="fc cash glass"><span class="glow"></span><span class="ic">💵</span><div class="l">Нал</div><div class="v '+((d.cash||0)<0?'neg':'pos')+'">'+eur(d.cash||0)+'</div></div>'+
    '<div class="fc card glass"><span class="glow"></span><span class="ic">💳</span><div class="l">Карта</div><div class="v '+((d.card||0)<0?'neg':'pos')+'">'+eur(d.card||0)+'</div></div>'+
    '<div class="fc total glass"><span class="glow"></span><span class="ic">👛</span><div class="l">Всего</div><div class="v">'+eur(d.balance||0)+'</div></div>';
  // day summary
  const st=d.spend_today||[],sw=d.spend_week||[];
  const sumT=st.reduce((a,b)=>a+b.amount,0),sumW=sw.reduce((a,b)=>a+b.amount,0);
  const tlist=st.length?st.map(s=>'• '+esc(s.title)+' — '+eur(s.amount)).join('<br>'):'нет платежей';
  const wnames=[...new Set(sw.map(s=>s.title))].slice(0,4).join(' · ')||'нет платежей';
  document.getElementById('daysum').innerHTML=
    '<div class="ds today glass"><div class="l">📅 сегодня к оплате</div><div class="v">'+eur(sumT)+'</div><div class="mini">'+tlist+'</div></div>'+
    '<div class="ds glass"><div class="l">🗓 ближайшие 7 дней</div><div class="v">'+eur(sumW)+'</div><div class="mini">'+esc(wnames)+'</div></div>';
  // debts
  const cur=(d.debts||[]).filter(x=>x.kind==='current'),lng=(d.debts||[]).filter(x=>x.kind==='long');
  renderDebtChart(d);
  const curRem=cur.reduce((a,b)=>a+_rem(b),0);
  document.getElementById('cur-cnt').textContent=cur.length?cur.length+' · '+eur(curRem):'нет';
  document.getElementById('cur-debts').innerHTML=cur.length?cur.map(x=>{
    const u=_debtUrg(x);
    const pill=u.paid?'<span class="due-pill done">✓ погашен</span>':
      (u.pillText?'<span class="due-pill '+u.pillCls+'">'+u.pillText+'</span>':'');
    return '<div class="debt glass-sm '+(u.urg==='overdue'||u.urg==='urgent'?'soon':'')+(u.paid?' paidrow':'')+'" onclick="openDebt('+x.id+')">'+
      '<div class="nm"><div class="t">'+esc(x.name)+'</div>'+pill+'</div>'+
      '<div class="amt">'+eur(_rem(x))+'</div><span class="x" onclick="event.stopPropagation();delDebt('+x.id+')">×</span></div>';
  }).join(''):'<div class="empty">задолженностей нет 👍</div>';
  document.getElementById('long-cnt').textContent=lng.length||'нет';
  document.getElementById('long-debts').innerHTML=lng.length?lng.map(x=>{
    const pct=x.total?Math.round((x.paid||0)/x.total*100):0;const paid=pct>=100;
    return '<div class="ldebt glass-sm'+(paid?' paidrow':'')+'" onclick="openDebt('+x.id+')"><div class="lh"><span class="em">'+(paid?'✅':(x.icon||'🏦'))+'</span><span class="t">'+esc(x.name)+'</span>'+
      '<span class="p">'+pct+'%</span><span class="x" onclick="event.stopPropagation();delDebt('+x.id+')">×</span></div>'+
      '<div class="lbar"><div class="lfill" style="width:'+pct+'%"></div></div>'+
      '<div class="lm"><span>выплачено <b>'+eur(x.paid||0)+'</b> из '+eur(x.total)+'</span>'+(x.monthly?'<span>'+eur(x.monthly)+'/мес</span>':'')+'</div></div>';
  }).join(''):'<div class="empty">долгосрочных долгов нет</div>';
  // payments
  const pays=d.payments||[];
  const monthly=pays.filter(p=>p.kind==='recurring'&&p.recur==='monthly').reduce((a,b)=>a+b.amount,0);
  document.getElementById('pay-cnt').textContent=pays.length?pays.length+' · '+eur(monthly)+'/мес':'нет';
  document.getElementById('payments').innerHTML=pays.length?pays.map(p=>{
    let when=p.kind==='planned'?fmtDate(p.date):(p.recur==='weekly'?'каждый '+DOW[(p.day||0)%7]:p.day+' числа');
    return '<div class="recur glass-sm"><div class="ic">'+(p.icon||'💸')+'</div><div class="nm">'+esc(p.title)+'</div>'+
      '<div class="when">'+when+'</div><div class="amt">'+eur(p.amount)+'</div><span class="x" onclick="delPayment('+p.id+')">×</span></div>';
  }).join(''):'<div class="empty">платежей нет</div>';
  // log
  const log=d.fin_log||[];
  document.getElementById('fin-log').innerHTML=log.length?log.map(r=>{
    const a=r.amount||0;const acc=r.account==='cash'?'💵':'💳';
    const dt=(r.created_at||'').slice(5,10).replace('-','.');
    return '<div class="fl"><span class="amt '+(a>=0?'pos':'neg')+'">'+(a>=0?'+':'−')+Math.abs(a).toLocaleString('ru')+' €</span>'+
      '<span class="acc">'+acc+'</span><span class="cm">'+esc(r.comment||'')+'</span><span class="dt">'+dt+'</span>'+
      '<span class="x" onclick="finDel('+r.id+')">×</span></div>';
  }).join(''):'<div class="empty">операций пока нет</div>';
}
function fmtDate(s){if(!s)return '';const d=new Date(s+'T00:00');if(isNaN(d))return '';return d.getDate()+' '+MONTHS[d.getMonth()];}
function _debt(id){return (DATA.debts||[]).find(x=>x.id===id);}
function _rem(x){return Math.max(0,(x.total||0)-(x.paid||0));}
// Срочность долга: цвет по сроку/остатку, статус «погашен» по paid≥total
function _debtUrg(x){
  const rem=_rem(x);
  const paid=(x.total||0)>0&&rem<=0.005;
  let days=null;
  if(x.due_date){const d=new Date(x.due_date+'T00:00');if(!isNaN(d))days=Math.ceil((d-new Date())/864e5);}
  let urg='normal',pillText='',pillCls='ok';
  if(paid){urg='paid';}
  else if(days!==null){
    if(days<0){urg='overdue';pillText='⚠️ просрочено';pillCls='urg';}
    else if(days<=7){urg='urgent';pillText='⏳ до '+fmtDate(x.due_date)+' · '+days+' дн';pillCls='urg';}
    else if(days<=30){urg='soon';pillText='до '+fmtDate(x.due_date)+' · '+days+' дн';pillCls='soon';}
    else {urg='normal';pillText='до '+fmtDate(x.due_date);pillCls='ok';}
  }
  const col={overdue:'linear-gradient(180deg,#ff5566,#ff8895)',urgent:'linear-gradient(180deg,#ff6b7d,#ff9aa6)',
    soon:'linear-gradient(180deg,#ffb648,#ffd07a)',normal:'linear-gradient(180deg,#5b9dff,#86b8ff)',paid:'transparent'}[urg];
  return {rem,paid,days,urg,pillText,pillCls,col};
}
function renderDebtChart(d){
  const block=document.getElementById('debtchart-block');
  const debts=(d.debts||[]).slice();
  if(!debts.length){block.style.display='none';return;}
  block.style.display='block';
  // сортировка: срочные раньше, затем по остатку (крупные — выше и левее)
  const rank={overdue:0,urgent:1,soon:2,normal:3,paid:4};
  const arr=debts.map(x=>({x,u:_debtUrg(x)})).sort((a,b)=>(rank[a.u.urg]-rank[b.u.urg])||(b.u.rem-a.u.rem));
  const maxRem=Math.max(1,...arr.map(v=>v.u.rem));
  const totalRem=arr.reduce((s,v)=>s+v.u.rem,0);
  const openN=arr.filter(v=>!v.u.paid).length;
  document.getElementById('debt-total').textContent=eur(totalRem)+' · '+openN+' активных';
  document.getElementById('debtchart').innerHTML=arr.map(({x,u})=>{
    const h=u.paid?44:Math.round(24+(u.rem/maxRem)*104); // 24..128px
    const inner=u.paid?'<span class="chk">✓</span>':'';
    const amtLbl=u.paid?'':eur(u.rem).replace(/\s?€/,'');
    return '<div class="dbar" onclick="openDebt('+x.id+')">'+
      '<div class="dbar-amt">'+(u.paid?'✓':amtLbl)+'</div>'+
      '<div class="col '+u.urg+'" style="height:'+h+'px;'+(u.paid?'':'background:'+u.col)+'">'+inner+'</div>'+
      '<div class="nm">'+esc((x.name||'').replace(/ · \$$/,'')) +'</div></div>';
  }).join('');
}

// ─── project actions ───
function toggleProj(id){openProjects.has(id)?openProjects.delete(id):openProjects.add(id);render();}
async function addChaos(){
  const t=await uiPrompt('Новая задача / вводная:','',{placeholder:'что добавить в парковку'});
  if(!t||!t.trim())return;
  mutate(()=>{if(!DATA.chaos)DATA.chaos=[];DATA.chaos.unshift({id:_tmpId(),text:t.trim(),area:'other',priority:'mid',importance:0,urgency:0,done:0,project_id:null,position:-999999});},
    '/api/chaos_add',{text:t.trim()});
}

// ─── parking lot drag-to-reorder ───
let _dg=null;
function _startDrag(e,cid){
  e.preventDefault();e.stopPropagation();
  const row=e.currentTarget.closest('[data-cid]');
  if(!row)return;
  const container=document.getElementById('chaos');
  const rect=row.getBoundingClientRect();
  const startY=(e.touches?e.touches[0]:e).clientY;
  const clone=row.cloneNode(true);
  clone.style.cssText='position:fixed;left:'+rect.left+'px;top:'+rect.top+'px;width:'+rect.width+'px;z-index:999;pointer-events:none;opacity:.92;box-shadow:0 8px 32px rgba(0,0,0,.65);border-radius:15px;transition:none';
  document.body.appendChild(clone);
  row.classList.add('dragging');
  _dg={cid,row,container,clone,startY,rowTop:rect.top};
  document.addEventListener('touchmove',_moveDrag,{passive:false});
  document.addEventListener('touchend',_endDrag,{once:true});
  document.addEventListener('mousemove',_moveDrag);
  document.addEventListener('mouseup',_endDrag,{once:true});
}
function _moveDrag(e){
  if(!_dg)return;
  e.preventDefault();
  const y=(e.touches?e.touches[0]:e).clientY;
  const dy=y-_dg.startY;
  _dg.clone.style.top=(_dg.rowTop+dy)+'px';
  const myMid=_dg.rowTop+dy+_dg.clone.offsetHeight/2;
  const rows=[..._dg.container.querySelectorAll('[data-cid]')];
  let before=null;
  for(const r of rows){
    if(r===_dg.row)continue;
    const rr=r.getBoundingClientRect();
    if(myMid<rr.top+rr.height/2){before=r;break;}
  }
  if(before){_dg.container.insertBefore(_dg.row,before);}
  else if(_dg.row!==_dg.container.lastElementChild){_dg.container.appendChild(_dg.row);}
}
function _endDrag(){
  if(!_dg)return;
  document.removeEventListener('touchmove',_moveDrag);
  document.removeEventListener('mousemove',_moveDrag);
  _dg.clone.remove();
  _dg.row.classList.remove('dragging');
  const parkingIds=[..._dg.container.querySelectorAll('[data-cid]')].map(r=>parseInt(r.dataset.cid));
  const mp={};(DATA.chaos||[]).forEach(c=>mp[c.id]=c);
  const sorted=parkingIds.map(id=>mp[id]).filter(Boolean);
  const rest=(DATA.chaos||[]).filter(c=>!parkingIds.includes(c.id));
  DATA.chaos=[...sorted,...rest];
  // Send ALL non-done IDs so server positions stay consistent with client order
  const allIds=(DATA.chaos||[]).filter(c=>!c.done).map(c=>c.id);
  mutate(null,'/api/chaos_reorder',{ids:allIds});
  _dg=null;
}

// ─── project step drag-to-reorder / move between projects ───
let _sd=null;
function _startStepDrag(e,sid,pid){
  e.preventDefault();e.stopPropagation();
  const row=e.currentTarget.closest('[data-sid]');
  if(!row)return;
  const container=row.closest('.gsteps-rows');
  if(!container)return;
  const rect=row.getBoundingClientRect();
  const startY=(e.touches?e.touches[0]:e).clientY;
  const clone=row.cloneNode(true);
  clone.style.cssText='position:fixed;left:'+rect.left+'px;top:'+rect.top+'px;width:'+rect.width+'px;z-index:999;pointer-events:none;opacity:.9;box-shadow:0 8px 32px rgba(0,0,0,.65);border-radius:11px;transition:none';
  document.body.appendChild(clone);
  row.classList.add('dragging');
  _sd={sid,pid,row,container,clone,startY,rowTop:rect.top,targetContainer:container};
  document.addEventListener('touchmove',_moveStepDrag,{passive:false});
  document.addEventListener('touchend',_endStepDrag,{once:true});
  document.addEventListener('mousemove',_moveStepDrag);
  document.addEventListener('mouseup',_endStepDrag,{once:true});
}
function _moveStepDrag(e){
  if(!_sd)return;
  e.preventDefault();
  const y=(e.touches?e.touches[0]:e).clientY;
  const dy=y-_sd.startY;
  _sd.clone.style.top=(_sd.rowTop+dy)+'px';
  const myMid=_sd.rowTop+dy+_sd.clone.offsetHeight/2;
  const allContainers=[...document.querySelectorAll('.gsteps-rows[data-proj]')];
  let target=_sd.container;
  for(const c of allContainers){
    const cr=c.getBoundingClientRect();
    if(myMid>=cr.top-24&&myMid<=cr.bottom+24){target=c;break;}
  }
  allContainers.forEach(c=>c.classList.remove('drag-over'));
  if(target!==_sd.container)target.classList.add('drag-over');
  _sd.targetContainer=target;
  const rows=[...target.querySelectorAll('[data-sid]')];
  let before=null;
  for(const r of rows){
    if(r===_sd.row)continue;
    const rr=r.getBoundingClientRect();
    if(myMid<rr.top+rr.height/2){before=r;break;}
  }
  if(before)target.insertBefore(_sd.row,before);
  else target.appendChild(_sd.row);
}
function _endStepDrag(){
  if(!_sd)return;
  document.removeEventListener('touchmove',_moveStepDrag);
  document.removeEventListener('mousemove',_moveStepDrag);
  document.querySelectorAll('.gsteps-rows').forEach(c=>c.classList.remove('drag-over'));
  _sd.clone.remove();
  _sd.row.classList.remove('dragging');
  const tgt=_sd.targetContainer;
  const newPid=tgt?parseInt(tgt.dataset.proj):_sd.pid;
  const stepIds=[...tgt.querySelectorAll('[data-sid]')].map(r=>parseInt(r.dataset.sid));
  if(newPid!==_sd.pid){
    const op=_proj(_sd.pid);if(op)op.steps=op.steps.filter(s=>s.id!==_sd.sid);
    const np=_proj(newPid);const s=_step(_sd.sid);
    if(np&&s){s.project_id=newPid;np.steps.push(s);}
    mutate(null,'/api/step_move',{id:_sd.sid,project_id:newPid,ids:stepIds});
  } else {
    const proj=_proj(_sd.pid);
    if(proj){const mp={};proj.steps.forEach(s=>mp[s.id]=s);
      proj.steps=stepIds.map(id=>mp[id]).filter(Boolean).concat(proj.steps.filter(s=>!stepIds.includes(s.id)));}
    mutate(null,'/api/step_reorder',{project_id:_sd.pid,ids:stepIds});
  }
  _sd=null;
}

// ─── prioritization matrix dot menu ───
function openDotMenu(e,cid){
  e.stopPropagation();
  document.querySelectorAll('.dot-menu').forEach(m=>m.remove());
  const c=_chaos(cid);if(!c)return;
  const imp=c.importance||0,urg=c.urgency||0;
  const existingCard=(DATA.cards||[]).find(x=>x.chaos_id===cid&&x.kind==='event');
  const curDate=existingCard?existingCard.date:localISO(new Date());
  const curTime=existingCard?existingCard.time||'':'';
  const d=document.createElement('div');
  d.className='dot-menu';
  d.innerHTML='<div class="grab"></div>'+
    '<div class="dm-t">'+esc(c.text)+'</div>'+
    '<div class="slider-row"><div class="sl-top"><span>🔴 Важность</span><span class="val" id="dm-iv">'+imp+' / 10</span></div>'+
      '<input type="range" id="dm-imp" min="0" max="10" value="'+imp+'"></div>'+
    '<div class="slider-row"><div class="sl-top"><span>⚡ Срочность</span><span class="val" id="dm-uv">'+urg+' / 10</span></div>'+
      '<input type="range" id="dm-urg" min="0" max="10" value="'+urg+'"></div>'+
    '<div class="sh-quad" id="dm-quad"></div>'+
    '<div class="sh-actions" style="margin-top:10px"><button class="sh-btn prime" id="dm-rate">💾 Сохранить оценку</button></div>'+
    '<div class="sh-divider" style="margin:14px 0 10px"></div>'+
    '<div class="sh-pick-lbl" style="margin-bottom:8px">📅 Запланировать</div>'+
    '<div class="sh-picker">'+
      '<input type="date" id="dm-date" value="'+curDate+'">'+
      '<input type="time" id="dm-time" value="'+curTime+'">'+
      '<button id="dm-go">запланировать</button></div>'+
    '<div class="sh-actions" style="margin-top:14px">'+
      '<button class="sh-btn" id="dm-done">✅ выполнено</button>'+
      '<button class="sh-btn danger" id="dm-arch">🗑 архив</button></div>';
  document.body.appendChild(d);
  _swipeDismiss(d,()=>d.remove());
  const impEl=d.querySelector('#dm-imp'),urgEl=d.querySelector('#dm-urg'),quad=d.querySelector('#dm-quad');
  function updQuad(){
    const i=+impEl.value,u=+urgEl.value;
    d.querySelector('#dm-iv').textContent=i+' / 10';
    d.querySelector('#dm-uv').textContent=u+' / 10';
    const q=(i>=6&&u>=6)?['🔴 Делай сейчас','rgba(255,107,125,.16)','rgba(255,107,125,.4)','#ff9aa6']
      :(i>=6&&u<6)?['🟡 Запланируй','rgba(255,198,87,.16)','rgba(255,198,87,.4)','#ffd07a']
      :(i<6&&u>=6)?['🔵 Делегируй','rgba(91,157,255,.16)','rgba(91,157,255,.4)','#86b8ff']
      :['⚪ Не оценено','rgba(235,240,250,.08)','var(--rim)','var(--muted)'];
    quad.textContent=q[0];quad.style.background=q[1];quad.style.borderColor=q[2];quad.style.color=q[3];
  }
  impEl.oninput=updQuad;urgEl.oninput=updQuad;updQuad();
  d.querySelector('#dm-rate').onclick=()=>{
    const imp=+impEl.value,urg=+urgEl.value;
    d.remove();
    mutate(()=>{const x=_chaos(cid);if(x){x.importance=imp;x.urgency=urg;}(DATA.cards||[]).forEach(ev=>{if(ev.chaos_id===cid){ev.importance=imp;ev.urgency=urg;}});},'/api/rate',{id:cid,importance:imp,urgency:urg});
  };
  d.querySelector('#dm-go').onclick=()=>{
    const date=d.querySelector('#dm-date').value,time=d.querySelector('#dm-time').value||'';
    if(!date)return;
    d.remove();
    mutate(()=>{
      const x=_chaos(cid);if(!DATA.cards)DATA.cards=[];
      DATA.cards=DATA.cards.filter(ev=>ev.chaos_id!==cid||ev.kind!=='event');
      DATA.cards.push({kind:'event',id:_tmpId(),date,time,text:(x?x.text:c.text),chaos_id:cid,project_id:(x?x.project_id:null)||null,morning_brief:0,importance:0,urgency:0});
    },'/api/move',{kind:'chaos',id:cid,date,time});
  };
  d.querySelector('#dm-done').onclick=()=>{
    d.remove();
    mutate(()=>{const x=_chaos(cid);if(x)x.done=1;DATA.cards=(DATA.cards||[]).filter(ev=>ev.chaos_id!==cid);},'/api/complete',{kind:'chaos',id:cid});
  };
  d.querySelector('#dm-arch').onclick=()=>{
    d.remove();
    mutate(()=>{DATA.chaos=(DATA.chaos||[]).filter(x=>x.id!==cid);DATA.cards=(DATA.cards||[]).filter(x=>x.chaos_id!==cid);DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.chaos_id!==cid);},'/api/delete',{kind:'chaos',id:cid});
  };
  setTimeout(()=>{
    function h(ev){if(!d.contains(ev.target)){d.remove();document.removeEventListener('click',h);}}
    document.addEventListener('click',h);
  },80);
}

function stepToggle(id){
  const s=_step(id);if(!s)return;
  const pid=s.project_id;
  mutate(()=>{s.done=s.done?0:1;},'/api/step_toggle',{id});
  // Все пункты цели стали зелёными → спрашиваем, достигнута ли цель
  const p=_proj(pid);
  if(p&&p.steps.length&&p.steps.every(x=>x.done))_askGoalDone(pid);
}
async function _askGoalDone(pid){
  const p=_proj(pid);
  if(!p||!p.steps.length||!p.steps.every(x=>x.done))return;
  if(await uiConfirm('🎉 Цель достигнута?',{sub:p.name,ok:'🗄 В архив'})){
    mutate(()=>{DATA.projects=(DATA.projects||[]).filter(x=>x.id!==pid);},'/api/proj_archive',{id:pid});
  }
}
async function stepAdd(pid){const t=await uiPrompt('Новый шаг:','',{placeholder:'что сделать'});if(t&&t.trim()){const p=_proj(pid);mutate(()=>{if(p){if(!p.steps)p.steps=[];p.steps.push({id:_tmpId(),text:t.trim(),done:0,project_id:pid});}},'/api/step_add',{project_id:pid,text:t.trim()});}}
async function stepRename(id){const s=_step(id);if(!s)return;const t=await uiPrompt('Переименовать шаг:',s.text,{ok:'Сохранить'});if(t&&t.trim()){mutate(()=>{const x=_step(id);if(x)x.text=t.trim();},'/api/step_rename',{id,text:t.trim()});}}
async function stepComment(id){const s=_step(id);if(!s)return;const t=await uiPrompt('💬 Комментарий к шагу:',s.comment||'',{ok:'Сохранить',placeholder:'заметка…'});if(t===null)return;mutate(()=>{const x=_step(id);if(x)x.comment=t.trim();},'/api/card_comment',{kind:'step',id,comment:t.trim()});}
async function stepDelete(id){const s=_step(id);if(!s)return;if(await uiConfirm('Удалить шаг?',{sub:s.text,danger:true,ok:'Удалить'})){mutate(()=>{for(const p of (DATA.projects||[])){const i=(p.steps||[]).findIndex(x=>x.id===id);if(i>=0){p.steps.splice(i,1);break;}}},'/api/step_delete',{id});}}
async function projRename(id,old){const t=await uiPrompt('Название цели:',old);if(t&&t.trim()){const p=_proj(id);mutate(()=>{if(p)p.name=t.trim();},'/api/proj_rename',{id,name:t.trim()});}}
async function projDel(id,name){if(await uiConfirm('Удалить цель?',{sub:name,danger:true,ok:'Удалить'})){mutate(()=>{DATA.projects=(DATA.projects||[]).filter(p=>p.id!==id);},'/api/proj_delete',{id});}}
function projSetMorning(id,on){const p=_proj(id);mutate(()=>{if(p)p.morning_brief=on?1:0;},'/api/proj_set_morning',{id,on});}

// ─── finance actions ───
function finAdd(sign){
  const amt=parseFloat(document.getElementById('fin-amt').value);
  if(!amt||isNaN(amt)){document.getElementById('fin-amt').focus();return;}
  const account=document.getElementById('fin-acc').value;
  const comment=document.getElementById('fin-cm').value;
  const signed=Math.abs(amt)*sign;
  document.getElementById('fin-amt').value='';document.getElementById('fin-cm').value='';
  mutate(()=>{
    if(!DATA.fin_log)DATA.fin_log=[];
    DATA.fin_log.unshift({id:_tmpId(),amount:signed,account,comment:comment||'коррекция',created_at:new Date().toISOString()});
    if(account==='cash')DATA.cash=(DATA.cash||0)+signed; else DATA.card=(DATA.card||0)+signed;
    DATA.balance=(DATA.balance||0)+signed;
  },'/api/finance_add',{amount:signed,account,comment});
}
async function finDel(id){
  if(!(await uiConfirm('Удалить операцию?',{danger:true,ok:'Удалить'})))return;
  const op=_byId(DATA.fin_log,id);
  mutate(()=>{
    if(op){const a=op.amount||0;if(op.account==='cash')DATA.cash=(DATA.cash||0)-a;else DATA.card=(DATA.card||0)-a;DATA.balance=(DATA.balance||0)-a;}
    DATA.fin_log=(DATA.fin_log||[]).filter(r=>r.id!==id);
  },'/api/finance_delete',{id});
}
async function addDebt(kind){
  const name=await uiPrompt(kind==='long'?'Долгосрочный долг — название:':'Задолженность — название:','',{placeholder:'название'});
  if(!name||!name.trim())return;
  const total=parseFloat(await uiNum('Сумма €:',''))||0;
  let body;
  if(kind==='long'){
    const paid=parseFloat(await uiNum('Уже выплачено €:','0'))||0;
    const monthly=parseFloat(await uiNum('Платёж в месяц € (можно пусто):','0'))||0;
    body={name:name.trim(),kind:'long',total,paid,monthly,icon:'🏦'};
  } else {
    const due=await uiPrompt('Срок оплаты (можно пусто):','',{placeholder:'ГГГГ-ММ-ДД'});
    body={name:name.trim(),kind:'current',total,due_date:due&&due.trim()?due.trim():null,icon:'🔴'};
  }
  mutate(()=>{if(!DATA.debts)DATA.debts=[];DATA.debts.push({id:_tmpId(),paid:0,monthly:0,due_date:null,...body});},'/api/debt_add',body);
}
async function delDebt(id){if(await uiConfirm('Удалить долг?',{danger:true,ok:'Удалить'})){mutate(()=>{DATA.debts=(DATA.debts||[]).filter(x=>x.id!==id);},'/api/debt_delete',{id});}}
function openDebt(id){
  const x=_debt(id);if(!x)return;
  closeSheet();
  const bg=document.createElement('div');bg.id='sheet-bg';bg.onclick=closeSheet;document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  const u=_debtUrg(x);const pct=x.total?Math.round((x.paid||0)/x.total*100):0;
  const sub=u.paid?'✅ погашен полностью':('осталось '+eur(u.rem)+' из '+eur(x.total)+
    (u.pillText?' · '+u.pillText:''));
  sheet.innerHTML='<div class="grab"></div>'+
    '<div class="stitle-row"><span class="title-edit-spacer"></span><div class="stitle">'+(x.icon||'💳')+' '+esc(x.name)+'</div><span class="title-edit-spacer"></span></div>'+
    '<div class="ssub">'+sub+'</div>'+
    '<div class="lbar" style="margin:10px 0 4px"><div class="lfill" style="width:'+pct+'%"></div></div>'+
    (u.paid?'':'<div class="sh-comment-wrap"><div class="sh-comment-lbl">↩️ Возврат</div>'+
      '<div class="fin-row"><input class="fin-inp" id="debt-ret" type="number" inputmode="decimal" placeholder="сумма € (осталось '+eur(u.rem).replace(/\s?€/,'')+')"/>'+
      '<button class="fbtn in" id="debt-ret-go" style="flex:0 0 auto;padding:0 16px">записать</button></div></div>')+
    '<div class="sh-actions" style="flex-direction:column;gap:8px">'+
    '<button class="sh-btn" id="debt-name">✏️ Название</button>'+
    '<button class="sh-btn" id="debt-total">💶 Сумма долга</button>'+
    (x.kind==='current'?'<button class="sh-btn" id="debt-due">📅 Срок оплаты</button>':'<button class="sh-btn" id="debt-monthly">📆 Платёж в месяц</button>')+
    '<button class="sh-btn danger" id="debt-del">🗑 Удалить долг</button></div>';
  document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  _swipeDismiss(sheet,closeSheet);
  const retGo=sheet.querySelector('#debt-ret-go');
  if(retGo)retGo.onclick=()=>{
    const inp=sheet.querySelector('#debt-ret');const amt=parseFloat(inp.value)||0;
    if(amt<=0){inp.focus();return;}
    const newPaid=Math.min(x.total||((x.paid||0)+amt),(x.paid||0)+amt);
    closeSheet();
    mutate(()=>{const y=_debt(id);if(y)y.paid=newPaid;},'/api/debt_update',{id,paid:newPaid});
  };
  sheet.querySelector('#debt-name').onclick=async()=>{
    const t=await uiPrompt('Название долга:',x.name);
    if(t&&t.trim())mutate(()=>{const y=_debt(id);if(y)y.name=t.trim();},'/api/debt_update',{id,name:t.trim()});};
  sheet.querySelector('#debt-total').onclick=async()=>{
    const v=parseFloat(await uiNum('Сумма долга €:',String(x.total||0)));
    if(!isNaN(v))mutate(()=>{const y=_debt(id);if(y)y.total=v;},'/api/debt_update',{id,total:v});};
  const dueBtn=sheet.querySelector('#debt-due');
  if(dueBtn)dueBtn.onclick=async()=>{
    const t=await uiPrompt('Срок оплаты (ГГГГ-ММ-ДД, пусто — убрать):',x.due_date||'',{placeholder:'2026-08-01'});
    if(t!==null)mutate(()=>{const y=_debt(id);if(y)y.due_date=t.trim()||null;},'/api/debt_update',{id,due_date:t.trim()});};
  const mBtn=sheet.querySelector('#debt-monthly');
  if(mBtn)mBtn.onclick=async()=>{
    const v=parseFloat(await uiNum('Платёж в месяц €:',String(x.monthly||0)));
    if(!isNaN(v))mutate(()=>{const y=_debt(id);if(y)y.monthly=v;},'/api/debt_update',{id,monthly:v});};
  sheet.querySelector('#debt-del').onclick=()=>{closeSheet();delDebt(id);};
}
async function addPayment(){
  const title=await uiPrompt('Платёж — название:','',{placeholder:'за что'});
  if(!title||!title.trim())return;
  const amount=parseFloat(await uiNum('Сумма €:',''))||0;
  const isRec=await uiConfirm('Какой это платёж?',{ok:'🔁 Регулярный',cancel:'1️⃣ Разовый'});
  const icon=(await uiPrompt('Иконка (эмодзи):','💸'))||'💸';
  let body;
  if(isRec){
    const day=parseInt(await uiNum('Какого числа каждый месяц? (1-31):','1'))||1;
    body={title:title.trim(),amount,kind:'recurring',recur:'monthly',day,icon};
  } else {
    const date=await uiPrompt('Дата платежа:','',{placeholder:'ГГГГ-ММ-ДД'});
    body={title:title.trim(),amount,kind:'planned',date:date&&date.trim()?date.trim():null,icon};
  }
  mutate(()=>{if(!DATA.payments)DATA.payments=[];DATA.payments.push({id:_tmpId(),day:1,date:null,recur:'monthly',...body});},'/api/payment_add',body);
}
async function delPayment(id){if(await uiConfirm('Удалить платёж?',{danger:true,ok:'Удалить'})){mutate(()=>{DATA.payments=(DATA.payments||[]).filter(p=>p.id!==id);},'/api/payment_delete',{id});}}

// ─── bottom sheet (rate / move) ───
function closeSheet(){const s=document.getElementById('sheet');if(s)s.remove();const b=document.getElementById('sheet-bg');if(b)b.remove();}

// Универсальное «смахивание вниз» для любой нижней панели. Вешается на «ручку» (.grab),
// заголовок и саму панель (но не на интерактив — input/range/textarea/button/select),
// чтобы жест работал везде, где есть ползунок-полоска, как в нативных iOS-шторках.
function _swipeDismiss(sheet,closeFn){
  let sy=0,dragging=false;
  const onStart=e=>{
    const tg=e.target;
    if(tg.closest('input,textarea,select,button,.sh-day,.tog'))return;
    sy=e.touches[0].clientY;dragging=true;sheet.style.transition='none';
  };
  const onMove=e=>{
    if(!dragging)return;
    const dy=e.touches[0].clientY-sy;
    if(dy>0)sheet.style.transform='translateY('+dy+'px)';
  };
  const onEnd=e=>{
    if(!dragging)return;dragging=false;sheet.style.transition='';
    const dy=e.changedTouches[0].clientY-sy;
    if(dy>80){closeFn();}else{sheet.style.transform='translateY(0)';}
  };
  sheet.addEventListener('touchstart',onStart,{passive:true});
  sheet.addEventListener('touchmove',onMove,{passive:true});
  sheet.addEventListener('touchend',onEnd,{passive:true});
}

// Свои диалоги вместо prompt/confirm/alert — нативные отключены в standalone-PWA на iOS
function _openSheet(html){
  closeSheet();
  const bg=document.createElement('div');bg.id='sheet-bg';document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  sheet.innerHTML=html;document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  bg.onclick=closeSheet;
  _swipeDismiss(sheet,closeSheet);
  return {bg,sheet};
}

// ─── красивый «захват вводной»: вместо одной строки prompt — полноценная шторка ───
function openIdeaSheet(){
  closeSheet();
  const bg=document.createElement('div');bg.id='sheet-bg';bg.onclick=closeSheet;document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  sheet.innerHTML='<div class="grab"></div>'+
    '<div class="idea-h"><span class="idea-spark">💡</span><div>'+
      '<div class="stitle" style="text-align:left;margin:0">Новая вводная</div>'+
      '<div class="ssub" style="text-align:left">лови мысль — разложим её позже</div></div></div>'+
    '<textarea id="idea-txt" class="idea-txt" placeholder="Что пришло в голову?" rows="4"></textarea>'+
    '<div class="sched-row"><span class="sched-lbl">📅 Запланировать</span><div class="tog" id="sc-on"><div class="tog-k"></div></div></div>'+
    '<div id="sc-body" style="display:none">'+
      '<div class="sched-row"><span class="sched-lbl">Весь день</span><div class="tog" id="sc-allday"><div class="tog-k"></div></div></div>'+
      '<div class="sched-row"><span class="sched-lbl">Начало</span><div class="sched-inps"><input type="date" id="sc-date" value="'+localISO(new Date())+'"><input type="time" id="sc-t1"></div></div>'+
      '<div class="sched-row" id="sc-endrow"><span class="sched-lbl">Конец</span><div class="sched-inps"><input type="time" id="sc-t2"></div></div>'+
    '</div>'+
    '<button class="big-add" id="idea-save" style="margin-top:18px"><span class="ic">📌</span>Припарковать</button>';
  document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  _swipeDismiss(sheet,closeSheet);
  const txt=sheet.querySelector('#idea-txt');
  setTimeout(()=>{try{txt.focus();}catch(_){}},160);
  // блок планирования в стиле iOS-календаря: тумблер «Весь день», начало/конец
  let schedOn=false,allDay=false;
  const scOn=sheet.querySelector('#sc-on'),scBody=sheet.querySelector('#sc-body');
  const scAll=sheet.querySelector('#sc-allday'),scEndRow=sheet.querySelector('#sc-endrow');
  const t1=sheet.querySelector('#sc-t1'),t2=sheet.querySelector('#sc-t2');
  const saveBtn=sheet.querySelector('#idea-save');
  const updLabel=()=>{saveBtn.innerHTML='<span class="ic">'+(schedOn?'📅':'📌')+'</span>'+(schedOn?'В календарь':'Припарковать');};
  scOn.onclick=()=>{schedOn=!schedOn;scOn.classList.toggle('on',schedOn);scBody.style.display=schedOn?'':'none';updLabel();};
  scAll.onclick=()=>{allDay=!allDay;scAll.classList.toggle('on',allDay);t1.style.display=allDay?'none':'';scEndRow.style.display=allDay?'none':'';};
  // конец автоматически = начало + 1 час (как в iOS), пока не задан вручную
  t1.addEventListener('change',()=>{
    if(!t1.value)return;
    if(!t2.value||t2.value<=t1.value){
      const p=t1.value.split(':').map(Number);
      t2.value=String(Math.min(23,p[0]+1)).padStart(2,'0')+':'+String(p[1]).padStart(2,'0');
    }
  });
  const save=()=>{
    const v=(txt.value||'').trim();
    if(!v){txt.focus();return;}
    const date=schedOn?(sheet.querySelector('#sc-date').value||localISO(new Date())):'';
    const time=(schedOn&&!allDay)?(t1.value||''):'';
    const time_end=(schedOn&&!allDay&&time)?(t2.value||''):'';
    closeSheet();
    mutate(()=>{
      if(!DATA.chaos)DATA.chaos=[];
      const cid=_tmpId();
      DATA.chaos.unshift({id:cid,text:v,area:'other',priority:'mid',importance:0,urgency:0,done:0,project_id:null,position:-999999});
      if(date){if(!DATA.cards)DATA.cards=[];DATA.cards.push({kind:'event',id:_tmpId(),date,time,time_end,text:v,chaos_id:cid,project_id:null,morning_brief:0,importance:0,urgency:0});}
    },'/api/chaos_add',date?{text:v,area:'other',date,time,time_end}:{text:v,area:'other'});
  };
  sheet.querySelector('#idea-save').onclick=save;
  txt.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter')save();});
}
function uiPrompt(title,value='',opts={}){
  return new Promise(resolve=>{
    const sub=opts.sub?`<div class="ssub2">${esc(opts.sub)}</div>`:'';
    const {bg,sheet}=_openSheet(
      `<div class="grab"></div><div class="stitle">${esc(title)}</div>${sub}`+
      `<input id="ui-inp" class="ui-input" type="${opts.type||'text'}" inputmode="${opts.inputmode||'text'}" `+
      `placeholder="${esc(opts.placeholder||'')}" value="${esc(value==null?'':value)}">`+
      `<div class="sh-actions" style="margin-top:14px">`+
      `<button class="sh-btn" id="ui-cancel">Отмена</button>`+
      `<button class="sh-btn prime" id="ui-ok">${esc(opts.ok||'Готово')}</button></div>`);
    const inp=sheet.querySelector('#ui-inp');
    setTimeout(()=>{try{inp.focus();}catch(_){}}, 140);
    const done=v=>{closeSheet();resolve(v);};
    bg.onclick=()=>done(null);
    sheet.querySelector('#ui-cancel').onclick=()=>done(null);
    sheet.querySelector('#ui-ok').onclick=()=>done(inp.value);
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();done(inp.value);}});
  });
}
function uiConfirm(title,opts={}){
  return new Promise(resolve=>{
    const sub=opts.sub?`<div class="ssub2">${esc(opts.sub)}</div>`:'';
    const okCls=opts.danger?'danger':'prime';
    const {bg,sheet}=_openSheet(
      `<div class="grab"></div><div class="stitle">${esc(title)}</div>${sub}`+
      `<div class="sh-actions" style="margin-top:16px">`+
      `<button class="sh-btn" id="ui-cancel">${esc(opts.cancel||'Отмена')}</button>`+
      `<button class="sh-btn ${okCls}" id="ui-ok">${esc(opts.ok||'OK')}</button></div>`);
    const done=v=>{closeSheet();resolve(v);};
    bg.onclick=()=>done(false);
    sheet.querySelector('#ui-cancel').onclick=()=>done(false);
    sheet.querySelector('#ui-ok').onclick=()=>done(true);
  });
}
function uiAlert(msg,title){
  return new Promise(resolve=>{
    const {bg,sheet}=_openSheet(
      `<div class="grab"></div>`+(title?`<div class="stitle">${esc(title)}</div>`:'')+
      `<div class="ssub2" style="font-size:14px">${esc(msg)}</div>`+
      `<div class="sh-actions" style="margin-top:16px"><button class="sh-btn prime" id="ui-ok">Понятно</button></div>`);
    const done=()=>{closeSheet();resolve();};
    bg.onclick=done;sheet.querySelector('#ui-ok').onclick=done;
  });
}
async function uiNum(title,value,opts={}){
  const v=await uiPrompt(title,value,{...opts,type:'text',inputmode:'decimal'});
  return v;
}
function openTask(t){
  closeSheet();
  const now=new Date();
  const bg=document.createElement('div');bg.id='sheet-bg';bg.onclick=closeSheet;document.body.appendChild(bg);
  const sheet=document.createElement('div');sheet.id='sheet';sheet.className='glass';
  let dayBtns='';
  for(let i=0;i<8;i++){const dd=new Date(now);dd.setDate(now.getDate()+i);const ds=localISO(dd);
    const lbl=i===0?'сегодня':i===1?'завтра':DOW[(dd.getDay()+6)%7]+' '+dd.getDate();
    dayBtns+='<button class="sh-day" data-date="'+ds+'">'+lbl+'</button>';}
  let rateBlock='';
  if(t.kind==='chaos'||t.kind==='event'){
    const imp=t.imp||0,urg=t.urg||0;
    rateBlock='<div class="slider-row"><div class="sl-top"><span>🔴 Важность</span><span class="val" id="imp-val">'+imp+' / 10</span></div>'+
      '<input type="range" class="imp" id="imp" min="0" max="10" value="'+imp+'"></div>'+
      '<div class="slider-row"><div class="sl-top"><span>⚡ Срочность</span><span class="val" id="urg-val">'+urg+' / 10</span></div>'+
      '<input type="range" class="urg" id="urg" min="0" max="10" value="'+urg+'"></div>'+
      '<div class="sh-quad" id="quad"></div>'+
      '<div class="sh-actions"><button class="sh-btn prime" id="rate-save">💾 Сохранить оценку</button></div>'+
      '<div class="sh-divider"></div>';
  }
  // Project selector block (for both chaos and event)
  const projs=DATA.projects||[];
  const curProjId=t.proj||t.project_id||null;
  const projOpts='<option value="">— без проекта —</option>'+projs.map(p=>'<option value="'+p.id+'" '+(curProjId==p.id?'selected':'')+'>'+esc(p.name)+'</option>').join('');
  const projBlock='<div class="sh-proj-row"><span style="font-size:12px;color:var(--muted);font-weight:700;flex-shrink:0">📁 Проект:</span>'+
    '<select id="sh-proj" style="flex:1;min-width:0;max-width:100%;overflow:hidden;background:rgba(255,255,255,.06);border:1px solid var(--rim);border-radius:10px;color:#fff;font-size:13px;padding:6px 10px">'+projOpts+'</select></div>';
  const mbBlock='';
  // Comment block (both chaos and event)
  const curComment=((t.kind==='chaos'?(_chaos(t.id)||{}):(_card(t.id)||{})).comment)||'';
  const commentBlock='<div class="sh-comment-wrap"><div class="sh-comment-lbl">💬 Комментарий</div>'+
    '<textarea id="sh-comment" class="sh-comment" rows="2" placeholder="заметка к карточке…">'+esc(curComment)+'</textarea></div>';
  sheet.innerHTML='<div class="grab"></div>'+
    '<div class="stitle-row"><span class="title-edit-spacer"></span>'+
      '<div class="stitle">'+esc(t.text||'')+'</div>'+
      '<button id="sh-ren" class="title-edit-btn" title="Переименовать">✏️</button></div>'+
    '<div class="ssub">'+(t.kind==='chaos'?'оцени — точка встанет на матрицу, или запланируй день':'оцени приоритет / перенести / закрыть')+'</div>'+
    rateBlock+
    projBlock+mbBlock+commentBlock+
    '<div class="sh-divider"></div>'+
    '<div class="sh-days">'+dayBtns+'</div>'+
    '<div class="sh-pick-lbl">или выбери дату и время (начало · конец)</div>'+
    '<div class="sh-picker">'+
      '<input type="date" id="sh-date" value="'+((t.kind==='event'&&_card(t.id)&&_card(t.id).date)||localISO(now))+'">'+
      '<input type="time" id="sh-time" value="'+((t.kind==='event'&&_card(t.id)&&_card(t.id).time)||'')+'" title="Начало">'+
      '<input type="time" id="sh-time2" value="'+((t.kind==='event'&&_card(t.id)&&_card(t.id).time_end)||'')+'" title="Конец">'+
      '<button id="sh-go">📅</button></div>'+
    '<div class="sh-actions"><button class="sh-btn" id="sh-done">✅ выполнено</button>'+
    '<button class="sh-btn danger" id="sh-del">'+(t.kind==='chaos'?'🗑 удалить':'↩️ на парковку')+'</button></div>'+
    (t.kind==='event'?'<button class="sh-act sh-del" id="sh-evdel" style="margin-top:10px;width:100%">🗑 Удалить навсегда</button>':'');
  document.body.appendChild(sheet);
  requestAnimationFrame(()=>{sheet.style.transform='translateY(0)';sheet.style.opacity='1';});
  _swipeDismiss(sheet,closeSheet);

  if(t.kind==='chaos'||t.kind==='event'){
    const impEl=sheet.querySelector('#imp'),urgEl=sheet.querySelector('#urg'),quad=sheet.querySelector('#quad');
    function upd(){
      const i=+impEl.value,u=+urgEl.value;
      sheet.querySelector('#imp-val').textContent=i+' / 10';
      sheet.querySelector('#urg-val').textContent=u+' / 10';
      const q=(i>=6&&u>=6)?['🔴 Делай сейчас — важно и срочно','rgba(255,107,125,.16)','rgba(255,107,125,.4)','#ff9aa6']
        :(i>=6&&u<6)?['🟡 Запланируй — важно, не срочно','rgba(255,198,87,.16)','rgba(255,198,87,.4)','#ffd07a']
        :(i<6&&u>=6)?['🔵 Делегируй — не важно, срочно','rgba(91,157,255,.16)','rgba(91,157,255,.4)','#86b8ff']
        :['⚪ Оценка не задана','rgba(235,240,250,.08)','var(--rim)','var(--muted)'];
      quad.textContent=q[0];quad.style.background=q[1];quad.style.borderColor=q[2];quad.style.color=q[3];
    }
    impEl.oninput=upd;urgEl.oninput=upd;upd();
    sheet.querySelector('#rate-save').onclick=()=>{
      const imp=+impEl.value,urg=+urgEl.value;
      closeSheet();
      if(t.kind==='chaos'){
        mutate(()=>{const c=_chaos(t.id);if(c){c.importance=imp;c.urgency=urg;}(DATA.cards||[]).forEach(ev=>{if(ev.chaos_id===t.id){ev.importance=imp;ev.urgency=urg;}});},'/api/rate',{id:t.id,importance:imp,urgency:urg});
      } else {
        mutate(()=>{const card=_card(t.id);if(card){card.importance=imp;card.urgency=urg;if(card.chaos_id){const c=_chaos(card.chaos_id);if(c){c.importance=imp;c.urgency=urg;}}}},'/api/event_update',{id:t.id,importance:imp,urgency:urg});
      }
    };
  }
  // move to a date — mirrors api_move: chaos creates a calendar event, event/reminder reschedules.
  // Время читаем из предзаполненных полей: перенос дня сохраняет начало/конец,
  // осознанно очищенное поле снимает время (событие «на весь день»).
  function doMove(date){
    const time=(sheet.querySelector('#sh-time')||{}).value||'';
    let time_end=(sheet.querySelector('#sh-time2')||{}).value||'';
    if(!time)time_end='';
    closeSheet();
    mutate(()=>{
      if(t.kind==='chaos'){
        const c=_chaos(t.id);
        if(!DATA.cards)DATA.cards=[];
        DATA.cards.push({kind:'event',id:_tmpId(),date,time,time_end,text:(c?c.text:t.text),chaos_id:t.id,project_id:(c?c.project_id:null)||null,morning_brief:0});
      } else {
        const card=_card(t.id);if(card){card.date=date;if(t.kind==='event'){card.time=time;card.time_end=time_end;}}
      }
    },'/api/move',t.kind==='reminder'?{kind:t.kind,id:t.id,date}:{kind:t.kind,id:t.id,date,time,time_end});
  }
  sheet.querySelectorAll('.sh-day').forEach(b=>b.onclick=()=>doMove(b.dataset.date));
  // конец автоматически = начало + 1 час, если пуст или раньше начала
  const _t1=sheet.querySelector('#sh-time'),_t2=sheet.querySelector('#sh-time2');
  if(_t1&&_t2)_t1.addEventListener('change',()=>{
    if(!_t1.value)return;
    if(!_t2.value||_t2.value<=_t1.value){
      const p=_t1.value.split(':').map(Number);
      _t2.value=String(Math.min(23,p[0]+1)).padStart(2,'0')+':'+String(p[1]).padStart(2,'0');
    }
  });
  sheet.querySelector('#sh-go').onclick=()=>{
    const date=sheet.querySelector('#sh-date').value||localISO(now);
    doMove(date);
  };
  sheet.querySelector('#sh-done').onclick=()=>{
    closeSheet();
    mutate(()=>{
      if(t.kind==='chaos'){const c=_chaos(t.id);if(c)c.done=1;}
      else{
        if(t.kind==='event'){const card=_card(t.id);if(card&&card.chaos_id){const c=_chaos(card.chaos_id);if(c)c.done=1;}}
        DATA.cards=(DATA.cards||[]).filter(x=>x.id!==t.id);
      }
    },'/api/complete',{kind:t.kind,id:t.id});
  };
  sheet.querySelector('#sh-del').onclick=async()=>{
    if(t.kind==='chaos'&&!(await uiConfirm('Удалить задачу навсегда?',{danger:true,ok:'Удалить'})))return;
    closeSheet();
    mutate(()=>{
      if(t.kind==='chaos'){
        DATA.cards=(DATA.cards||[]).filter(x=>x.chaos_id!==t.id);
        DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.chaos_id!==t.id);
        DATA.chaos=(DATA.chaos||[]).filter(x=>x.id!==t.id);
      } else {
        DATA.cards=(DATA.cards||[]).filter(x=>x.id!==t.id);
      }
    },'/api/unplan',{kind:t.kind,id:t.id});
  };
  // Delete event permanently (with linked chaos task)
  const shEvDel=sheet.querySelector('#sh-evdel');
  if(shEvDel)shEvDel.onclick=async()=>{
    if(!(await uiConfirm('Удалить событие навсегда?',{danger:true,ok:'Удалить'})))return;
    closeSheet();
    mutate(()=>{
      const chaosId=(_card(t.id)||{}).chaos_id||null;
      DATA.cards=(DATA.cards||[]).filter(x=>x.id!==t.id);
      if(chaosId){
        DATA.chaos=(DATA.chaos||[]).filter(x=>x.id!==chaosId);
        DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.chaos_id!==chaosId);
      }
    },'/api/event_delete',{id:t.id});
  };
  // Переименование по карандашику — логика как в проектах (uiPrompt). Работает и для
  // вводной (chaos), и для события календаря (event). Шторка остаётся открытой, имя в ней
  // обновляется на месте.
  const shRen=sheet.querySelector('#sh-ren');
  if(shRen)shRen.onclick=async()=>{
    const nv=await uiPrompt('Переименовать:',t.text);
    if(!nv||!nv.trim())return;
    const val=nv.trim();
    t.text=val;
    const st=sheet.querySelector('.stitle');if(st)st.textContent=val;
    if(t.kind==='chaos'){
      mutate(()=>{const c=_chaos(t.id);if(c)c.text=val;},'/api/chaos_rename',{id:t.id,text:val});
    } else if(t.kind==='event'){
      mutate(()=>{const card=_card(t.id);if(card)card.text=val;
        if(card&&card.chaos_id){const c=_chaos(card.chaos_id);if(c)c.text=val;}},
        '/api/event_update',{id:t.id,text:val});
    }
  };
  // Project selector — save on change (sheet stays open; page repaints behind it)
  const shProj=sheet.querySelector('#sh-proj');
  if(shProj){
    shProj.onchange=()=>{
      const pid=shProj.value?parseInt(shProj.value):null;
      if(t.kind==='event'){
        mutate(()=>{const card=_card(t.id);if(card)card.project_id=pid;},'/api/event_update',{id:t.id,project_id:pid});
      } else if(t.kind==='chaos'){
        mutate(()=>{const c=_chaos(t.id);if(c)c.project_id=pid;},'/api/chaos_set_project',{id:t.id,project_id:pid});
      }
    };
  }
  // Comment — save on blur / change (sheet stays open)
  const shComment=sheet.querySelector('#sh-comment');
  if(shComment){
    let last=curComment;
    const saveComment=()=>{
      const v=shComment.value;
      if(v===last)return;
      last=v;
      mutate(()=>{const o=(t.kind==='chaos'?_chaos(t.id):_card(t.id));if(o)o.comment=v;},
        '/api/card_comment',{kind:t.kind,id:t.id,comment:v});
    };
    shComment.addEventListener('blur',saveComment);
    shComment.addEventListener('change',saveComment);
  }
}

// ─── KANBAN ───
function spawnConfetti(x,y){
  const colors=['#5b9dff','#52e08a','#ffd07a','#ff9aa6','#b18bff','#41e3d4','#ff7ac0','#fff'];
  const shapes=[4,5,6,7,8];
  for(let i=0;i<38;i++){
    const p=document.createElement('div');p.className='confetti-particle';
    const angle=Math.random()*Math.PI*2,dist=60+Math.random()*120;
    const w=5+Math.random()*6,h=w*(Math.random()<.5?.4:1);
    const rot=(Math.random()-0.5)*720;
    p.style.cssText=`width:${w}px;height:${h}px;background:${colors[i%colors.length]};`+
      `border-radius:${Math.random()<.5?'50%':'2px'};left:${x}px;top:${y}px;`+
      `--dx:${Math.cos(angle)*dist}px;--dy:${Math.sin(angle)*dist-40}px;--dr:${rot}deg;`+
      `animation-delay:${i*22}ms;animation-duration:${0.9+Math.random()*.5}s`;
    document.body.appendChild(p);setTimeout(()=>p.remove(),1600);
  }
}

const MONTHS_SHORT=['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
function fmtDeadline(dl){
  if(!dl)return null;
  const d=new Date(dl+'T00:00'),now=new Date();
  const days=Math.ceil((d-now)/864e5);
  const label=d.getDate()+' '+MONTHS_SHORT[d.getMonth()];
  if(days<0)return {cls:'overdue',text:'⚠️ просрочен · '+label};
  if(days<=5)return {cls:'soon',text:'⏳ '+label+' · '+days+'д'};
  return {cls:'ok',text:'📅 '+label};
}

function renderKanban(d){
  const cols=d.kanban_cols||[];
  const cards=d.kanban_cards||[];
  const kb=document.getElementById('kanban');
  kb.innerHTML=cols.map(col=>{
    const cc=cards.filter(c=>c.column_id===col.id);
    const isCurrent=col.status==='current';
    const dl=fmtDeadline(col.deadline);
    const dlHtml=dl?`<div class="kdl ${dl.cls}" onclick="kcolMenu(event,${col.id})">${dl.text}</div>`:'';
    const cardsHtml=cc.map(c=>{
      const done=c.checked?'done':'';
      return `<div class="kcard ${done}" onclick="kcardClick(event,${c.id},${col.id},this)">
        <button class="kren" onclick="krename(event,${c.id},this)" title="Переименовать">✏️</button>
        <div class="kt">${esc(c.title)}${c.comment?'<span class="cmt-dot" title="есть комментарий">💬</span>':''}</div>
        ${c.description?`<div class="kdesc">${esc(c.description)}</div>`:''}
        ${c.comment?`<div class="kdesc kcmt-prev">💬 ${esc(c.comment)}</div>`:''}
      </div>`;
    }).join('');
    return `<div class="kol${isCurrent?' current':''}" data-col-id="${col.id}">
      <div class="kol-head" onclick="kcolMenu(event,${col.id})">
        <div class="kh-dot" style="background:${col.color}"></div>
        <div class="kh-name">${esc(col.name)}</div>
        <div class="kh-cnt">${cc.length}</div>
        <div class="kh-more">···</div>
      </div>
      ${dlHtml}
      ${cardsHtml}
      <button class="kadd" onclick="kaddCard(${col.id},'${esc(col.name)}')">＋ карточка</button>
    </div>`;
  }).join('');
  renderKArchive(d);
}

function renderKArchive(d){
  const arch=d.kanban_archived||[];
  const cnt=document.getElementById('arch-cnt');
  const box=document.getElementById('arch-cards');
  if(!box)return;
  if(cnt)cnt.textContent=arch.length;
  if(!arch.length){box.innerHTML='<div style="opacity:.4;font-size:13px;padding:10px 2px">архив пуст</div>';return;}
  const colName=id=>{const c=(d.kanban_cols||[]).find(x=>x.id===id);return c?c.name:'';};
  box.innerHTML=arch.map(c=>`<div class="karch-row" style="display:flex;align-items:center;gap:10px;padding:11px 12px;background:rgba(255,255,255,.05);border:1px solid var(--rim);border-radius:14px;margin-bottom:8px">
    <div style="flex:1;min-width:0">
      <div style="font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.title)}</div>
      ${colName(c.column_id)?`<div style="font-size:11px;color:var(--muted);margin-top:2px">${esc(colName(c.column_id))}</div>`:''}
    </div>
    <button class="kren" style="position:static;flex-shrink:0" title="Вернуть из архива" onclick="kunarchive(${c.id})">↩️</button>
    <button class="kren" style="position:static;flex-shrink:0" title="Удалить навсегда" onclick="kdelArch(${c.id})">🗑</button>
  </div>`).join('');
}

function kunarchive(id){
  mutate(()=>{
    const c=(DATA.kanban_archived||[]).find(x=>x.id===id);
    if(c){
      DATA.kanban_archived=DATA.kanban_archived.filter(x=>x.id!==id);
      const cols=DATA.kanban_cols||[];
      const exists=cols.some(x=>x.id===c.column_id);
      if(!exists&&cols.length)c.column_id=cols[0].id;
      c.archived=0;
      (DATA.kanban_cards=DATA.kanban_cards||[]).push(c);
    }
  },'/api/kcard_unarchive',{id},()=>renderKanban(DATA));
}
async function kdelArch(id){
  if(!(await uiConfirm('Удалить карточку навсегда?',{danger:true,ok:'Удалить'})))return;
  mutate(()=>{DATA.kanban_archived=(DATA.kanban_archived||[]).filter(x=>x.id!==id);},'/api/kcard_delete',{id},()=>renderKanban(DATA));
}

function kcolMenu(e,colId){
  e.stopPropagation();
  const col=(DATA.kanban_cols||[]).find(c=>c.id===colId);
  if(!col)return;
  const isCurrent=col.status==='current';
  const togOn=isCurrent?'on':'';
  const {sheet}=_openSheet(
    `<div class="grab"></div>`+
    `<div class="stitle" style="margin-bottom:4px">${esc(col.name)}</div>`+
    `<div style="display:flex;flex-direction:column;gap:14px;margin-top:16px">`+
    // status toggle
    `<div style="display:flex;align-items:center;gap:12px;padding:14px 16px;background:rgba(255,255,255,.06);border-radius:16px">
       <span class="ptlabel${!isCurrent?' on':''}">Перспективный</span>
       <div class="tog ${togOn}" id="kcol-tog" style="flex-shrink:0"><div class="tog-k"></div></div>
       <span class="ptlabel${isCurrent?' on':''}">Текущий</span>
       <button class="kren" id="kcol-del-btn" title="Удалить проект" style="position:static;margin-left:auto;flex-shrink:0">🗑</button>
     </div>`+
    // deadline
    (()=>{
      const dv=col.deadline||'';
      const dlabel=dv?(()=>{const d=new Date(dv+'T00:00');return d.getDate()+' '+['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][d.getMonth()]+' '+d.getFullYear();})():'не задан';
      return `<div style="padding:12px 16px;background:rgba(255,255,255,.06);border-radius:16px">
       <div style="font-size:11px;font-weight:800;color:var(--muted);letter-spacing:.5px;margin-bottom:10px">📅 ДЕДЛАЙН ПРОЕКТА</div>
       <div style="display:flex;gap:8px;align-items:center">
         <div style="position:relative;flex:1">
           <div id="dl-label" style="padding:10px 14px;background:rgba(255,255,255,.08);border:1px solid ${dv?'rgba(255,208,122,.4)':'var(--rim)'};border-radius:12px;font-size:14px;font-weight:700;color:${dv?'#ffd07a':'var(--muted)'};pointer-events:none">${dlabel}</div>
           <input id="kcol-dl" type="date" value="${dv}" style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer">
         </div>
         ${dv?`<button id="dl-clear" style="padding:10px 12px;background:rgba(255,107,125,.12);border:1px solid rgba(255,107,125,.3);border-radius:12px;color:#ff9aa6;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap">✕ сброс</button>`:''}
       </div>
     </div>`;
    })()+
    // rename
    `<button class="sh-act" id="kcol-ren-btn">✏️ Переименовать список</button>`+
    `</div>`
  );
  // toggle logic
  const tog=sheet.querySelector('#kcol-tog');
  tog.onclick=()=>{
    const nowCurrent=!tog.classList.contains('on');
    tog.classList.toggle('on');
    sheet.querySelector('.ptlabel:first-of-type').classList.toggle('on',!tog.classList.contains('on'));
    sheet.querySelector('.ptlabel:last-of-type').classList.toggle('on',tog.classList.contains('on'));
    const newStatus=nowCurrent?'current':'prospective';
    if(newStatus==='current'){
      const rect=tog.getBoundingClientRect();
      spawnConfetti(rect.left+rect.width/2,rect.top+rect.height/2);
    }
    mutate(()=>{const c=_kcol(colId);if(c)c.status=newStatus;},'/api/kcol_setstatus',{id:colId,status:newStatus},()=>renderKanban(DATA));
  };
  // deadline
  const dlInput=sheet.querySelector('#kcol-dl');
  const dlLabel=sheet.querySelector('#dl-label');
  if(dlInput){
    dlInput.onchange=async(ev)=>{
      const val=ev.target.value;
      if(dlLabel){
        if(val){
          const d=new Date(val+'T00:00');
          const months=['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
          dlLabel.textContent=d.getDate()+' '+months[d.getMonth()]+' '+d.getFullYear();
          dlLabel.style.color='#ffd07a';dlLabel.style.borderColor='rgba(255,208,122,.4)';
        }else{dlLabel.textContent='не задан';dlLabel.style.color='var(--muted)';dlLabel.style.borderColor='var(--rim)';}
      }
      mutate(()=>{const c=_kcol(colId);if(c)c.deadline=val||null;},'/api/kcol_setdeadline',{id:colId,deadline:val||null},()=>renderKanban(DATA));
    };
  }
  const dlClear=sheet.querySelector('#dl-clear');
  if(dlClear)dlClear.onclick=()=>{
    if(dlInput)dlInput.value='';
    if(dlLabel){dlLabel.textContent='не задан';dlLabel.style.color='var(--muted)';dlLabel.style.borderColor='var(--rim)';}
    dlClear.remove();
    mutate(()=>{const c=_kcol(colId);if(c)c.deadline=null;},'/api/kcol_setdeadline',{id:colId,deadline:null},()=>renderKanban(DATA));
  };
  // rename
  sheet.querySelector('#kcol-ren-btn').onclick=async()=>{
    const nv=await uiPrompt('Название списка:',col.name);
    if(!nv||!nv.trim())return;
    closeSheet();
    mutate(()=>{const c=_kcol(colId);if(c)c.name=nv.trim();},'/api/kcol_rename',{id:colId,name:nv.trim()},()=>renderKanban(DATA));
  };
  // delete project (list)
  sheet.querySelector('#kcol-del-btn').onclick=async()=>{
    const cnt=(DATA.kanban_cards||[]).filter(c=>c.column_id===colId&&!c.archived).length;
    const msg=cnt?`Удалить проект «${col.name}» и его карточек: ${cnt}?`:`Удалить проект «${col.name}»?`;
    if(!(await uiConfirm(msg,{danger:true,ok:'Удалить'})))return;
    closeSheet();
    mutate(()=>{
      DATA.kanban_cols=(DATA.kanban_cols||[]).filter(x=>x.id!==colId);
      DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.column_id!==colId);
    },'/api/kcol_delete',{id:colId},()=>renderKanban(DATA));
  };
}

function kcheck(e,id,val){e.stopPropagation();mutate(()=>{const c=_kcard(id);if(c)c.checked=val;},'/api/kcard_check',{id,checked:val},()=>renderKanban(DATA));}
function _karchLocal(id){const c=_kcard(id);DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.id!==id);if(c){c.archived=1;(DATA.kanban_archived=DATA.kanban_archived||[]).unshift(c);}}
async function karchive(e,id){e.stopPropagation();if(!(await uiConfirm('Отправить в архив?',{ok:'В архив'})))return;mutate(()=>_karchLocal(id),'/api/kcard_archive',{id},()=>renderKanban(DATA));}
async function krename(e,id,btn){
  e.stopPropagation();
  const title=btn.closest('.kcard').querySelector('.kt').textContent;
  const nv=await uiPrompt('Новое название:',title);
  if(!nv||!nv.trim())return;
  mutate(()=>{const c=_kcard(id);if(c)c.title=nv.trim();},'/api/kcard_rename',{id,title:nv.trim()},()=>renderKanban(DATA));
}
function kcardClick(e,id,colId,el){
  if(e.target.closest('.kren,.kol-head'))return;
  e.stopPropagation();
  const title=el.querySelector('.kt').textContent;
  const hasCols=(DATA.kanban_cols||[]).length>1;
  const kc=_kcard(id)||{};
  const curC=kc.comment||'';
  const {sheet}=_openSheet(`<div class="grab"></div><div class="stitle">${esc(title)}</div>`+
    `<div class="sh-comment-wrap"><div class="sh-comment-lbl">💬 Комментарий</div>`+
    `<textarea id="kcmt" class="sh-comment" rows="2" placeholder="заметка к карточке…">${esc(curC)}</textarea></div>`+
    `<div style="display:flex;flex-direction:column;gap:10px;margin-top:14px">`+
    `<button class="sh-act" id="kren-btn">✏️ Переименовать</button>`+
    (hasCols?`<button class="sh-act" id="kmove-open-btn">↗ Переместить на доску</button>`:'')+
    `<button class="sh-act" id="karch-btn">📦 В архив</button>`+
    `<button class="sh-act sh-del" id="kdel-btn">🗑 Удалить навсегда</button></div>`);
  const kcmt=sheet.querySelector('#kcmt');
  if(kcmt){
    let last=curC;
    const save=()=>{const v=kcmt.value;if(v===last)return;last=v;
      mutate(()=>{const c=_kcard(id);if(c)c.comment=v;},'/api/card_comment',{kind:'kcard',id,comment:v},()=>renderKanban(DATA));};
    kcmt.addEventListener('blur',save);kcmt.addEventListener('change',save);
  }
  if(hasCols) sheet.querySelector('#kmove-open-btn').onclick=()=>{closeSheet();_openKMoveSheet(id,colId,title);};
  sheet.querySelector('#kren-btn').onclick=async()=>{
    const nv=await uiPrompt('Новое название:',title);
    if(!nv||!nv.trim())return;
    closeSheet();
    mutate(()=>{const c=_kcard(id);if(c)c.title=nv.trim();},'/api/kcard_rename',{id,title:nv.trim()},()=>renderKanban(DATA));
  };
  sheet.querySelector('#karch-btn').onclick=async()=>{
    if(!(await uiConfirm('Отправить в архив?',{ok:'В архив'})))return;
    closeSheet();
    mutate(()=>_karchLocal(id),'/api/kcard_archive',{id},()=>renderKanban(DATA));
  };
  sheet.querySelector('#kdel-btn').onclick=async()=>{
    if(!(await uiConfirm('Удалить карточку навсегда?',{danger:true,ok:'Удалить'})))return;
    closeSheet();
    mutate(()=>{DATA.kanban_cards=(DATA.kanban_cards||[]).filter(x=>x.id!==id);},'/api/kcard_delete',{id},()=>renderKanban(DATA));
  };
}
function _openKMoveSheet(cardId,currentColId,cardTitle){
  const cols=DATA.kanban_cols||[];
  const cards=DATA.kanban_cards||[];
  const rows=cols.map(col=>{
    const cnt=cards.filter(c=>c.column_id===col.id&&!c.archived).length;
    const cur=col.id===currentColId;
    return `<button class="sh-act kmove-col" data-col="${col.id}" `+
      `style="display:flex;align-items:center;gap:12px;justify-content:flex-start;${cur?'opacity:.4;pointer-events:none':''}">`+
      `<span style="width:12px;height:12px;border-radius:50%;background:${col.color};flex-shrink:0"></span>`+
      `<span style="flex:1;text-align:left">${esc(col.name)}</span>`+
      `<span style="font-size:12px;color:var(--muted);min-width:18px;text-align:right">${cnt}</span>`+
      `${cur?'<span style="font-size:15px;margin-left:4px">✓</span>':''}</button>`;
  }).join('');
  const {sheet}=_openSheet(
    `<div class="grab"></div>`+
    `<div style="font-size:11px;font-weight:800;letter-spacing:.6px;color:var(--muted);margin:0 2px 10px">ПЕРЕМЕСТИТЬ КАРТОЧКУ</div>`+
    `<div class="stitle" style="font-size:15px;margin-bottom:16px;text-align:left">${esc(cardTitle)}</div>`+
    `<div style="display:flex;flex-direction:column;gap:8px">${rows}</div>`
  );
  sheet.querySelectorAll('.kmove-col').forEach(btn=>{
    btn.onclick=()=>{
      const target=parseInt(btn.dataset.col,10);
      closeSheet();
      mutate(()=>{const c=_kcard(cardId);if(c)c.column_id=target;},'/api/kcard_move',{id:cardId,col:target},()=>renderKanban(DATA));
    };
  });
}

async function kaddCard(colId,colName){
  const t=await uiPrompt(`Новая карточка в «${colName}»:`,'',{placeholder:'заголовок'});
  if(!t||!t.trim())return;
  const desc=(await uiPrompt('Описание (необязательно):',''))||'';
  mutate(()=>{
    if(!DATA.kanban_cards)DATA.kanban_cards=[];
    DATA.kanban_cards.push({id:_tmpId(),column_id:colId,title:t.trim(),description:desc.trim(),checked:0,archived:0,position:9999});
  },'/api/kcard_add',{col:colId,title:t.trim(),desc:desc.trim()},()=>renderKanban(DATA));
}
async function addKCol(){
  const n=await uiPrompt('Название новой колонки:','',{placeholder:'например: Готово'});
  if(!n||!n.trim())return;
  mutate(()=>{
    if(!DATA.kanban_cols)DATA.kanban_cols=[];
    DATA.kanban_cols.push({id:_tmpId(),name:n.trim(),color:'#5b9dff',status:'prospective',position:9999,deadline:null});
  },'/api/kcol_add',{name:n.trim()},()=>renderKanban(DATA));
}

// ─── HAPPINESS ───
const H_KEYS=['work','friendship','health','wellbeing','hobby','love'];
const H_LABELS={work:'Работа',friendship:'Дружба',health:'Здоровье',wellbeing:'Благополучие',hobby:'Хобби',love:'Любовь'};
const H_COLORS={work:'#5b9dff',friendship:'#ff7ac0',health:'#52e08a',love:'#ff6b7d',wellbeing:'#ffd07a',hobby:'#b18bff'};
// H_NODES computed dynamically in updateHNodes() for equal pixel distances
let hValues={work:3,friendship:3,health:3,wellbeing:3,hobby:3,love:3};
let hPeriod='7';
let _hapHistory=[];

function renderHappiness(d){
  const h=d.happiness||{};
  hValues={work:h.work||3,friendship:h.friendship||3,health:h.health||3,
    wellbeing:h.wellbeing||3,hobby:h.hobby||3,love:h.love||3};
  _hapHistory=d.happiness_history||[];
  updateHNodes();
  requestAnimationFrame(drawHLines);
  drawHChart(_hapHistory);
}

function updateHNodes(){
  let minVal=5;
  // Pixel-equidistant positions: all nodes at same px distance from center.
  // Reference = health/love: 43% of container width horizontally.
  const wrap=document.getElementById('hmap-wrap');
  const W=(wrap&&wrap.offsetWidth)||390,HP=(wrap&&wrap.offsetHeight)||420;
  const Rpx=0.43*W;                      // target pixel radius
  const dxp=Rpx/W/Math.SQRT2*100;        // % of width  for 45° corners
  const dyp=Rpx/HP/Math.SQRT2*100;       // % of height for 45° corners
  const POS={
    work:       {maxL:50+dxp, maxT:50-dyp},
    friendship: {maxL:50-dxp, maxT:50-dyp},
    health:     {maxL:93,     maxT:50},
    love:       {maxL:7,      maxT:50},
    wellbeing:  {maxL:50+dxp, maxT:50+dyp},
    hobby:      {maxL:50-dxp, maxT:50+dyp}
  };
  H_KEYS.forEach(k=>{
    const el=document.getElementById('hv-'+k);
    if(el){el.textContent=hValues[k];el.style.color=H_COLORS[k];if(hValues[k]<minVal)minVal=hValues[k];}
    const n=POS[k];
    if(n){
      const t=Math.max(0.05,Math.sqrt(hValues[k]/5));
      const node=document.getElementById('hn-'+k);
      if(node){node.style.left=(50+(n.maxL-50)*t)+'%';node.style.top=(50+(n.maxT-50)*t)+'%';}
    }
  });
  const tc=document.getElementById('hv-total');
  if(tc){tc.textContent=minVal.toFixed(1);tc.style.color='#ffd07a';}
}

function drawHLines(){
  const svg=document.getElementById('hmap-lines');
  if(!svg)return;
  const wrap=document.getElementById('hmap-wrap');
  const wRect=wrap.getBoundingClientRect();
  if(!wRect.width||!wRect.height)return;
  const scX=300/wRect.width,scY=360/wRect.height;
  function svgPt(id){
    const hc=document.querySelector('#hn-'+id+' .hc');
    if(!hc)return null;
    const r=hc.getBoundingClientRect();
    return{x:((r.left-wRect.left)+r.width/2)*scX,y:((r.top-wRect.top)+r.height/2)*scY};
  }
  const center=svgPt('center');
  if(!center)return;
  const cx=center.x.toFixed(1),cy=center.y.toFixed(1);
  svg.innerHTML='<defs>'+
    '<filter id="hgl1" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="9"/></filter>'+
    '<filter id="hgl2" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3"/></filter>'+
    '</defs>'+
    H_KEYS.map(k=>{
      const p=svgPt(k);if(!p)return'';
      const c=H_COLORS[k];const xs=p.x.toFixed(1),ys=p.y.toFixed(1);
      return`<line x1="${cx}" y1="${cy}" x2="${xs}" y2="${ys}" stroke="${c}" stroke-width="20" stroke-opacity="0.11" filter="url(#hgl1)"/>`+
            `<line x1="${cx}" y1="${cy}" x2="${xs}" y2="${ys}" stroke="${c}" stroke-width="4.5" stroke-opacity="0.30" filter="url(#hgl2)"/>`+
            `<line x1="${cx}" y1="${cy}" x2="${xs}" y2="${ys}" stroke="${c}" stroke-width="1.5" stroke-opacity="0.95"/>`;
    }).join('');
}

function filterHHistory(history,period){
  if(!history||!history.length)return[];
  const now=new Date(),cut=new Date(now);
  if(period==='7')cut.setDate(now.getDate()-7);
  else if(period==='14')cut.setDate(now.getDate()-14);
  else if(period==='month')cut.setMonth(now.getMonth()-1);
  else if(period==='year')cut.setFullYear(now.getFullYear()-1);
  return history.filter(r=>r.logged_at&&new Date(r.logged_at)>=cut);
}

function drawHChart(history){
  const canvas=document.getElementById('hchart');
  if(!canvas)return;
  const leg=document.getElementById('hchart-legend');
  if(leg)leg.innerHTML=H_KEYS.map(k=>`<div class="hcl"><div class="hcld" style="background:${H_COLORS[k]}"></div>${H_LABELS[k]}</div>`).join('');
  // Use real offsetWidth; if hidden (0), defer until next frame
  const realW=canvas.offsetWidth;
  if(!realW){requestAnimationFrame(()=>drawHChart(history));return;}
  canvas.width=realW*2;canvas.height=200;
  const ctx=canvas.getContext('2d');
  const w=canvas.width,h=canvas.height,pad=20;
  ctx.clearRect(0,0,w,h);
  let filtered=filterHHistory(history,hPeriod);
  let label=null;
  if(!filtered.length&&history&&history.length){
    // show all available data with a note
    filtered=history.slice().slice(0,60);
    label='все данные';
  }
  if(!filtered.length){
    ctx.fillStyle='rgba(235,240,250,.22)';
    ctx.font=`bold ${w/25}px -apple-system,sans-serif`;
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillText('нет данных — нажми ⭐ чтобы сохранить',w/2,h/2);
    return;
  }
  ctx.strokeStyle='rgba(255,255,255,.05)';ctx.lineWidth=1;
  for(let i=1;i<=5;i++){const y=pad+(h-2*pad)*(1-i/5);ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  // y-axis labels
  ctx.fillStyle='rgba(235,240,250,.3)';ctx.font=`${w/35}px -apple-system,sans-serif`;ctx.textAlign='right';
  for(let i=1;i<=5;i++){const y=pad+(h-2*pad)*(1-i/5);ctx.fillText(i,pad-4,y+4);}
  if(label){
    ctx.fillStyle='rgba(235,240,250,.25)';ctx.font=`bold ${w/28}px -apple-system,sans-serif`;
    ctx.textAlign='center';ctx.fillText(label,w/2,pad/2+4);
  }
  const n=filtered.length;
  const rev=filtered.slice().reverse();
  H_KEYS.forEach(k=>{
    ctx.strokeStyle=H_COLORS[k];ctx.lineWidth=3;ctx.lineJoin='round';ctx.lineCap='round';
    ctx.beginPath();
    rev.forEach((row,i)=>{
      const x=pad+(w-2*pad)*i/(n-1||1);
      const y=pad+(h-2*pad)*(1-(row[k]||3)/5);
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    });
    ctx.stroke();
    if(n<=20){
      rev.forEach((row,i)=>{
        const x=pad+(w-2*pad)*i/(n-1||1);
        const y=pad+(h-2*pad)*(1-(row[k]||3)/5);
        ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);
        ctx.fillStyle=H_COLORS[k];ctx.fill();
      });
    }
  });
}

document.addEventListener('click',e=>{
  const btn=e.target.closest('.hper-btn');
  if(!btn)return;
  document.querySelectorAll('.hper-btn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  hPeriod=btn.dataset.p;
  drawHChart(_hapHistory);
});

function showDrumPicker(label,color,current,cb){
  const ex=document.getElementById('drum-sheet');if(ex)ex.remove();
  const sheet=document.createElement('div');
  sheet.id='drum-sheet';sheet.className='drum-sheet';
  const nums=Array.from({length:5},(_,i)=>i+1);
  sheet.innerHTML=
    '<div class="drum-inner">'+
    '<div class="drum-hdr">'+
    '<span class="dm-cancel">Отмена</span>'+
    '<span class="dm-title" style="color:'+color+'">'+label+'</span>'+
    '<span class="dm-ok">Готово</span>'+
    '</div>'+
    '<div class="drum-body">'+
    '<div class="drum-sel"></div>'+
    '<div class="drum-scroll" id="drum-scroll">'+
    '<div class="drum-pad"></div>'+
    nums.map(v=>'<div class="drum-item">'+v+'</div>').join('')+
    '<div class="drum-pad"></div>'+
    '</div></div></div>';
  document.body.appendChild(sheet);
  const scroll=sheet.querySelector('#drum-scroll');
  function highlight(){
    const idx=Math.round(scroll.scrollTop/55);
    scroll.querySelectorAll('.drum-item').forEach((el,i)=>{
      if(i===idx){el.classList.add('sel');el.style.color=color;}
      else{el.classList.remove('sel');el.style.color='';}
    });
  }
  requestAnimationFrame(()=>{scroll.scrollTop=(current-1)*55;highlight();});
  scroll.addEventListener('scroll',highlight,{passive:true});
  sheet.querySelector('.dm-ok').onclick=()=>{
    const val=Math.max(1,Math.min(5,Math.round(scroll.scrollTop/55)+1));
    sheet.remove();cb(val);
  };
  sheet.querySelector('.dm-cancel').onclick=()=>sheet.remove();
  sheet.addEventListener('click',e=>{if(e.target===sheet)sheet.remove();});
}

// hValues — локальный аккумулятор оценок. Чтобы новая оценка НИКОГДА не перезаписывала
// остальные узлы устаревшими значениями («каждое следующее изменение откатывало
// предыдущее»), после каждого сохранения пересинхронизируем hValues с авторитетным
// снимком сервера, а payload собираем явно из всех шести ключей.
function _hapSync(){const h=(DATA&&DATA.happiness)||{};H_KEYS.forEach(k=>{if(h[k]!=null)hValues[k]=Number(h[k]);});}
function _hapBody(extra){const h=(DATA&&DATA.happiness)||{};const b=Object.assign({note:''},extra||{});H_KEYS.forEach(k=>b[k]=(h[k]!=null?Number(h[k]):hValues[k]));return b;}

function editHNode(key){
  showDrumPicker(H_LABELS[key],H_COLORS[key],hValues[key],val=>{
    hValues[key]=val;
    if(!DATA.happiness)DATA.happiness={};
    DATA.happiness[key]=val;
    updateHNodes();
    requestAnimationFrame(drawHLines);
    mutate(null,'/api/happiness_save',_hapBody(),()=>{_hapSync();updateHNodes();requestAnimationFrame(drawHLines);});
  });
}

async function editHappiness(){
  const note=(await uiPrompt('Заметка о настроении (необязательно):','',{placeholder:'как ты сейчас'}))||'';
  mutate(null,'/api/happiness_save',_hapBody({note}),()=>{_hapSync();updateHNodes();requestAnimationFrame(drawHLines);});
}

// Блокировка при каждом сворачивании окна — при возврате снова рисуем круг
let _wasHidden=false;
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
    _wasHidden=true;
    try{navigator.sendBeacon('/api/lock');}catch(_){fetch('/api/lock',{method:'POST',keepalive:true});}
  }else if(_wasHidden){
    location.reload();
  }
});
window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});

// Потяни вниз для обновления (pull-to-refresh) — работает и в standalone-режиме
(function(){
  const ptr=document.getElementById('ptr'),ind=ptr.querySelector('.i');
  const TH=50;let startY=0,pulling=false,dist=0,busy=false;
  function resetPtr(){pulling=false;dist=0;ptr.style.transition='transform .25s,opacity .25s';ptr.style.transform='translate(-50%,-60px)';ptr.style.opacity=0;}
  window.addEventListener('touchstart',e=>{
    // КОРЕНЬ ОТКАТА ОЦЕНОК СЧАСТЬЯ: барабан-пикер имеет id 'drum-sheet', а проверялся
    // только 'sheet'. Поэтому прокрутка барабана перехватывалась pull-to-refresh, и на
    // отпускании срабатывал load()+render()+renderHappiness — он сбрасывал узлы свежим
    // снимком прямо посреди правки, и предыдущая оценка «возвращалась на место».
    if(busy||document.getElementById('sheet')||document.getElementById('drum-sheet'))return;
    if(window.scrollY<=0){startY=e.touches[0].clientY;pulling=true;dist=0;}
  },{passive:true});
  window.addEventListener('touchmove',e=>{
    if(!pulling)return;
    dist=e.touches[0].clientY-startY;
    if(dist<=0){resetPtr();return;}
    const d=Math.min(dist,120);
    ptr.style.transition='none';
    ptr.style.opacity=Math.min(d/TH,1);
    ptr.style.transform='translate(-50%,'+(d*0.55-46)+'px)';
    ind.style.transform='rotate('+(d/TH*270)+'deg)';
  },{passive:true});
  window.addEventListener('touchcancel',resetPtr,{passive:true});
  window.addEventListener('touchend',async()=>{
    if(!pulling)return;
    const triggered=dist>=TH;
    pulling=false;
    ptr.style.transition='transform .3s cubic-bezier(.2,.8,.2,1),opacity .3s';
    if(triggered){
      busy=true;
      ptr.style.transform='translate(-50%,14px)';ptr.style.opacity=1;
      ind.style.transform='';ptr.classList.add('spin');
      try{await load();}catch(_){}
      await new Promise(r=>setTimeout(r,380));
      ptr.classList.remove('spin');busy=false;
    }
    ptr.style.transform='translate(-50%,-60px)';ptr.style.opacity=0;
  },{passive:true});
})();

load();
// НЕТ фонового авто-опроса, который перерисовывал бы весь экран. Раньше именно он через
// несколько секунд подменял свежую правку устаревшим снимком («появилось → исчезло»).
// Данные обновляются только при старте, pull-to-refresh и в ответе самой мутации —
// и каждый такой снимок защищён ревизией (_revOK). Изменения с бота подхватятся при
// pull-to-refresh или возврате на вкладку (reload).
// Keepalive: держим сессию живой даже при открытом диалоге/крутилке. Только пингует
// сервер (обновляет _last_seen), НЕ применяет данные к экрану — откатить ничего не может.
setInterval(()=>{if(!document.hidden)fetch('/api/data?_t='+Date.now(),{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});},20000);
</script></body></html>"""


LOCK_PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>•</title>
<style>
html,body{margin:0;height:100%;background:#000;overflow:hidden;overscroll-behavior:none;touch-action:none;-webkit-user-select:none;user-select:none}
#dot{position:fixed;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;background:#fff;
  box-shadow:0 0 22px 6px rgba(255,255,255,.45);animation:pulse 2.6s ease-in-out infinite;z-index:1}
@keyframes pulse{0%,100%{transform:scale(1);opacity:.8}50%{transform:scale(1.5);opacity:1}}
#ink{position:fixed;inset:0;z-index:2;width:100%;height:100%;pointer-events:none;transition:opacity .6s}
#hint{position:fixed;left:0;right:0;bottom:calc(40px + env(safe-area-inset-bottom));text-align:center;
  color:rgba(255,255,255,.18);font-family:-apple-system,sans-serif;font-size:13px;font-weight:500;
  letter-spacing:.5px;z-index:1;transition:opacity 1s;pointer-events:none}
#surface{position:fixed;inset:0;z-index:4;touch-action:none;background:transparent}
#flash{position:fixed;inset:0;background:#fff;opacity:0;z-index:5;pointer-events:none;transition:opacity .45s}
</style></head>
<body>
<div id="dot"></div>
<svg id="ink" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- мягкое облако распыла (overspray) -->
    <filter id="mist" x="-130%" y="-130%" width="360%" height="360%"><feGaussianBlur stdDeviation="6.5"/></filter>
    <!-- лёгкое тело струи -->
    <filter id="body" x="-90%" y="-90%" width="280%" height="280%"><feGaussianBlur stdDeviation="3"/></filter>
    <!-- плотные края — почти резкие -->
    <filter id="edge" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="1"/></filter>
  </defs>
  <g id="mistL"></g>
  <g id="bodyL"></g>
  <g id="edgeL"></g>
  <g id="dripL"></g>
</svg>
<div id="hint">обведи точку</div>
<div id="surface"></div>
<div id="flash"></div>
<script>
const NS='http://www.w3.org/2000/svg';
const hint=document.getElementById('hint'),ink=document.getElementById('ink'),
      mistL=document.getElementById('mistL'),bodyL=document.getElementById('bodyL'),
      edgeL=document.getElementById('edgeL'),dripL=document.getElementById('dripL'),
      surface=document.getElementById('surface');
// матовый красный баллон — без неона
const R='208,22,16', RD='150,10,8', RH='234,52,38';
const rgba=(rgb,a)=>`rgba(${rgb},${a})`;
let drawing=false,pts=[],busy=false,lastXY=null,lastT=0,drips=[],raf=0;

function pt(e){const t=(e.touches&&e.touches[0])?e.touches[0]:e;return[t.clientX,t.clientY];}
function circ(layer,x,y,r,fill,filter){
  const c=document.createElementNS(NS,'circle');
  c.setAttribute('cx',x.toFixed(1));c.setAttribute('cy',y.toFixed(1));
  c.setAttribute('r',r.toFixed(1));c.setAttribute('fill',fill);
  if(filter)c.setAttribute('filter',filter);
  layer.appendChild(c);return c;
}

// ── подтёки: капля сползает вниз с ускорением, оставляя тонкий след ──
function spawnDrip(x,y,w){
  if(drips.filter(d=>!d.done).length>16)return;
  const ln=document.createElementNS(NS,'line');
  ln.setAttribute('x1',x.toFixed(1));ln.setAttribute('y1',y.toFixed(1));
  ln.setAttribute('x2',x.toFixed(1));ln.setAttribute('y2',y.toFixed(1));
  ln.setAttribute('stroke',rgba(R,0.8));ln.setAttribute('stroke-width',Math.max(1.6,w*0.42).toFixed(1));
  ln.setAttribute('stroke-linecap','round');
  dripL.appendChild(ln);
  const hd=circ(dripL,x,y,Math.max(1.8,w*0.55),rgba(R,0.9),'url(#edge)');
  drips.push({x,y0:y,y,vy:0.2+Math.random()*0.3,
              maxLen:18+Math.random()*150,ln,hd,done:false});
  if(!raf)raf=requestAnimationFrame(tick);
}
function tick(){
  let alive=false;
  for(const d of drips){
    if(d.done)continue;
    d.vy=Math.min(d.vy+0.05,2.6);d.y+=d.vy;
    if(d.y-d.y0>=d.maxLen){d.y=d.y0+d.maxLen;d.done=true;}else alive=true;
    d.ln.setAttribute('y2',d.y.toFixed(1));d.hd.setAttribute('cy',d.y.toFixed(1));
  }
  raf=alive?requestAnimationFrame(tick):0;
}

// ── один «пшик» фэткэпа вдоль струи ──
function spray(x,y){
  const now=performance.now();
  let hw=12,speed=0,nx=0,ny=1;
  if(lastXY){
    const dx=x-lastXY[0],dy=y-lastXY[1],dist=Math.hypot(dx,dy)||1;
    speed=dist/Math.max(6,now-lastT);                 // px/ms
    nx=-dy/dist;ny=dx/dist;                            // нормаль к движению
  }
  hw=Math.max(4,Math.min(15,14-speed*1.7));            // медленно→широко, быстро→узко
  // 1) overspray-туман вокруг струи (редко, чтоб не зашумлять)
  if(Math.random()<0.55)
    circ(mistL,x,y,hw*2.4,rgba(RD,(0.05+Math.random()*0.05).toFixed(3)),'url(#mist)');
  // 2) пустоватое тело по центру — еле заметное
  circ(bodyL,x,y,hw*0.9,rgba(R,(0.07+Math.random()*0.05).toFixed(3)),'url(#body)');
  // 3) ПЛОТНЫЕ КРАЯ струи — две «рельсы» по нормали
  for(const s of [hw,-hw]){
    circ(edgeL,x+nx*s,y+ny*s,2.4+Math.random()*1.3,
         rgba(Math.random()<0.3?RH:R,(0.72+Math.random()*0.2).toFixed(2)),'url(#edge)');
  }
  // 4) зернистость распыла в центре — редкие сухие точки
  const grains=1+(Math.random()*2|0);
  for(let i=0;i<grains;i++){
    const t=(Math.random()*2-1)*hw*0.75, a=(Math.random()*2-1)*hw*0.4;
    circ(edgeL,x+nx*t-ny*a*0,y+ny*t+nx*a,0.4+Math.random()*1.2,
         rgba(R,(0.15+Math.random()*0.25).toFixed(2)),null);
  }
  // 5) подтёк — где ведёшь медленно и широко, краска копится и течёт
  if(speed<0.45 && Math.random()<0.08*(hw/15))
    spawnDrip(x+(Math.random()*2-1)*hw*0.4, y+hw*0.6, hw);
  lastXY=[x,y];lastT=now;
}

function splat(x,y){           // первичный «плевок» при нажатии клапана
  for(let i=0;i<9;i++){
    const ang=Math.random()*Math.PI*2,d=2+Math.random()*16,sr=0.5+Math.random()*2.6;
    circ(edgeL,x+Math.cos(ang)*d,y+Math.sin(ang)*d,sr,
         rgba(R,(0.2+Math.random()*0.35).toFixed(2)),null);
  }
}
function clearAll(){mistL.innerHTML='';bodyL.innerHTML='';edgeL.innerHTML='';dripL.innerHTML='';
  drips=[];if(raf){cancelAnimationFrame(raf);raf=0;}}

function start(e){if(busy)return;e.preventDefault();
  drawing=true;ink.style.opacity=1;clearAll();pts=[];lastXY=null;lastT=performance.now();
  const p=pt(e);pts.push(p);splat(p[0],p[1]);spray(p[0],p[1]);hint.style.opacity=0;}
function move(e){if(!drawing||busy)return;e.preventDefault();
  const p=pt(e),lp=pts[pts.length-1];
  if(lp&&Math.hypot(p[0]-lp[0],p[1]-lp[1])<2.5)return;
  pts.push(p);spray(p[0],p[1]);}
async function end(e){if(!drawing||busy)return;e.preventDefault();drawing=false;
  if(pts.length<10){fade();return;}
  busy=true;
  try{
    const r=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({points:pts})});
    const j=await r.json();
    if(j.ok){success();return;}
  }catch(_){}
  busy=false;fade();}

function fade(){ink.style.opacity=0;
  setTimeout(()=>{clearAll();pts=[];lastXY=null;ink.style.opacity=1;hint.style.opacity='';},640);}
function success(){const f=document.getElementById('flash'),d=document.getElementById('dot');
  d.style.transition='transform .45s,opacity .45s';d.style.transform='scale(28)';d.style.opacity=0;
  f.style.opacity=1;setTimeout(()=>location.replace('/'),460);}
surface.addEventListener('touchstart',start,{passive:false});
surface.addEventListener('touchmove',move,{passive:false});
surface.addEventListener('touchend',end,{passive:false});
surface.addEventListener('touchcancel',end,{passive:false});
surface.addEventListener('mousedown',start);
surface.addEventListener('mousemove',move);
surface.addEventListener('mouseup',end);
document.addEventListener('contextmenu',e=>e.preventDefault());
</script></body></html>"""


def _set_session(payload):
    if is_circle((payload or {}).get("points") or []):
        return {"ok": True}
    return {"ok": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _authed(self):
        global _last_seen
        cookie = self.headers.get("Cookie", "") or ""
        has_token = any(
            part.strip().partition("=")[0] == "dash"
            and part.strip().partition("=")[2] == SESSION_TOKEN
            for part in cookie.split(";")
        )
        if not has_token:
            return False
        now = time.time()
        if (now - _last_seen) > IDLE_TIMEOUT:
            return False  # давно нет активности (или рестарт сервера) → снова рисуем круг
        _last_seen = now
        return True

    def _send(self, body, ctype, extra_headers=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        # запрет кэширования — iOS на домашнем экране иначе показывает старую версию
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        for h, v in (extra_headers or []):
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if not self._authed():
            # для API отвечаем 401, чтобы клиент перезагрузился на экран-замок
            if path.startswith("/api/"):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # любой обычный путь без сессии → экран-замок (рисуй круг)
            self._send(LOCK_PAGE.encode(), "text/html; charset=utf-8")
            return
        if path == "/api/data":
            self._send(json.dumps(get_data(), ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
        else:
            # вшиваем данные прямо в HTML — браузеру не нужен второй запрос
            try:
                data_json = json.dumps(get_data(), ensure_ascii=False)
                page = (PAGE.replace("__VERSION__", VERSION)
                            .replace("window.__INIT__=null",
                                     "window.__INIT__=" + data_json))
            except Exception:
                page = PAGE.replace("__VERSION__", VERSION)
            self._send(page.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length)) if length else {}

        # разблокировка кругом — единственный POST без сессии
        if path == "/api/unlock":
            global _last_seen
            result = _set_session(payload)
            extra = None
            if result.get("ok"):
                _last_seen = time.time()  # запускаем отсчёт бездействия заново
                # сессионная cookie (без Max-Age) — пропадает при закрытии вкладки
                extra = [("Set-Cookie",
                          f"dash={SESSION_TOKEN}; Path=/; SameSite=Lax; HttpOnly")]
            self._send(json.dumps(result).encode(), "application/json; charset=utf-8", extra)
            return

        # блокировка при сворачивании окна — гасим cookie и сбрасываем активность
        if path == "/api/lock":
            _last_seen = 0.0
            extra = [("Set-Cookie", "dash=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly")]
            self._send(b'{"ok":true}', "application/json; charset=utf-8", extra)
            return

        if not self._authed():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # Данные отдаём и по POST — ответы на POST Safari/iOS НИКОГДА не кэширует,
        # поэтому фоновый опрос и pull-to-refresh всегда получают свежий снимок.
        if path == "/api/data":
            self._send(json.dumps(get_data(), ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
            return

        routes = {
            "/api/move": api_move, "/api/unplan": api_unplan, "/api/complete": api_complete,
            "/api/rate": api_rate,
            "/api/finance_add": api_finance_add, "/api/finance_delete": api_finance_delete,
            "/api/debt_add": api_debt_add, "/api/debt_delete": api_debt_delete,
            "/api/debt_update": api_debt_update,
            "/api/payment_add": api_payment_add, "/api/payment_delete": api_payment_delete,
            "/api/kcard_add": api_kcard_add, "/api/kcard_check": api_kcard_check,
            "/api/kcard_archive": api_kcard_archive, "/api/kcard_unarchive": api_kcard_unarchive,
            "/api/kcard_delete": api_kcard_delete,
            "/api/kcard_move": api_kcard_move,
            "/api/kcard_rename": api_kcard_rename, "/api/kcol_add": api_kcol_add,
            "/api/kcol_setstatus": api_kcol_setstatus, "/api/kcol_setdeadline": api_kcol_setdeadline,
            "/api/kcol_rename": api_kcol_rename, "/api/kcol_delete": api_kcol_delete,
            "/api/happiness_save": api_happiness_save,
            "/api/chaos_add": api_chaos_add, "/api/chaos_rename": api_chaos_rename,
            "/api/chaos_reorder": api_chaos_reorder,
            "/api/event_delete": api_event_delete, "/api/event_update": api_event_update,
            "/api/chaos_set_project": api_chaos_set_project,
            "/api/proj_set_morning": api_proj_set_morning,
            "/api/card_comment": api_card_comment,
            "/api/sgoal_add": api_sgoal_add, "/api/sgoal_update": api_sgoal_update,
            "/api/sgoal_delete": api_sgoal_delete,
        }
        if path in routes:
            result = routes[path](payload)
        elif path in ("/api/step_toggle", "/api/step_delete", "/api/step_add",
                      "/api/step_rename", "/api/proj_rename", "/api/proj_delete",
                      "/api/proj_archive", "/api/step_reorder", "/api/step_move",
                      "/api/proj_add"):
            result = api_steps(path, payload)
        else:
            result = {"ok": False}
        if not isinstance(result, dict):
            result = {"ok": True}
        # Каждая мутация двигает ревизию вперёд и возвращает свежий авторитетный снимок
        # с новым rev. Клиент применит его, а любой устаревший снимок с меньшим rev
        # отбросит — изменение подтверждается самой записью и не может «исчезнуть».
        try:
            bump_rev()
            result["data"] = get_data()
        except Exception:
            pass
        self._send(json.dumps(result, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")


if __name__ == "__main__":
    print(f"Дашборд: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
