"""База данных Inspire (SQLite). Одна точка правды для бота, дашборда и сводки."""
import os
import sqlite3
import secrets
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS dancers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    group_name TEXT,              -- Kids / Teens / Adults / Pro / Show
    style TEXT,                   -- hip-hop, contemporary, jazz-funk...
    level TEXT,                   -- начальный / средний / продвинутый
    phone TEXT, email TEXT,
    birthday TEXT,                -- YYYY-MM-DD
    joined_on TEXT,
    status TEXT DEFAULT 'active', -- active / pause / left
    monthly_fee REAL DEFAULT 0,   -- абонемент в месяц
    tg_id INTEGER UNIQUE,
    tg_username TEXT,
    invite_code TEXT UNIQUE,      -- персональная ссылка t.me/<bot>?start=<code>
    notes TEXT
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT,
    kind TEXT,                    -- корпоратив / свадьба / агентство / фестиваль / ТВ / бренд / частный
    phone TEXT, email TEXT,
    source TEXT,                  -- откуда пришёл: Instagram, рекомендация, сайт...
    created_on TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    kind TEXT,                    -- шоу / постановка / клип / workshop / конкурс / фестиваль
    date TEXT,                    -- дата события
    venue TEXT,
    status TEXT DEFAULT 'лид',    -- лид / переговоры / подтверждён / выполнен / отменён
    budget REAL DEFAULT 0,        -- сумма договора
    dancers_needed INTEGER DEFAULT 0,
    created_on TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    amount REAL NOT NULL,         -- всегда положительное
    direction TEXT NOT NULL,      -- in / out
    category TEXT,                -- Гонорар, Абонементы, Мастер-классы, Гранты | Аренда, Костюмы, Выплаты танцорам...
    project_id INTEGER REFERENCES projects(id),
    client_id INTEGER REFERENCES clients(id),
    dancer_id INTEGER REFERENCES dancers(id),
    method TEXT,                  -- банк / наличные / PayPal / карта
    note TEXT,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS communications (
    id INTEGER PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id),
    project_id INTEGER REFERENCES projects(id),
    date TEXT NOT NULL,
    channel TEXT,                 -- звонок / email / WhatsApp / Telegram / встреча
    direction TEXT,               -- in / out
    summary TEXT,
    next_step TEXT,
    next_date TEXT                -- напоминание: когда вернуться к заказчику
);
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    dancer_id INTEGER REFERENCES dancers(id),
    status TEXT DEFAULT 'invited', -- invited / yes / maybe / no / confirmed
    fee REAL DEFAULT 0,
    UNIQUE(project_id, dancer_id)
);
CREATE TABLE IF NOT EXISTS rehearsals (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL, time TEXT,
    group_name TEXT, title TEXT, place TEXT
);
CREATE TABLE IF NOT EXISTS attendance (
    rehearsal_id INTEGER REFERENCES rehearsals(id),
    dancer_id INTEGER REFERENCES dancers(id),
    present INTEGER,
    reason TEXT,
    PRIMARY KEY (rehearsal_id, dancer_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    dancer_id INTEGER REFERENCES dancers(id),
    date TEXT NOT NULL,
    direction TEXT,               -- in (от танцора) / out (от руководителя) / broadcast
    text TEXT,
    kind TEXT DEFAULT 'text',     -- text / file / absence / poll
    is_read INTEGER DEFAULT 0,
    admin_msg_id INTEGER          -- id пересланного админу сообщения: ответ reply-ем уходит танцору
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    date TEXT,
    uploaded_by TEXT,
    kind TEXT,                    -- photo / video / document / audio / voice
    filename TEXT, path TEXT, size INTEGER,
    tg_file_id TEXT,
    caption TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_comm_client ON communications(client_id);
CREATE INDEX IF NOT EXISTS ix_att_dancer ON attendance(dancer_id);
CREATE INDEX IF NOT EXISTS ix_msg_dancer ON messages(dancer_id);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        c.execute("PRAGMA journal_mode=WAL")


def rows(sql, args=()):
    with db() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    with db() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def execute(sql, args=()):
    with db() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def new_invite_code():
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "z")


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key, value):
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
