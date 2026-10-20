"""
Хранилище Backstage — одна SQLite-база на всю платформу, данные клиентов
разделены по client_id. Схема:

  clients   — клиенты агентства (ключ доступа, профиль практики, бюджет, модели)
  widgets   — элементы дашборда клиента (KPI, график, таблица, доска, список, заметка)
  messages  — переписка клиента с командой (по агентам)
  usage     — расход токенов и денег по каждому вызову Claude
  insights  — база опыта: выводы, которые команда сохраняет по ходу работы.
              shared=1 — одобрено владельцем платформы и видно агентам ВСЕХ клиентов
              (обезличенный общий плейбук), shared=0 — только этому клиенту.
"""
import os
import json
import sqlite3
import secrets
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta

DB = os.environ.get("BACKSTAGE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "backstage.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    profile TEXT DEFAULT '',
    lang TEXT DEFAULT 'ru',
    monthly_budget REAL DEFAULT 20.0,
    model_chat TEXT DEFAULT '',
    model_deep TEXT DEFAULT '',
    tg_token TEXT DEFAULT '',
    tg_chat_id TEXT DEFAULT '',
    share_insights INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS widgets (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    config TEXT DEFAULT '{}',
    data TEXT DEFAULT '{}',
    pos INTEGER DEFAULT 0,
    size TEXT DEFAULT 'm',
    updated TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    agent TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    meta TEXT DEFAULT '{}',
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read INTEGER DEFAULT 0,
    cache_write INTEGER DEFAULT 0,
    web_searches INTEGER DEFAULT 0,
    cost REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    agent TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT DEFAULT '',
    shared INTEGER DEFAULT 0,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,          -- нормализованная ссылка (или название): одна возможность — одна строка
    title TEXT NOT NULL,
    org TEXT DEFAULT '',
    url TEXT DEFAULT '',
    deadline TEXT DEFAULT '',          -- YYYY-MM-DD или пусто (без срока)
    amount TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    region TEXT DEFAULT 'intl',        -- de | at | ch | ua | eu | intl
    crafts TEXT DEFAULT '',            -- ремёсла через запятую
    found TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_opps (
    client_id INTEGER NOT NULL,
    opp_id INTEGER NOT NULL,
    added TEXT NOT NULL,
    PRIMARY KEY (client_id, opp_id)
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT DEFAULT 'other',         -- cv | portfolio | statement | bio | press | photo | video | other
    mime TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    path TEXT NOT NULL,
    text TEXT DEFAULT '',              -- извлечённый текст (для агентов)
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT DEFAULT '',
    body TEXT NOT NULL,                -- markdown
    app_id INTEGER DEFAULT 0,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    org TEXT DEFAULT '',
    url TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    status TEXT DEFAULT 'idea',        -- idea | preparing | submitted | won | rejected
    note TEXT DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
    client_id INTEGER NOT NULL,
    key TEXT NOT NULL,                 -- что уже напомнили: «виджет:пункт:за N дней»
    created TEXT NOT NULL,
    PRIMARY KEY (client_id, key)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    client_id INTEGER NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_widgets_client ON widgets(client_id, pos);
CREATE INDEX IF NOT EXISTS ix_messages_client ON messages(client_id, agent, id);
CREATE INDEX IF NOT EXISTS ix_usage_client ON usage(client_id, ts);
"""


@contextmanager
def db():
    # Как в дашборде Фридмана: коммит при успехе, откат при ошибке, соединение
    # закрывается всегда. Несколько процессов (сервер + Telegram-мост) пишут
    # в одну базу, поэтому timeout и WAL.
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(clients)").fetchall()}
        if "source" not in cols:  # admin | signup | demo — кто завёл клиента
            conn.execute("ALTER TABLE clients ADD COLUMN source TEXT DEFAULT 'admin'")
        if "craft" not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN craft TEXT DEFAULT ''")
        if "survey" not in cols:  # подробная анкета: JSON {answers, summary, done, updated}
            conn.execute("ALTER TABLE clients ADD COLUMN survey TEXT DEFAULT ''")
        for col in ("plan", "plan_until", "stripe_customer", "prefs"):  # тариф (plans.py) и покупатель в Stripe
            if col not in cols:
                conn.execute(f"ALTER TABLE clients ADD COLUMN {col} TEXT DEFAULT ''")


def set_survey(client_id: int, answers: dict, summary: str, done: bool):
    old = {}
    with db() as conn:
        r = conn.execute("SELECT survey FROM clients WHERE id=?", (client_id,)).fetchone()
        try:
            old = json.loads((r and r["survey"]) or "{}")
        except Exception:
            old = {}
        data = {"answers": answers, "summary": summary, "done": bool(done or old.get("done")), "updated": now()}
        conn.execute("UPDATE clients SET survey=? WHERE id=?", (json.dumps(data, ensure_ascii=False), client_id))


# ─── Радар возможностей: общий каталог ───────────────────────────────────────

def _opp_key(url, title):
    u = (url or "").strip().lower().split("#")[0].rstrip("/")
    for p in ("https://", "http://", "www."):
        u = u[len(p):] if u.startswith(p) else u
    return u or "t:" + " ".join((title or "").lower().split())[:120]


def add_opportunity(o: dict, craft: str, region: str):
    """Новая возможность → в каталог; уже известная — дописываем ремесло. Возвращает id."""
    key = _opp_key(o.get("url"), o.get("title"))
    with db() as conn:
        row = conn.execute("SELECT id, crafts FROM opportunities WHERE key=?", (key,)).fetchone()
        if row:
            crafts = set(filter(None, row["crafts"].split(","))) | {craft}
            conn.execute("UPDATE opportunities SET crafts=? WHERE id=?", (",".join(sorted(crafts)), row["id"]))
            return row["id"]
        cur = conn.execute(
            "INSERT INTO opportunities (key, title, org, url, deadline, amount, summary, region, crafts, found) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, str(o.get("title", ""))[:200], str(o.get("org") or "")[:120], str(o.get("url") or "")[:500],
             str(o.get("deadline") or "")[:10], str(o.get("amount") or "")[:80], str(o.get("summary") or "")[:400],
             (o.get("region") or region or "intl")[:8], craft, now()))
        return cur.lastrowid


def match_opportunities(client_id: int, crafts, regions, limit=5, min_deadline=""):
    """Подходящие клиенту и ещё не отправленные ему возможности, ближайшие дедлайны первыми."""
    crafts = [c for c in crafts if c] or ["other"]
    cq = " OR ".join("(','||o.crafts||',') LIKE ?" for _ in crafts)
    rq = ",".join("?" for _ in regions)
    with db() as conn:
        rows = conn.execute(
            f"SELECT o.* FROM opportunities o WHERE ({cq}) AND o.region IN ({rq}) "
            "AND (o.deadline='' OR o.deadline>=?) "
            "AND o.id NOT IN (SELECT opp_id FROM client_opps WHERE client_id=?) "
            "ORDER BY CASE WHEN o.deadline='' THEN 1 ELSE 0 END, o.deadline LIMIT ?",
            (*[f"%,{c},%" for c in crafts], *regions, min_deadline, client_id, limit)).fetchall()
    return [dict(r) for r in rows]


def mark_delivered(client_id: int, opp_ids):
    with db() as conn:
        conn.executemany("INSERT OR IGNORE INTO client_opps (client_id, opp_id, added) VALUES (?,?,?)",
                         [(client_id, i, now()) for i in opp_ids])


def recent_opportunities(limit=50):
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM opportunities ORDER BY id DESC LIMIT ?", (limit,))]


# ─── Сейф материалов, документы, заявки ──────────────────────────────────────

FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")
APP_STATUSES = ("idea", "preparing", "submitted", "won", "rejected")


def add_file(client_id, name, kind, mime, raw: bytes, text=""):
    d = os.path.join(FILES_DIR, str(client_id))
    os.makedirs(d, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[-80:] or "file"
    with db() as conn:
        cur = conn.execute("INSERT INTO files (client_id, name, kind, mime, size, path, text, created) "
                           "VALUES (?,?,?,?,?,?,?,?)", (client_id, name[:160], kind, mime, len(raw), "", text[:20000], now()))
        fid = cur.lastrowid
        path = os.path.join(d, f"{fid}_{safe}")
        with open(path, "wb") as f:
            f.write(raw)
        conn.execute("UPDATE files SET path=? WHERE id=?", (path, fid))
    return fid


def list_files(client_id):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, name, kind, mime, size, created, length(text) AS text_len FROM files WHERE client_id=? ORDER BY id DESC",
            (client_id,))]


def get_file(client_id, fid):
    with db() as conn:
        r = conn.execute("SELECT * FROM files WHERE id=? AND client_id=?", (fid, client_id)).fetchone()
    return dict(r) if r else None


def delete_file(client_id, fid):
    f = get_file(client_id, fid)
    if f:
        try:
            os.unlink(f["path"])
        except OSError:
            pass
        with db() as conn:
            conn.execute("DELETE FROM files WHERE id=?", (fid,))


def files_size(client_id):
    with db() as conn:
        return conn.execute("SELECT COALESCE(SUM(size),0) FROM files WHERE client_id=?", (client_id,)).fetchone()[0]


def add_doc(client_id, title, kind, body, app_id=0):
    with db() as conn:
        return conn.execute("INSERT INTO docs (client_id, title, kind, body, app_id, created) VALUES (?,?,?,?,?,?)",
                            (client_id, title[:200], kind, body, int(app_id or 0), now())).lastrowid


def list_docs(client_id):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, kind, app_id, created, length(body) AS size FROM docs WHERE client_id=? ORDER BY id DESC",
            (client_id,))]


def get_doc(client_id, did):
    with db() as conn:
        r = conn.execute("SELECT * FROM docs WHERE id=? AND client_id=?", (did, client_id)).fetchone()
    return dict(r) if r else None


def delete_doc(client_id, did):
    with db() as conn:
        conn.execute("DELETE FROM docs WHERE id=? AND client_id=?", (did, client_id))


def save_app(client_id, a: dict):
    """Создать (без id) или обновить заявку. Возвращает id."""
    fields = {k: str(a[k])[:500] for k in ("title", "org", "url", "deadline", "status", "note") if a.get(k) is not None}
    if "status" in fields and fields["status"] not in APP_STATUSES:
        fields.pop("status")
    with db() as conn:
        if a.get("id"):
            if fields:
                sets = ", ".join(f"{k}=?" for k in fields)
                conn.execute(f"UPDATE applications SET {sets}, updated=? WHERE id=? AND client_id=?",
                             (*fields.values(), now(), int(a["id"]), client_id))
            return int(a["id"])
        if not fields.get("title"):
            raise ValueError("title")
        cols = ["client_id", *fields, "created", "updated"]
        return conn.execute(f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                            (client_id, *fields.values(), now(), now())).lastrowid


def list_apps(client_id):
    with db() as conn:
        rows = conn.execute("SELECT a.*, (SELECT MAX(d.id) FROM docs d WHERE d.app_id=a.id) AS doc_id "
                            "FROM applications a WHERE a.client_id=? ORDER BY "
                            "CASE a.status WHEN 'won' THEN 3 WHEN 'rejected' THEN 3 ELSE 1 END, "
                            "CASE WHEN a.deadline='' THEN '9999' ELSE a.deadline END", (client_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_app(client_id, aid):
    with db() as conn:
        conn.execute("DELETE FROM applications WHERE id=? AND client_id=?", (aid, client_id))


def replace_last_answer(client_id, agent, text, meta_extra=None):
    with db() as conn:
        r = conn.execute("SELECT id, meta FROM messages WHERE client_id=? AND agent=? AND role='assistant' "
                         "ORDER BY id DESC LIMIT 1", (client_id, agent)).fetchone()
        if r:
            meta = {**json.loads(r["meta"] or "{}"), **(meta_extra or {})}
            conn.execute("UPDATE messages SET text=?, meta=? WHERE id=?", (text, json.dumps(meta, ensure_ascii=False), r["id"]))


def notice_once(client_id: int, key: str) -> bool:
    """True — если это напоминание ещё не отправлялось (и отмечает его отправленным)."""
    with db() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO notices (client_id, key, created) VALUES (?,?,?)",
                           (client_id, key, now()))
        return cur.rowcount == 1


def active_clients(days=30):
    """Кто реально пользуется: включён и писал команде за последние N дней."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM clients WHERE active=1 AND id IN (SELECT DISTINCT client_id FROM messages "
            "WHERE role='user' AND substr(created,1,10)>=?)", (since,)).fetchall()
    return [dict(r) for r in rows]


def meta_get(key, default=None):
    with db() as conn:
        r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def meta_set(key, value):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, str(value)))


def now():
    return datetime.now().isoformat(timespec="seconds")


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ─── Клиенты ─────────────────────────────────────────────────────────────────

def create_client(slug: str, name: str, profile: str = "", budget: float = 20.0, lang: str = "en", key: str = None,
                  source: str = "admin", craft: str = ""):
    """Создаёт клиента со стартовым дашбордом. Возвращает (client_id, access_key) —
    ключ показывается один раз, в базе лежит только его хэш."""
    key = key or secrets.token_urlsafe(18)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO clients (slug, name, key_hash, profile, monthly_budget, lang, created, source, craft) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (slug, name, hash_key(key), profile, budget, lang, now(), source, craft))
        cid = cur.lastrowid
    seed_dashboard(cid, craft.split(",")[0], lang)
    return cid, key


def slug_taken(slug: str) -> bool:
    with db() as conn:
        return bool(conn.execute("SELECT 1 FROM clients WHERE slug=?", (slug,)).fetchone())


def signups_since(hours: int = 24, ip_hash: str = None) -> int:
    with db() as conn:
        if ip_hash:
            return conn.execute("SELECT COUNT(*) FROM meta WHERE key LIKE ? AND value >= datetime('now', ?)",
                                (f"signup:{ip_hash}:%", f"-{hours} hours")).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM clients WHERE source='signup' AND created >= ?",
                            ((datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds"),)).fetchone()[0]


def note_signup(ip_hash: str):
    with db() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, datetime('now'))",
                     (f"signup:{ip_hash}:{secrets.token_hex(4)}",))


def requests_today(client_id: int) -> dict:
    """Сколько сообщений клиент сегодня отправил команде (обычных и с глубоким анализом).
    Считаем сообщения, а не вызовы модели: одно сообщение Майе может стоить
    нескольких вызовов (она зовёт специалистов), а лимит — про человека."""
    day = datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute("SELECT meta FROM messages WHERE client_id=? AND role='user' AND substr(created,1,10)=?",
                            (client_id, day)).fetchall()
    deep = sum(1 for r in rows if '"deep": true' in (r["meta"] or ""))
    return {"chat": len(rows) - deep, "deep": deep}


def reset_key(client_id: int) -> str:
    key = secrets.token_urlsafe(18)
    with db() as conn:
        conn.execute("UPDATE clients SET key_hash=? WHERE id=?", (hash_key(key), client_id))
    drop_client_sessions(client_id)  # старый ключ мог утечь — выкидываем все входы по нему
    return key


def client_by_key(slug: str, key: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE slug=? AND active=1", (slug,)).fetchone()
    if row and secrets.compare_digest(row["key_hash"], hash_key(key)):
        return dict(row)
    return None


def get_client(client_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return dict(row) if row else None


def client_by_slug(slug: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


def client_by_customer(customer: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE stripe_customer=?", (customer,)).fetchone()
    return dict(row) if row else None


def list_clients():
    month = datetime.now().strftime("%Y-%m")
    with db() as conn:
        rows = conn.execute(
            "SELECT c.*, COALESCE((SELECT SUM(cost) FROM usage u WHERE u.client_id=c.id "
            "AND substr(u.ts,1,7)=?),0) AS spent_month, "
            "COALESCE((SELECT SUM(cost) FROM usage u WHERE u.client_id=c.id),0) AS spent_total "
            "FROM clients c ORDER BY c.id", (month,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("key_hash", None)
        d["tg_connected"] = bool(d.pop("tg_token", ""))
        d.pop("survey", None)
        out.append(d)
    return out


CLIENT_EDITABLE = {"name", "profile", "lang", "monthly_budget", "model_chat", "model_deep",
                   "tg_token", "tg_chat_id", "share_insights", "active", "plan", "plan_until", "stripe_customer", "prefs"}


def update_client(client_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in CLIENT_EDITABLE}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE clients SET {sets} WHERE id=?", (*fields.values(), client_id))


DEMO_SLUG = "canon"


def retire_demo():
    """Общий демо-вход Canon/1111 больше не предлагается: новички регистрируются сами.
    Старый демо-аккаунт отключаем (данные не удаляем)."""
    with db() as conn:
        conn.execute("UPDATE clients SET active=0 WHERE slug=? AND source IN ('demo','admin') AND key_hash=?",
                     (DEMO_SLUG, hash_key("1111")))


# ─── Сессии ──────────────────────────────────────────────────────────────────
# client_id = 0 — сессия владельца платформы (админка). Живут 30 дней.

SESSION_DAYS = 30


def new_session(client_id: int) -> str:
    tok = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE created < datetime('now', ?)", (f"-{SESSION_DAYS} days",))
        conn.execute("INSERT INTO sessions (token, client_id, created) VALUES (?,?,datetime('now'))",
                     (tok, client_id))
    return tok


def session_client(tok: str):
    if not tok:
        return None
    with db() as conn:
        row = conn.execute("SELECT client_id FROM sessions WHERE token=? AND created >= datetime('now', ?)",
                           (tok, f"-{SESSION_DAYS} days")).fetchone()
    return row["client_id"] if row else None


def drop_session(tok: str):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (tok,))


def drop_client_sessions(client_id: int):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE client_id=?", (client_id,))


# ─── Дашборд ─────────────────────────────────────────────────────────────────

WIDGET_KINDS = ("kpi", "chart", "table", "board", "list", "note")


def seed_dashboard(client_id: int, craft: str = "", lang: str = "en"):
    """Базовая версия дашборда — то, с чего начинает любой клиент. Менее
    персонализированная, чем «Капитанский мостик» Фридмана: дальше клиент
    перестраивает её руками или через чат. Подписи — на языке клиента."""
    import i18n
    L = i18n.norm(lang)
    S = i18n.SEED[L]
    month = datetime.now().strftime("%Y-%m")
    seed = [
        ("kpi", S["income"], {"unit": "€", "goal": 3000}, {"value": 0, "delta": ""}, "s"),
        ("kpi", S["apps"], {"unit": ""}, {"value": 0, "delta": ""}, "s"),
        ("kpi", S["budget"], {"unit": "$", "system": "budget"}, {"value": 0}, "s"),
        ("board", S["projects"], {"columns": i18n.BOARDS[L].get(craft) or i18n.BOARDS[L]["_"]},
         {"cards": [{"id": 1, "col": 0, "text": S["card"]}]}, "l"),
        ("chart", S["chart"], {"type": "bar", "unit": "€"},
         {"labels": [month], "series": [{"name": S["series"], "values": [0]}]}, "m"),
        ("list", i18n.LISTS[L].get(craft) or i18n.LISTS[L]["_"], {}, {"items": []}, "m"),
        ("note", S["profile"], {}, {"text": S["profile_text"]}, "m"),
    ]
    with db() as conn:
        for i, (kind, title, cfg, data, size) in enumerate(seed):
            conn.execute(
                "INSERT INTO widgets (client_id, kind, title, config, data, pos, size, updated) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (client_id, kind, title, json.dumps(cfg, ensure_ascii=False),
                 json.dumps(data, ensure_ascii=False), i, size, now()))


def _widget_row(r):
    d = dict(r)
    d["config"] = json.loads(d["config"] or "{}")
    d["data"] = json.loads(d["data"] or "{}")
    return d


def list_widgets(client_id: int):
    with db() as conn:
        rows = conn.execute("SELECT * FROM widgets WHERE client_id=? ORDER BY pos, id", (client_id,)).fetchall()
    return [_widget_row(r) for r in rows]


def get_widget(client_id: int, wid: int):
    with db() as conn:
        r = conn.execute("SELECT * FROM widgets WHERE client_id=? AND id=?", (client_id, wid)).fetchone()
    return _widget_row(r) if r else None


def add_widget(client_id: int, kind: str, title: str, config=None, data=None, size="m"):
    if kind not in WIDGET_KINDS:
        raise ValueError(f"неизвестный тип виджета: {kind}")
    with db() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(pos),-1)+1 FROM widgets WHERE client_id=?", (client_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO widgets (client_id, kind, title, config, data, pos, size, updated) VALUES (?,?,?,?,?,?,?,?)",
            (client_id, kind, title[:120], json.dumps(config or {}, ensure_ascii=False),
             json.dumps(data or {}, ensure_ascii=False), pos, size if size in ("s", "m", "l") else "m", now()))
        return cur.lastrowid


def update_widget(client_id: int, wid: int, title=None, config=None, data=None, size=None):
    w = get_widget(client_id, wid)
    if not w:
        raise ValueError(f"виджет {wid} не найден")
    with db() as conn:
        conn.execute(
            "UPDATE widgets SET title=?, config=?, data=?, size=?, updated=? WHERE id=? AND client_id=?",
            ((title or w["title"])[:120],
             json.dumps(config if config is not None else w["config"], ensure_ascii=False),
             json.dumps(data if data is not None else w["data"], ensure_ascii=False),
             size if size in ("s", "m", "l") else w["size"], now(), wid, client_id))
    return get_widget(client_id, wid)


def delete_widget(client_id: int, wid: int):
    with db() as conn:
        conn.execute("DELETE FROM widgets WHERE id=? AND client_id=?", (wid, client_id))


def reorder_widgets(client_id: int, ids):
    with db() as conn:
        for i, wid in enumerate(ids):
            conn.execute("UPDATE widgets SET pos=? WHERE id=? AND client_id=?", (i, int(wid), client_id))


# ─── Переписка ───────────────────────────────────────────────────────────────

def add_message(client_id: int, agent: str, role: str, text: str, meta=None):
    with db() as conn:
        conn.execute(
            "INSERT INTO messages (client_id, agent, role, text, meta, created) VALUES (?,?,?,?,?,?)",
            (client_id, agent, role, text, json.dumps(meta or {}, ensure_ascii=False), now()))


def history(client_id: int, agent: str, limit: int = 30):
    with db() as conn:
        rows = conn.execute(
            "SELECT role, text, meta, created FROM messages WHERE client_id=? AND agent=? "
            "ORDER BY id DESC LIMIT ?", (client_id, agent, limit)).fetchall()
    out = [dict(r) for r in reversed(rows)]
    for m in out:
        m["meta"] = json.loads(m["meta"] or "{}")
    return out


def _archive_today(conn, client_id, agent=None):
    """Сегодняшние запросы клиента не удаляем, а прячем в «_archive»: по ним считается
    дневной лимит бесплатной версии, и очистка чата не должна его обнулять."""
    day = datetime.now().strftime("%Y-%m-%d")
    q = "UPDATE messages SET agent='_archive', text='' WHERE client_id=? AND role='user' AND substr(created,1,10)=?"
    args = [client_id, day]
    if agent:
        q += " AND agent=?"
        args.append(agent)
    conn.execute(q, args)


def clear_history(client_id: int, agent: str):
    with db() as conn:
        _archive_today(conn, client_id, agent)
        conn.execute("DELETE FROM messages WHERE client_id=? AND agent=?", (client_id, agent))


def restart_client(client_id: int, name: str, profile: str, craft: str, lang: str):
    """«Начать с нуля»: переписка, дашборд, своя база опыта и анкета стираются,
    вход (имя и PIN), язык и расход остаются."""
    with db() as conn:
        _archive_today(conn, client_id)
        conn.execute("DELETE FROM messages WHERE client_id=? AND agent!='_archive'", (client_id,))
        conn.execute("DELETE FROM widgets WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM insights WHERE client_id=? AND shared=0", (client_id,))
        conn.execute("DELETE FROM docs WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM applications WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM client_opps WHERE client_id=?", (client_id,))
        conn.execute("UPDATE clients SET name=?, profile=?, craft=?, lang=?, survey='' WHERE id=?",
                     (name, profile, craft, lang, client_id))
    seed_dashboard(client_id, craft.split(",")[0], lang)


# ─── Расход ──────────────────────────────────────────────────────────────────

def log_usage(client_id: int, kind: str, model: str, u: dict, cost: float):
    with db() as conn:
        conn.execute(
            "INSERT INTO usage (client_id, ts, kind, model, input_tokens, output_tokens, cache_read, "
            "cache_write, web_searches, cost) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (client_id, now(), kind, model, u.get("input", 0), u.get("output", 0),
             u.get("cache_read", 0), u.get("cache_write", 0), u.get("web", 0), cost))


def spent_this_month(client_id: int) -> float:
    month = datetime.now().strftime("%Y-%m")
    with db() as conn:
        v = conn.execute("SELECT COALESCE(SUM(cost),0) FROM usage WHERE client_id=? AND substr(ts,1,7)=?",
                         (client_id, month)).fetchone()[0]
    return float(v)


def usage_summary(client_id=None, days: int = 31):
    q = ("SELECT substr(ts,1,10) AS day, model, SUM(input_tokens) i, SUM(output_tokens) o, "
         "SUM(cache_read) cr, SUM(cost) cost, COUNT(*) n FROM usage "
         "WHERE ts >= date('now', ?) " + ("AND client_id=? " if client_id else "") +
         "GROUP BY day, model ORDER BY day")
    args = [f"-{days} days"] + ([client_id] if client_id else [])
    with db() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


# ─── База опыта ──────────────────────────────────────────────────────────────

def add_insight(client_id: int, agent: str, title: str, body: str, tags: str = ""):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO insights (client_id, agent, title, body, tags, created) VALUES (?,?,?,?,?,?)",
            (client_id, agent, title[:200], body[:4000], tags[:200], now()))
        return cur.lastrowid


def insights_for(client_id: int, limit: int = 40):
    """Свои выводы клиента + общий плейбук (одобренный владельцем)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, client_id, agent, title, body, tags, shared, created FROM insights "
            "WHERE client_id=? OR shared=1 ORDER BY id DESC LIMIT ?", (client_id, limit)).fetchall()
    return [dict(r) for r in rows]


def all_insights(limit: int = 300):
    with db() as conn:
        rows = conn.execute(
            "SELECT i.*, c.name AS client_name, c.share_insights FROM insights i "
            "LEFT JOIN clients c ON c.id=i.client_id ORDER BY i.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def set_insight_shared(iid: int, shared: int, title=None, body=None):
    with db() as conn:
        if title is not None or body is not None:
            conn.execute("UPDATE insights SET shared=?, title=COALESCE(?,title), body=COALESCE(?,body) WHERE id=?",
                         (shared, title, body, iid))
        else:
            conn.execute("UPDATE insights SET shared=? WHERE id=?", (shared, iid))


def delete_insight(iid: int, client_id=None):
    with db() as conn:
        if client_id:
            conn.execute("DELETE FROM insights WHERE id=? AND client_id=?", (iid, client_id))
        else:
            conn.execute("DELETE FROM insights WHERE id=?", (iid,))
