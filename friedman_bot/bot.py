import os
import re
import sqlite3
import logging
import tempfile
import asyncio
import calendar as _calendar
from datetime import datetime, time, date, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, JobQueue
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
DB = os.path.join(os.path.dirname(__file__), "friedman.db")
# Постоянное хранилище PDF счетов: /tmp живёт до перезагрузки, а рассылка
# по запросу и бэкапы работают только с этим каталогом (файл = <номер>.pdf)
INVOICES_PDF_DIR = os.path.join(os.path.dirname(__file__), "invoices_pdf")

# Таймзона Франкфурта — чтобы сводка приходила по местному времени, а не по UTC сервера
try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    try:
        import pytz
        BERLIN = pytz.timezone("Europe/Berlin")
    except Exception:
        BERLIN = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Данные ────────────────────────────────────────────────────────────────────

AREAS = {
    "work":   "💼 работа",
    "health": "🌿 здоровье",
    "money":  "💰 деньги",
    "people": "👥 люди",
    "home":   "🏠 дом",
    "self":   "📚 саморазвитие",
    "other":  "⚡ другое",
}

# Ключевые слова для автоматической категоризации
AREA_KEYWORDS = {
    "health": ["врач", "доктор", "больниц", "аптек", "таблетк", "здоровь", "тромбоз", "болит",
               "зуб", "стоматол", "анализ", "медицин", "спорт", "бег", "тренировк", "сон",
               "питани", "диет", "страховк"],
    "money":  ["деньги", "деньг", "евро", "€", "$", "заплатить", "оплатить", "купить", "банк",
               "счёт", "счет", "долг", "кредит", "бюджет", "налог", "доход", "расход", "перевод"],
    "people": ["позвони", "написать", "встреч", "свидани", "друг", "мама", "папа", "брат",
               "сестра", "жена", "муж", "ребён", "детям", "роберт", "стефан", "руслан"],
    "home":   ["дом", "квартир", "ремонт", "уборк", "кухн", "ванн", "кот", "кошк", "еда",
               "готовить", "магазин", "продукт", "окн", "дверь", "сантехник", "мебель"],
    "self":   ["книг", "курс", "учи", "прочитать", "посмотреть", "изучить", "развитие",
               "медитац", "дневник", "план", "цел", "мечт"],
    "work":   ["проект", "работ", "клиент", "встреч", "презентац", "дедлайн", "задач",
               "farbaholix", "граффити", "carhartt", "south bags", "партнёр", "спонсор",
               "письмо", "договор", "счёт"],
}

PRIORITY_KEYWORDS = {
    "high": ["срочно", "важно", "сегодня", "обязательно", "критично", "горит", "asap",
             "немедленно", "прямо сейчас", "не забыть", "!"],
    "low":  ["когда-нибудь", "потом", "не срочно", "когда будет время", "в будущем", "можно"],
}


def db():
    # timeout: шесть процессов (3 бота + Секретарь + 2 дашборда) пишут в один
    # SQLite — без ожидания блокировки редкие «database is locked» неизбежны
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        try:
            # WAL: свойство самого файла БД (хватает включить один раз любым
            # процессом) — параллельные читатели не блокируют писателя
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chaos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            area TEXT DEFAULT 'other',
            priority TEXT DEFAULT 'mid',
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            area TEXT DEFAULT 'work',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            text TEXT NOT NULL,
            done INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            area TEXT DEFAULT 'work',
            period TEXT DEFAULT 'week',
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT, date TEXT, time TEXT, chaos_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS finance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            comment TEXT,
            account TEXT DEFAULT 'card',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            due_at TEXT NOT NULL,
            text TEXT NOT NULL,
            sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT,
            date TEXT,
            recipient TEXT,
            customer_no TEXT,
            description TEXT,
            total REAL,
            source TEXT DEFAULT 'bot',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        -- Отдельная долгая память Юриста: полные реплики, не под общим лимитом 50
        -- и не вытесняется болтовнёй с секретарём. Старое сжимается в сводку (settings).
        CREATE TABLE IF NOT EXISTS lawyer_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        -- Память клиентов: по короткому упоминанию («Sa'Sis») бот берёт ПОЛНЫЙ адрес
        -- и обращение из прошлого счёта. key — нормализованное имя для матчинга.
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            name TEXT,
            recipient_full TEXT,
            salutation TEXT,
            customer_no TEXT,
            last_used TEXT DEFAULT CURRENT_TIMESTAMP
        );
        -- Архив распознанных инвойсов (для пакетного анализа года): структурные поля
        -- каждого присланного счёта. dedup по (number, inv_date).
        CREATE TABLE IF NOT EXISTS invoice_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT,
            inv_date TEXT,
            year INTEGER,
            client_name TEXT,
            items TEXT,
            net REAL,
            vat REAL,
            gross REAL,
            kleinunternehmer INTEGER,
            raw_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(number, inv_date)
        );
        -- Бюрократические «дела» (права, §24, паспорт, KSK…): статус, следующий шаг,
        -- срок. Юрист обновляет через action "case"; раз в неделю бот шлёт сводку.
        CREATE TABLE IF NOT EXISTS bureau_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT UNIQUE,
            title TEXT,
            status TEXT DEFAULT 'open',
            next_step TEXT,
            due_date TEXT,
            note TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        -- Архив распознанных договоров (для сбора нюансов и составления новых).
        CREATE TABLE IF NOT EXISTS contract_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT,
            subject TEXT,
            amount REAL,
            start_date TEXT,
            end_date TEXT,
            terms TEXT,
            raw_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bridge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT,
            done_text TEXT,
            missed_text TEXT,
            insight_text TEXT,
            next_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT DEFAULT 'current',
            total REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            due_date TEXT,
            monthly REAL DEFAULT 0,
            icon TEXT DEFAULT '💳',
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS payments (
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    with db() as conn:
        fcols = [r[1] for r in conn.execute("PRAGMA table_info(finance)").fetchall()]
        if "account" not in fcols:
            conn.execute("ALTER TABLE finance ADD COLUMN account TEXT DEFAULT 'card'")
            conn.execute("UPDATE finance SET account='card' WHERE account IS NULL")
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(chaos)").fetchall()]
        if "importance" not in ccols:
            conn.execute("ALTER TABLE chaos ADD COLUMN importance INTEGER DEFAULT 0")
        if "urgency" not in ccols:
            conn.execute("ALTER TABLE chaos ADD COLUMN urgency INTEGER DEFAULT 0")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()]
        for col, ddl in [("date", "TEXT"), ("customer_no", "TEXT"),
                         ("description", "TEXT"), ("source", "TEXT DEFAULT 'bot'")]:
            if col not in cols:
                conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")


# ─── Умная категоризация ───────────────────────────────────────────────────────

def detect_area(text: str) -> str:
    t = text.lower()
    scores = {area: 0 for area in AREA_KEYWORDS}
    for area, keywords in AREA_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                scores[area] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def detect_priority(text: str) -> str:
    t = text.lower()
    for kw in PRIORITY_KEYWORDS["high"]:
        if kw in t:
            return "high"
    for kw in PRIORITY_KEYWORDS["low"]:
        if kw in t:
            return "low"
    return "mid"


def detect_intent(text: str) -> str:
    t = text.lower().strip()
    if any(w in t for w in ["список", "покажи", "что у меня", "что есть", "обзор", "итого"]):
        return "list"
    if any(w in t for w in ["статистик", "сколько", "прогресс", "как дела"]):
        return "stats"
    if any(w in t for w in ["проект", "задач по проекту", "шаги"]):
        return "projects"
    if any(w in t for w in ["цел", "хочу достичь", "планирую"]):
        return "goals"
    if any(w in t for w in ["разбор", "итоги", "мостик", "что сделал"]):
        return "bridge"
    if any(w in t for w in ["готово", "сделал", "выполнил", "закрыл", "✅"]):
        return "done_hint"
    return "add"


def area_emoji(area: str) -> str:
    return AREAS.get(area, "⚡").split(" ")[0]


def priority_text(p: str) -> str:
    return {"high": "срочно 🔴", "mid": "обычный", "low": "не срочно 🟢"}.get(p, "")


def friendly_time() -> str:
    h = datetime.now().hour
    if h < 6:
        return "ночью"
    if h < 12:
        return "утром"
    if h < 17:
        return "днём"
    if h < 21:
        return "вечером"
    return "поздно вечером"


# ─── Обработка голоса ─────────────────────────────────────────────────────────

async def transcribe_voice(file_path: str) -> str:
    try:
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(file_path, language="ru")
        return result["text"].strip()
    except Exception as e:
        log.error(f"Whisper error: {e}")
        return ""


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def area_kbd(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    items = list(AREAS.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i+2]:
            row.append(InlineKeyboardButton(v, callback_data=f"{prefix}:{k}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def confirm_kbd(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ закрыть", callback_data=f"done:{item_id}"),
        InlineKeyboardButton("🗑 удалить", callback_data=f"del:{item_id}"),
        InlineKeyboardButton("✏️ область", callback_data=f"rezone:{item_id}"),
    ]])


# Кнопки убраны по просьбе владельца: reply-клавиатура снимается у всех,
# кто её видел; списки по-прежнему доступны текстом («📋 Хаос», «🧾 Архив инвойсов»)
MAIN_KBD = ReplyKeyboardRemove()


def list_filter_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("все", callback_data="list:all"),
         InlineKeyboardButton("💼", callback_data="list:work"),
         InlineKeyboardButton("🌿", callback_data="list:health"),
         InlineKeyboardButton("💰", callback_data="list:money")],
        [InlineKeyboardButton("👥", callback_data="list:people"),
         InlineKeyboardButton("🏠", callback_data="list:home"),
         InlineKeyboardButton("📚", callback_data="list:self"),
         InlineKeyboardButton("⚡", callback_data="list:other")],
        [InlineKeyboardButton("✅ только открытые", callback_data="list:open")],
    ])


# ─── Сохранение и красивый ответ ──────────────────────────────────────────────

def save_item(text: str, area: str, priority: str, importance: int = 0, urgency: int = 0) -> int:
    with db() as conn:
        min_pos = conn.execute(
            "SELECT COALESCE(MIN(position), 1) FROM chaos WHERE done=0"
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO chaos (text, area, priority, importance, urgency, position) VALUES (?,?,?,?,?,?)",
            (text, area, priority, importance, urgency, min_pos - 1)
        )
        return cur.lastrowid


CONFIRM_PHRASES = [
    "Записала ✍️", "Поймала! ✍️", "Готово, зафиксировала ✅",
    "Отлично, взяла в работу 📌", "Уже в списке 🗂",
]

import random

def confirm_phrase() -> str:
    return random.choice(CONFIRM_PHRASES)


async def save_and_reply(update: Update, text: str, source: str = "text"):
    area = detect_area(text)
    priority = detect_priority(text)
    item_id = save_item(text, area, priority)

    icon = area_emoji(area)
    pri = priority_text(priority)

    phrase = confirm_phrase()
    msg = f"{phrase}\n\n*{text}*\n{icon} {AREAS[area]} · {pri}"

    if source == "voice":
        msg = f"🎤 Услышала: _{text}_\n\n{msg[msg.index(chr(10))+1:]}"

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=confirm_kbd(item_id))


# ─── Мозг: Claude CLI ─────────────────────────────────────────────────────────

import subprocess
import json as jsonlib

CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")

# Загрузка OAuth-токена Claude (для работы на сервере без интерактивного входа)
_token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude_token")
if os.path.exists(_token_file):
    with open(_token_file) as _tf:
        _tok = _tf.read().strip()
    if _tok:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = _tok

SECRETARY_PROMPT = """Ты — личный секретарь-ассистент. Тёплый, дружелюбный, краткий. Общаешься на «ты», по-русски.
Твой хозяин — стрит-арт художник (бренд FARBAHOLIX) в Германии. Он строит жизнь по системе планирования Фридмана (материализация хаоса, проекты, цели, капитанский мостик).

Твои навыки:
1. ЗАДАЧИ: задача/идея/тревога в сообщении → action save. Сделал что-то → поздравь, action done с id из контекста. Для save ОБЯЗАТЕЛЬНО оцени по матрице Фридмана два числа 0-10: importance (важность — влияет ли на цели/деньги/здоровье/репутацию) и urgency (срочность — горит ли по времени). Оцени сам по смыслу; если задача явно значимая, но непонятно насколько горит (или наоборот) — задай ОДИН короткий уточняющий вопрос в reply («Насколько это срочно — на этой неделе или просто в планах?») и всё равно проставь свою оценку. priority выведется из них автоматически.
1а. ЦЕЛИ/ПРОЕКТЫ: если человек говорит слово «цель» («добавь цель...», «новая цель...», «цель — ...») или называет большое дело (не разовую задачу: «хочу выпустить книгу», «сделать сайт») → ОБЯЗАТЕЛЬНО action project (НЕ save!): придумай 4-8 конкретных шагов (декомпозиция по Фридману) и перечисли их в reply. Если человек сообщает о прогрессе по существующему проекту («продвинулся по книге», «сделал эскиз для выставки») → action progress с project_id из контекста и count (сколько шагов закрыть, обычно 1). Не создавай проект повторно если он уже есть в контексте.
2. ДЕНЬГИ: «получил 300 от Роберта» → action finance amount=300. «потратил 40 на баллоны» → amount=-40. Поле account: "cash" если наличные/кэш/cash, "card" если карта/перевод/счёт/банк/Überweisung (по умолчанию card). Спросят баланс — он в контексте (наличные, карта, всего).
3. НАПОМИНАНИЯ: «напомни завтра в 9 про страховку» → action remind, when в формате YYYY-MM-DD HH:MM. Сегодня: {today}.
4. КОНТАКТЫ: важная информация о человеке («Роберт должен 500», «Стефан — контакт по фасадам») → action contact. Спросят про человека — собери всё из контекста.
5. ПИСЬМА НА НЕМЕЦКОМ: попросят письмо/ответ для немецкого заказчика, фирмы, ведомства — напиши готовый текст письма на немецком прямо в reply (профессиональный тон), плюс 1 строка по-русски о чём оно.
6. СМЕТЫ: «стена 6 на 3, сколько краски/цена» → посчитай: грунт ~1л/5м², баллон 400мл ~1-1.5м²/слой, обычно 2 слоя фон + детали. Работа стрит-арт в Германии ориентир 50-150€/м² по сложности.
6в. СЧЕТА (RECHNUNG): «выстави счёт», «сделай инвойс», «Rechnung для X на сумму Y за работу Z» -> action invoice. Извлеки: recipient (получатель: название + адрес, каждая часть с новой строки через \n), items (позиции: desc — описание работы НА НЕМЕЦКОМ профессионально с правильными умляутами ä ö ü ß, напр. «Künstlerische Gestaltung der Fassade ...», price — сумма в евро числом), salutation (обращение если знаешь: «Frau Kluegling» / «Herr Schmidt»), customer_no (если назван), intro (вводная фраза счёта НА НЕМЕЦКОМ, если из просьбы ясен повод/проект — напр. «Hiermit berechne ich Ihnen wie vorab besprochen für die Gestaltung ... folgende Vorauszahlung:»; иначе пусто). Если не хватает получателя или суммы — спроси одним вопросом, не выдумывай.
7. Отвечай по-человечески: коротко, тепло. Максимум один уточняющий вопрос.
8. Не выдумывай данные которых нет в контексте.
9. ВЕБ: если в промпте есть блок «ВЕБ (актуальные данные из интернета):» — используй его данные для ответа. Это свежие данные из поиска, они надёжнее твоих внутренних знаний. Приводи конкретные цифры/факты из блока.

Области: work, health, money, people, home, self, other. Приоритеты: high, mid, low.

ВСЕГДА отвечай строго в JSON:
{"reply": "ответ человеку", "actions": [
 {"type": "save", "text": "...", "area": "...", "priority": "...", "importance": 8, "urgency": 5},
 {"type": "done", "id": 5},
 {"type": "finance", "amount": -40, "comment": "баллоны", "account": "cash"},
 {"type": "remind", "when": "2026-06-13 09:00", "text": "страховка"},
 {"type": "contact", "name": "Роберт", "note": "должен 500€"},
 {"type": "invoice", "recipient": "Café Sa'Sis\nAdlerstraße 1\n65812 Bad Soden", "items": [{"desc": "Künstlerische Gestaltung der Fassade", "price": 800}], "salutation": "Frau Klügling", "customer_no": "", "intro": ""},
 {"type": "project", "name": "КНИГА 3.0", "area": "work", "steps": ["шаг 1", "шаг 2"]},
 {"type": "progress", "project_id": 1, "count": 1}
]}
actions может быть пустым []. Никакого текста вне JSON."""


def get_context() -> str:
    with db() as conn:
        open_items = conn.execute(
            "SELECT id, text, area, priority FROM chaos WHERE done=0 ORDER BY priority='high' DESC, created_at DESC LIMIT 30"
        ).fetchall()
        history = conn.execute(
            "SELECT role, text FROM messages ORDER BY id DESC LIMIT 10"
        ).fetchall()
        balance = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
        cash_bal = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'").fetchone()[0]
        card_bal = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='card'").fetchone()[0]
        fin_last = conn.execute(
            "SELECT amount, comment, created_at FROM finance ORDER BY id DESC LIMIT 8"
        ).fetchall()
        contacts = conn.execute(
            "SELECT name, note, created_at FROM contacts ORDER BY id DESC LIMIT 30"
        ).fetchall()
        reminders = conn.execute(
            "SELECT due_at, text FROM reminders WHERE sent=0 ORDER BY due_at LIMIT 10"
        ).fetchall()

    with db() as conn:
        planned = {r["chaos_id"]: (r["date"], r["time"]) for r in conn.execute(
            "SELECT chaos_id, date, time FROM events WHERE chaos_id IS NOT NULL").fetchall()}

    lines = ["ПАРКОВКА (хаос, не запланировано):"]
    parking = [r for r in open_items if r["id"] not in planned]
    for r in parking:
        lines.append(f"[{r['id']}] ({r['area']}, {r['priority']}) {r['text']}")
    if not parking:
        lines.append("(пусто)")

    cal_items = [r for r in open_items if r["id"] in planned]
    if cal_items:
        lines.append("\nЗАПЛАНИРОВАНО В КАЛЕНДАРЕ:")
        for r in cal_items:
            d, t = planned[r["id"]]
            lines.append(f"[{r['id']}] {d}{' ' + t if t else ''} — {r['text']}")

    with db() as conn:
        projs = conn.execute("SELECT * FROM projects").fetchall()
        proj_lines = []
        for p in projs:
            stats = conn.execute(
                "SELECT COUNT(*) total, COALESCE(SUM(done),0) done FROM steps WHERE project_id=?",
                (p["id"],)).fetchone()
            pct = int(stats["done"] / stats["total"] * 100) if stats["total"] else 0
            next_step = conn.execute(
                "SELECT text FROM steps WHERE project_id=? AND done=0 ORDER BY id LIMIT 1",
                (p["id"],)).fetchone()
            proj_lines.append(
                f"[project_id={p['id']}] {p['name']}: {stats['done']}/{stats['total']} шагов ({pct}%)"
                + (f", следующий шаг: {next_step['text']}" if next_step else " — завершён"))
    if proj_lines:
        lines.append("\nПРОЕКТЫ (цели с декомпозицией):")
        lines.extend(proj_lines)

    lines.append(f"\nДЕНЬГИ: наличные {cash_bal:+.2f}€ | карта {card_bal:+.2f}€ | всего {balance:+.2f}€")
    if fin_last:
        lines.append("ПОСЛЕДНИЕ ОПЕРАЦИИ:")
        for f in fin_last:
            lines.append(f"  {f['amount']:+.0f}€ — {f['comment']} ({f['created_at'][:10]})")

    if contacts:
        lines.append("\nЗАМЕТКИ О ЛЮДЯХ:")
        for c in contacts:
            lines.append(f"  {c['name']}: {c['note']} ({c['created_at'][:10]})")

    if reminders:
        lines.append("\nНАПОМИНАНИЯ:")
        for r in reminders:
            lines.append(f"  {r['due_at']} — {r['text']}")

    lines.append("\nПОСЛЕДНИЕ СООБЩЕНИЯ:")
    for h in reversed(history):
        who = "Человек" if h["role"] == "user" else "Ты"
        lines.append(f"{who}: {h['text'][:200]}")

    return "\n".join(lines)


_WEB_RE = re.compile(
    r'\b(найди|поищи|погугли|загугли|найдите|поиск|'
    r'погода|прогноз погоды|температура|'
    r'курс (евро|доллар|рубл|фунт|юан|крон)|'
    r'новости|что нового|что происходит|'
    r'что такое|кто такой|кто такая|что значит|'
    r'где находится|адрес|телефон|сайт|часы работы|когда открыт|расписание|'
    r'сколько стоит|цена|стоимость|купить за|'
    r'как добраться|маршрут до|как доехать|'
    r'переведи с|перевод слова|как по-немецки|как по-русски|'
    r'последние|актуальн|свежи|обновлени|только что|прямо сейчас|'
    r'wikipedia|wiki|ближайш|в интернете|в сети|search|google)\b',
    re.IGNORECASE
)


def _needs_web(text: str) -> bool:
    return bool(_WEB_RE.search(text))


def _claude_exec(cmd, timeout):
    """Запуск claude CLI с промптом через STDIN, а не через argv. Большой промпт
    в аргументах командной строки даёт OSError E2BIG «Argument list too long»
    (лимит ОС на argv ~128 КБ) — именно из-за этого агенты «не давали результата».
    cmd = [CLAUDE_BIN, "-p", PROMPT, ...флаги]; позиционный PROMPT снимаем и подаём
    на stdin (claude -p без позиционного промпта читает его из stdin)."""
    if len(cmd) >= 3 and cmd[1] == "-p":
        prompt = cmd[2]
        argv = [cmd[0], cmd[1]] + cmd[3:]
    else:
        prompt, argv = "", cmd
    return subprocess.run(
        argv, input=prompt, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")})


def _web_research_sync(query: str) -> str:
    """Ищет в интернете через Claude + WebSearch/WebFetch, возвращает текстовое резюме."""
    prompt = (
        f"Запрос пользователя: «{query}»\n\n"
        "Найди актуальную информацию в интернете и дай чёткий, фактический ответ по-русски. "
        "Если это погода — текущая температура и прогноз. "
        "Если курс — точное значение на сегодня. "
        "Если адрес/часы — конкретные данные. "
        "Будь краток: 3-6 предложений, только суть, никакой воды. "
        "Если не нашёл — скажи честно."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--model", "haiku",
             "--max-turns", "6"], timeout=90)
        out = (result.stdout or "").strip()
        return out if out else ""
    except Exception as e:
        log.error(f"web research: {e}")
        return ""


def ask_claude_sync(user_text: str) -> dict:
    context = get_context()

    web_block = ""
    if _needs_web(user_text):
        web_data = _web_research_sync(user_text)
        if web_data:
            web_block = f"\n\nВЕБ (актуальные данные из интернета):\n{web_data}"
            log.info(f"web injected: {len(web_data)} chars")

    prompt = f"{context}{web_block}\n\nНОВОЕ СООБЩЕНИЕ ОТ ЧЕЛОВЕКА:\n{user_text}"
    sys_prompt = SECRETARY_PROMPT.replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A"))
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt,
             "--append-system-prompt", sys_prompt,
             "--model", "haiku",
             "--max-turns", "8",
             "--tools", ""], timeout=120)
        raw = result.stdout.strip()
        if not raw or raw.startswith("Error:"):
            log.error(f"Secretary CLI пусто/ошибка: rc={result.returncode} "
                      f"out={raw[:200]!r} err={(result.stderr or '')[:300]!r}")
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return jsonlib.loads(raw[start:end+1])
        if raw.startswith("Error:") or "max turns" in raw.lower() or not raw:
            return {"reply": "", "actions": []}
        return {"reply": raw, "actions": []}
    except Exception as e:
        log.error(f"Claude CLI: {e}")
        return {"reply": "", "actions": []}


# ─── Юрист: налогово-правовой консультант (DE, Freiberufler/§24) ───────────────

LEGAL_KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legal_kb")
STRATEGY_KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_kb")
SALES_KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_kb")
SECRETARY_KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secretary_kb")
DIRECTOR_KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "director_kb")

_KB_INLINE_CACHE = {}


def _kb_inline(path: str, cap: int = 7000) -> str:
    """SKILL.md базы знаний, вшитый прямо в системный промпт (кэш по mtime).
    Экономия токенов: каждый Read-тур агентного цикла пересылает ВЕСЬ контекст
    заново, поэтому «прочитай SKILL.md инструментом Read» стоил в разы дороже,
    чем те же байты, отданные сразу. Reference-файлы агент по-прежнему читает
    Read'ом, но только когда тема реально этого требует."""
    try:
        mtime = os.path.getmtime(path)
        cached = _KB_INLINE_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path, encoding="utf-8") as f:
            txt = f.read()[:cap]
        _KB_INLINE_CACHE[path] = (mtime, txt)
        return txt
    except Exception:
        return ""

LAWYER_PROMPT = """Ты — «Юрист», личный налогово-правовой консультант Вячеслава (Slavik): украинец в Германии со статусом §24 AufenthG (временная защита), работает как художник-фрилансер (Freiberufler Künstler, бренд FARBAHOLIX), Kleinunternehmer §19 UStG, gesetzlich krankenversichert, в KSK пока не состоит.

ТВОЯ БАЗА ЗНАНИЙ — каталог файлов: {kb}
SKILL.md (карта тем) уже вшит в конец этого промпта — НЕ читай его инструментом Read. В references/*.md лежат детали: Freiberufler vs Gewerbe, Kleinunternehmer, ELSTER/EÜR/Steuererklärung, KSK, IHK/Handwerk, Sozialversicherung, письма в инстанции — читай Read'ом ТОЛЬКО нужный файл по карте тем, когда ответ требует деталей/цифр оттуда. Не выдумывай факты, которых там нет.

Контекст §24: украинец на временной защите имеет право на самозанятость (selbständige Erwerbstätigkeit), доступ к gesetzliche Krankenversicherung, может получать Bürgergeld через Jobcenter — доход от самозанятости влияет на эти выплаты (учитывается как Einkommen). Правила §24 и пороги меняются — для актуальных цифр делай web_search, не угадывай.

ТВОИ ЗАДАЧИ:
1. Анализ финансов: тебе дан баланс, счета (Rechnungen) с оборотом по годам, долги, расходы. Оцени налогово-правовую картину, предупреди о рисках: превышение порога Kleinunternehmer (оборот), переквалификация Freiberufler→Gewerbe, обязанность Künstlersozialabgabe как Verwerter при выплатах другим художникам сверх Bagatellgrenze.
2. Сроки: напоминай о подаче деклараций (ESt + Anlage EÜR + Anlage S, обычно к 31 июля) и ежегодных обновлениях. Если просят — поставь напоминание (action remind).
3. Инвойсы (СЧЕТА): когда просят выставить/сделать счёт или PDF-Rechnung — твоя ЕДИНСТВЕННАЯ задача вернуть action invoice с данными (recipient — получатель: название + адрес, каждая часть с новой строки \\n; items — позиции, desc на немецком профессионально с умляутами, price числом; salutation — обращение если известно; intro — вводная фраза на немецком если ясен повод). PDF собирает САМ БОТ по фиксированному шаблону. Ты НЕ рисуешь и НЕ меняешь дизайн счёта, НЕ редактируешь файлы, НЕ пишешь и НЕ запускаешь код, НЕ просишь никаких разрешений/«Allow», НЕ утверждай, что ты обновил дизайн или отредактировал invoice.py — у тебя нет такой возможности и это не нужно. Просто верни action invoice и короткий reply вроде «Готовлю счёт для … на …€». Если не хватает получателя или суммы — спроси одним вопросом. ВАЖНО по НДС: ВСЕГДА по умолчанию — оговорка Kleinunternehmer §19 UStG (без НДС), vat_rate НЕ ставь. Даже если оборот прошлого года превысил порог — НЕ переключай на 19% USt сам: решение отложено до Steuerberater. "vat_rate": 19 только если пользователь прямо скажет, что Steuerberater подтвердил переход.
4. Письма/заявления: по reference letters.md составь готовый текст письма на немецком (Finanzamt, KSK, Krankenkasse, Handwerkskammer, Jobcenter) прямо в reply.
4б. ДОКУМЕНТЫ/БЮРОКРАТИЯ (права Führerschein-Umtausch, §24, паспорт, термины в ведомства): по reference buerokratie.md. В контексте тебе даны открытые «дела» (БЮРОКРАТИЧЕСКИЕ ДЕЛА) — когда пользователь сообщает новость по делу («записался на термин 15.08», «подал заявление», «получил права»), ОБНОВИ дело через action case: {"type":"case","topic":"fuehrerschein","status":"open|waiting|done","next_step":"...","due":"YYYY-MM-DD","note":"..."} (topic из списка в контексте; новую тему заводи с коротким латинским topic). Для актуальных процедур/правил делай web_search.
5. ELSTER: помоги понять, какие формы (Anlage S, Anlage EÜR), как заполнять, какие поля — пошагово.
6. Статус: рекомендуй изменения (вступление в KSK ради экономии ~50% на страховке, переход на Regelbesteuerung, регистрация Gewerbe/GmbH) — но как ОРИЕНТИР; финальное решение и расчёт — со Steuerberater.

ЖЁСТКИЕ ПРАВИЛА:
- НИКОГДА не вписывай в текст/письма/документы реальные IBAN, BIC, Steuernummer, персональный Steuer-Identifikationsnummer. Если форма требует — оставь плейсхолдер вида [Steuernummer].
- Ты не заменяешь Steuerberater: по решениям с налоговыми последствиями давай механику и пороги, но прямо говори, что финал подтверждает бухгалтер.
- Отвечай по-русски, тепло и конкретно. Тексты писем — на немецком, профессионально, с ä ö ü ß.
- Ты НЕ кодинг-агент и НЕ разработчик. Инструменты Read/WebSearch/WebFetch нужны ТОЛЬКО чтобы читать базу знаний ({kb}) и искать актуальные ставки/пороги. Ты НИКОГДА не редактируешь файлы, не пишешь и не запускаешь код/скрипты, не меняешь дизайн или шаблоны, не просишь у пользователя «Allow»/разрешений и не утверждаешь, что что-то отредактировал или задеплоил. Всё, что ты умеешь делать в системе — это вернуть actions (invoice/remind/contact/finance); остальное выполняет бот.

Сегодня: {today}.

ВСЕГДА отвечай строго в JSON:
{"reply": "ответ человеку (может содержать текст письма на немецком)", "actions": [
 {"type": "remind", "when": "2026-07-20 09:00", "text": "подать Einkommensteuererklärung"},
 {"type": "invoice", "recipient": "Galerie X\\nStraße 1\\n60311 Frankfurt", "items": [{"desc": "Künstlerische Wandgestaltung", "price": 1200}], "salutation": "", "customer_no": "", "intro": "", "vat_rate": null},
 {"type": "case", "topic": "fuehrerschein", "status": "waiting", "next_step": "термин в Führerscheinstelle 15.08", "due": "2026-08-15", "note": ""},
 {"type": "contact", "name": "Steuerberater Müller", "note": "ведёт ESt 2025"}
]}
actions может быть пустым []. Никакого текста вне JSON."""


def get_legal_context() -> str:
    """Финансово-правовой срез БД для Юриста: баланс, счета (оборот по годам), долги, платежи."""
    cur_year = datetime.now().year
    with db() as conn:
        balance = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
        cash = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'").fetchone()[0]
        card = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='card'").fetchone()[0]
        fin_last = conn.execute(
            "SELECT amount, comment, account, created_at FROM finance ORDER BY id DESC LIMIT 15").fetchall()
        # Единый источник: invoice_archive (сид + сгенерированные + загруженные) —
        # оборот и «последние счета» считаются по полной картине, а не по журналу бота
        invoices = conn.execute(
            "SELECT number, inv_date AS d, client_name AS recipient, gross AS total, "
            "items AS description FROM invoice_archive "
            "ORDER BY inv_date DESC, id DESC LIMIT 25").fetchall()
        debts = conn.execute(
            "SELECT name, kind, total, paid, due_date, monthly FROM debts ORDER BY kind, due_date").fetchall()
        payments = conn.execute(
            "SELECT title, amount, kind, recur, day FROM payments WHERE active=1 ORDER BY kind, day").fetchall()
    lawyer_summary, history = get_lawyer_memory()

    def _year_of(s):
        s = s or ""
        if "." in s:
            return s.split(".")[-1][:4]
        return s[:4] or "—"

    # Оборот по счетам за год — для анализа порога Kleinunternehmer
    turnover = {}
    for r in invoices:
        turnover[_year_of(r["d"])] = turnover.get(_year_of(r["d"]), 0) + (r["total"] or 0)

    lines = [f"ФИНАНСОВЫЙ СРЕЗ (для налогово-правового анализа), год {cur_year}:",
             f"Баланс: всего {balance:+.2f}€ (наличные {cash:+.2f}€ · карта {card:+.2f}€)"]

    if turnover:
        lines.append("\nОБОРОТ ПО ВЫСТАВЛЕННЫМ СЧЕТАМ (Umsatz, по годам — важно для порога Kleinunternehmer §19):")
        for y in sorted(turnover.keys(), reverse=True):
            lines.append(f"  {y}: {turnover[y]:.2f}€")

    if invoices:
        lines.append("\nПОСЛЕДНИЕ СЧЕТА (Ausgangsrechnungen):")
        for r in invoices[:15]:
            rec = (r["recipient"] or "").split(chr(10))[0][:40]
            lines.append(f"  №{r['number'] or '—'} {r['d'] or ''} · {rec} · {r['total'] or 0:.0f}€ · {(r['description'] or '')[:50]}")

    clients_block = clients_for_context()
    if clients_block:
        lines.append("\n" + clients_block)

    arch = archive_context()
    if arch:
        lines.append("\n" + arch)

    bank = bank_context()
    if bank:
        lines.append("\n" + bank)

    bureau = bureau_context()
    if bureau:
        lines.append("\n" + bureau)

    if fin_last:
        lines.append("\nПОСЛЕДНИЕ ФИНАНСОВЫЕ ОПЕРАЦИИ:")
        for f in fin_last:
            acc = "нал" if f["account"] == "cash" else "карта"
            lines.append(f"  {f['amount']:+.0f}€ — {f['comment']} ({acc}, {f['created_at'][:10]})")

    if debts:
        lines.append("\nДОЛГИ:")
        for x in debts:
            lines.append(f"  [{x['kind']}] {x['name']}: {x['paid']:.0f}/{x['total']:.0f}€"
                         + (f", {x['monthly']:.0f}€/мес" if x["monthly"] else "")
                         + (f", срок {x['due_date']}" if x["due_date"] else ""))

    if payments:
        lines.append("\nРЕГУЛЯРНЫЕ ПЛАТЕЖИ:")
        for p in payments:
            lines.append(f"  {p['title']}: {p['amount']:.0f}€ ({p['recur']}, {p['day']}-го)")

    if lawyer_summary:
        lines.append("\nПАМЯТЬ ЮРИСТА (сводка прошлых консультаций — факты, решения, статусы, сроки):")
        lines.append(lawyer_summary)

    if history:
        lines.append("\nПОСЛЕДНИЙ ДИАЛОГ С ЮРИСТОМ (свежие реплики, дословно):")
        for h in history:
            who = "Человек" if h["role"] == "user" else "Юрист"
            lines.append(f"{who}: {h['text'][:LAWYER_MSG_MAXLEN]}")

    return "\n".join(lines)


def ask_lawyer_sync(user_text: str) -> dict:
    context = get_legal_context()
    prompt = f"{context}\n\nВОПРОС/ЗАПРОС К ЮРИСТУ:\n{user_text}"
    sys_prompt = (LAWYER_PROMPT
                  .replace("{kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    skill = _kb_inline(os.path.join(LEGAL_KB_DIR, "SKILL.md"))
    if skill:
        sys_prompt += "\n\n=== SKILL.md (уже прочитан, Read не нужен) ===\n" + skill
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt,
             "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch",
             "--model", "sonnet",
             "--max-turns", "8"], timeout=240)
        raw = result.stdout.strip()
        if not raw or raw.startswith("Error:"):
            log.error(f"Lawyer CLI пусто/ошибка: rc={result.returncode} "
                      f"out={raw[:200]!r} err={(result.stderr or '')[:300]!r}")
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return jsonlib.loads(raw[start:end + 1])
            except Exception:
                pass
        if raw and not raw.startswith("Error:") and "max turns" not in raw.lower():
            return {"reply": raw, "actions": []}
        return {"reply": "", "actions": []}
    except Exception as e:
        log.error(f"Lawyer CLI: {e}")
        return {"reply": "", "actions": []}


async def ai_lawyer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_text: str):
    """Диалог с Юристом: налогово-правовой консультант с доступом к финансовой БД и базе знаний."""
    save_chat_id(update.effective_chat.id)
    wait = await update.message.reply_text("⚖️ Юрист изучает вопрос и сверяется с базой…")

    resp = await asyncio.get_event_loop().run_in_executor(None, lambda: ask_lawyer_sync(user_text))
    reply = resp.get("reply", "") or "Не смог сформулировать ответ — попробуй переформулировать вопрос."
    actions = resp.get("actions", [])
    applied = apply_actions(actions)

    # Ответ Юриста — в долгую память (вопрос уже записан маршрутизатором _route_text).
    remember_lawyer("lawyer", reply)

    extras = []
    for kind, item_id, text, area, pri in applied:
        if kind == "remind":
            extras.append(f"⏰ напоминание: _{text}_")
        elif kind == "invoice":
            extras.append(f"🧾 _{text}_ — PDF ниже")
        elif kind == "contact":
            extras.append(f"👤 _{text}_")
        elif kind == "finance":
            extras.append(f"💰 _{text}_")
        elif kind == "case":
            extras.append(f"🗂 дело обновлено: _{text}_")

    msg = "⚖️ *Юрист:*\n\n" + reply
    if extras:
        msg += "\n\n" + "\n".join(extras)

    try:
        await ctx.bot.delete_message(update.effective_chat.id, wait.message_id)
    except Exception:
        pass
    # Длинные письма могут не влезть в один Markdown-месседж — режем аккуратно
    for chunk in _split_msg(msg, 3800):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk.replace("*", "").replace("_", ""))

    for kind, _id, _text, path, _pri in applied:
        if kind == "invoice" and path:
            try:
                with open(path, "rb") as doc:
                    await update.message.reply_document(doc, filename=path.split("/")[-1])
            except Exception as e:
                log.error(f"lawyer invoice send: {e}")

    # После ответа: свернуть выпавшие за окно реплики в сводку (в фоне, не задерживает диалог)
    asyncio.get_event_loop().run_in_executor(None, maybe_update_lawyer_summary)


def _split_msg(text: str, limit: int = 3800):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        parts.append(cur)
    return parts


def next_invoice_number() -> str:
    base = datetime.now().strftime("%d%m%y")
    with db() as conn:
        rows = conn.execute(
            "SELECT number FROM invoices WHERE number = ? OR number LIKE ?",
            (base, base + "-%")
        ).fetchall()
    n = len(rows)
    return base if n == 0 else f"{base}-{n}"


# ── Память клиентов ───────────────────────────────────────────────────────────
_CYR2LAT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'i',
    'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
    'х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'і':'i','ї':'i','є':'e','ґ':'g',
}


def _client_norm(s: str) -> str:
    """Нормализация имени для матчинга: строчные, только латиница/цифры.
    Кириллица транслитерируется (САСИС→sasis), диакритика убирается (é→e)."""
    import unicodedata
    s = (s or "").lower()
    s = "".join(_CYR2LAT.get(ch, ch) for ch in s)  # кириллица → латиница
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r'[^a-z0-9]', '', s)


def upsert_client(recipient: str, salutation: str = "", customer_no: str = ""):
    """Запомнить клиента целиком после счёта (полный адрес + обращение)."""
    recipient = (recipient or "").strip()
    if not recipient:
        return
    name = recipient.split("\n")[0].strip()
    key = _client_norm(name)
    if not key:
        return
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO clients(key,name,recipient_full,salutation,customer_no,last_used) "
                "VALUES(?,?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET name=excluded.name, "
                "recipient_full=excluded.recipient_full, "
                "salutation=CASE WHEN excluded.salutation!='' THEN excluded.salutation ELSE clients.salutation END, "
                "customer_no=CASE WHEN excluded.customer_no!='' THEN excluded.customer_no ELSE clients.customer_no END, "
                "last_used=CURRENT_TIMESTAMP",
                (key, name, recipient, salutation or "", customer_no or ""))
    except Exception as e:
        log.error(f"upsert_client: {e}")


def find_client(query: str):
    """Найти клиента по короткому упоминанию. Возвращает Row или None."""
    q = _client_norm(query)
    if len(q) < 3:
        return None
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT name, recipient_full, salutation, customer_no FROM clients "
                "ORDER BY last_used DESC").fetchall()
    except Exception as e:
        log.error(f"find_client: {e}")
        return None
    # сначала точное вхождение имени, потом — по полному адресу
    for r in rows:
        nk = _client_norm(r["name"])
        if nk and (q in nk or nk in q):
            return r
    for r in rows:
        if q in _client_norm(r["recipient_full"]):
            return r
    return None


def clients_for_context(limit: int = 40) -> str:
    """Список известных клиентов для промпта — чтобы по короткому имени бот брал полный адрес."""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT name, recipient_full, salutation, customer_no FROM clients "
                "ORDER BY last_used DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        rows = []
    if not rows:
        return ""
    lines = ["ИЗВЕСТНЫЕ КЛИЕНТЫ (если в просьбе клиент назван коротко — бери ПОЛНЫЙ recipient "
             "и salutation отсюда дословно, адрес НЕ переспрашивай):"]
    for r in rows:
        one = (r["recipient_full"] or "").replace("\n", " | ")
        extra = f" | обращение: {r['salutation']}" if r["salutation"] else ""
        extra += f" | Kd-Nr: {r['customer_no']}" if r["customer_no"] else ""
        lines.append(f"  • {r['name']} → {one}{extra}")
    return "\n".join(lines)


def _valid_iban(v: str) -> bool:
    return bool(re.match(r'^DE\d{20}$', (v or "").replace(" ", "").upper()))


def _valid_bic(v: str) -> bool:
    return bool(re.match(r'^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$', (v or "").replace(" ", "").upper()))


def _mask_tail(v: str, keep: int = 4) -> str:
    v = (v or "").strip()
    return ("…" + v[-keep:]) if len(v) > keep else "***"


def import_own_invoice_sync(path: str):
    """Разобрать присланный документ: если это счёт, выставленный самим владельцем
    (Viacheslav Balabaiev / FARBAHOLIX) — забрать ИЗ НЕГО его реквизиты (в settings,
    только пустые поля, с валидацией) и клиента-получателя (в память клиентов).
    Возвращает {'imported': bool, 'summary': str} либо None, если это не его счёт."""
    prompt = (
        f"Прочитай документ по пути {path} инструментом Read (это может быть PDF или фото "
        "бумажного счёта — распознай текст, даже если снято под углом/с тенями). "
        "Определи, является ли это ИСХОДЯЩИМ счётом (Rechnung), который выставил САМ "
        "Viacheslav Balabaiev (бренд FARBAHOLIX, Graffiti Künstler) — то есть он отправитель/"
        "получатель платежа, а не адресат счёта.\n"
        "Верни СТРОГО JSON без иного текста:\n"
        '{"is_own_invoice": true|false, '
        '"sender": {"iban": "", "bic": "", "steuernummer": "", "ident_nr": ""}, '
        '"client": {"recipient": "получатель счёта: название и адрес, каждая часть с новой строки \\n", '
        '"salutation": "Frau/Herr … если есть", "customer_no": ""}}\n'
        "Реквизиты отправителя (iban/bic/steuernummer/ident_nr) и данные получателя выписывай "
        "ТОЧНО как в документе. Если это НЕ его исходящий счёт — верни is_own_invoice=false и "
        "пустые sender/client."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "6"], timeout=200)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            return None
        data = jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"import_own_invoice: {ex}")
        return None

    if not data.get("is_own_invoice"):
        return None

    saved, skipped = [], []
    snd = data.get("sender") or {}
    # Реквизиты: пишем ТОЛЬКО в пустые поля (не затираем уже заданное), с валидацией.
    def _try_save(field_key, value, label, validator=None):
        value = (value or "").strip()
        if not value:
            return
        if validator and not validator(value):
            skipped.append(f"{label} (не прошло проверку формата)")
            return
        if (_settings_get(field_key) or "").strip():
            skipped.append(f"{label} (уже задано)")
            return
        _settings_set(field_key, value)
        saved.append(f"{label}: {_mask_tail(value)}")

    _try_save("inv_iban", snd.get("iban"), "IBAN", _valid_iban)
    _try_save("inv_bic", snd.get("bic"), "BIC", _valid_bic)
    _try_save("inv_steuernummer", snd.get("steuernummer"), "Steuernummer")
    _try_save("inv_ident_nr", snd.get("ident_nr"), "Steuer-ID")

    cl = data.get("client") or {}
    client_name = ""
    if (cl.get("recipient") or "").strip():
        upsert_client(cl["recipient"], cl.get("salutation", ""), cl.get("customer_no", ""))
        client_name = cl["recipient"].split("\n")[0].strip()

    parts = []
    if client_name:
        parts.append(f"🗂 клиент запомнен: *{client_name}*")
    if saved:
        parts.append("🔐 реквизиты сохранены: " + ", ".join(saved))
    if skipped:
        parts.append("⏭ пропущено: " + ", ".join(skipped))
    if not parts:
        return {"imported": False, "summary": ""}
    return {"imported": bool(client_name or saved), "summary": "\n".join(parts)}


# ── Пакетный анализ года: извлечение инвойса в структурный архив ──────────────
def extract_invoice_full_sync(path: str):
    """Распознать инвойс и вернуть полные структурные поля (для архива/анализа)."""
    prompt = (
        f"Прочитай счёт (Rechnung) по пути {path} инструментом Read (PDF или фото — "
        "распознай даже под углом/с тенями; немецкий формат сумм: 2.000,00 = 2000.00). "
        "Верни СТРОГО JSON без иного текста:\n"
        '{"is_invoice": true|false, "number": "", "date": "YYYY-MM-DD", '
        '"client_name": "название клиента-получателя", '
        '"items": [{"desc": "", "qty": 1, "price": 0.0}], '
        '"net": 0.0, "vat": 0.0, "gross": 0.0, "kleinunternehmer": true|false, '
        '"client_recipient": "получатель: название и адрес, каждая часть с новой строки \\n", '
        '"salutation": "", "customer_no": ""}\n'
        "net — сумма без НДС, vat — сумма НДС (0 если Kleinunternehmer §19), gross — итог. "
        "kleinunternehmer=true если есть оговорка §19 UStG. Если это не счёт — is_invoice=false."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "6"], timeout=200)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            return None
        return jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"extract_invoice_full: {ex}")
        return None


def _year_of_iso(d: str):
    m = re.search(r'(\d{4})', d or "")
    return int(m.group(1)) if m else None


def store_archived_invoice(path: str):
    """Извлечь инвойс и сохранить в invoice_archive (+ клиент). Возвращает ack-строку или None."""
    data = extract_invoice_full_sync(path)
    if not data or not data.get("is_invoice"):
        return None
    number = (data.get("number") or "").strip()
    inv_date = (data.get("date") or "").strip()
    year = _year_of_iso(inv_date)
    client = (data.get("client_name") or "").strip()
    net = float(data.get("net") or 0)
    vat = float(data.get("vat") or 0)
    gross = float(data.get("gross") or 0) or (net + vat)
    klein = 1 if data.get("kleinunternehmer") else 0
    items = data.get("items") or []
    try:
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO invoice_archive "
                "(number, inv_date, year, client_name, items, net, vat, gross, kleinunternehmer, raw_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (number, inv_date, year, client, jsonlib.dumps(items, ensure_ascii=False),
                 net, vat, gross, klein, jsonlib.dumps(data, ensure_ascii=False)))
    except Exception as e:
        log.error(f"store_archived_invoice: {e}")
        return None
    if (data.get("client_recipient") or "").strip():
        upsert_client(data["client_recipient"], data.get("salutation", ""), data.get("customer_no", ""))
    return f"№{number or '—'} · {inv_date or '—'} · {client or '—'} · {gross:.0f}€"


def store_archived_document(path: str):
    """Классифицировать присланный документ (счёт или договор) и сохранить в нужную
    таблицу. В режиме сбора: инвойсы → invoice_archive, договоры → contract_archive.
    Возвращает ('invoice'|'contract'|None, ack-строка)."""
    prompt = (
        f"Прочитай документ по пути {path} инструментом Read (PDF или фото — распознай "
        "даже под углом/с тенями; немецкий формат сумм 2.000,00 = 2000.00). Определи тип: "
        "СЧЁТ (Rechnung) или ДОГОВОР (Vertrag). Верни СТРОГО JSON:\n"
        '{"doc_type": "rechnung"|"vertrag"|"anderes", '
        '"invoice": {"number":"","date":"YYYY-MM-DD","client_name":"","net":0,"vat":0,"gross":0,"kleinunternehmer":true,'
        '"client_recipient":"получатель: название и адрес, каждая часть с \\n","salutation":"","customer_no":"","items":[]}, '
        '"contract": {"client_name":"","client_recipient":"заказчик: название и адрес с \\n","subject":"предмет договора кратко",'
        '"amount":0,"start_date":"YYYY-MM-DD","end_date":"","terms":"ключевые условия кратко: оплата, права на изображения/Urheberrecht, ответственность, расторжение, особое"}}\n'
        "Заполни только релевантную секцию. Числа/даты точно как в документе."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "6"], timeout=200)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            return None, None
        data = jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"store_archived_document: {ex}")
        return None, None

    dt = data.get("doc_type")
    if dt == "rechnung":
        inv = data.get("invoice") or {}
        inv["is_invoice"] = True
        # переиспользуем логику инвойса через прямую запись
        number = (inv.get("number") or "").strip()
        inv_date = (inv.get("date") or "").strip()
        year = _year_of_iso(inv_date)
        client = (inv.get("client_name") or "").strip()
        net = float(inv.get("net") or 0); vat = float(inv.get("vat") or 0)
        gross = float(inv.get("gross") or 0) or (net + vat)
        klein = 1 if inv.get("kleinunternehmer") else 0
        try:
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO invoice_archive "
                    "(number, inv_date, year, client_name, items, net, vat, gross, kleinunternehmer, raw_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (number, inv_date, year, client, jsonlib.dumps(inv.get("items") or [], ensure_ascii=False),
                     net, vat, gross, klein, jsonlib.dumps(inv, ensure_ascii=False)))
        except Exception as e:
            log.error(f"archive invoice: {e}")
            return None, None
        if (inv.get("client_recipient") or "").strip():
            upsert_client(inv["client_recipient"], inv.get("salutation", ""), inv.get("customer_no", ""))
        _archive_pdf_copy(path, number)  # PDF — в постоянное хранилище (для выдачи по запросу)
        return "invoice", f"🧾 счёт №{number or '—'} · {inv_date or '—'} · {client or '—'} · {gross:.0f}€"

    if dt == "vertrag":
        con = data.get("contract") or {}
        client = (con.get("client_name") or "").strip()
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO contract_archive (client_name, subject, amount, start_date, end_date, terms, raw_json) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (client, (con.get("subject") or "")[:400], float(con.get("amount") or 0),
                     con.get("start_date") or "", con.get("end_date") or "",
                     (con.get("terms") or "")[:1500], jsonlib.dumps(con, ensure_ascii=False)))
        except Exception as e:
            log.error(f"archive contract: {e}")
            return None, None
        if (con.get("client_recipient") or "").strip():
            upsert_client(con["client_recipient"], "", "")
        amt = float(con.get("amount") or 0)
        return "contract", f"📄 договор · {client or '—'} · {(con.get('subject') or '')[:40]}" + (f" · {amt:.0f}€" if amt else "")

    return None, None


def contracts_context(limit: int = 20) -> str:
    """Сводка прошлых договоров — чтобы новый договор учитывал типичные условия/нюансы."""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT client_name, subject, amount, start_date, end_date, terms "
                "FROM contract_archive ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        rows = []
    if not rows:
        return ""
    lines = ["ПРОШЛЫЕ ДОГОВОРЫ (используй типичные условия/нюансы отсюда для нового договора; "
             "дизайн старых НЕ копируй):"]
    for r in rows:
        amt = f" · {r['amount']:.0f}€" if r["amount"] else ""
        lines.append(f"  • {r['client_name'] or '—'}: {(r['subject'] or '')[:60]}{amt}")
        if r["terms"]:
            lines.append(f"      условия: {(r['terms'] or '')[:300]}")
    return "\n".join(lines)


def year_archive_rows(year: int):
    try:
        with db() as conn:
            return conn.execute(
                "SELECT number, inv_date, client_name, net, vat, gross, kleinunternehmer "
                "FROM invoice_archive WHERE year = ? ORDER BY inv_date, number", (year,)).fetchall()
    except Exception:
        return []


# ── Единый контур счетов: регистрация, PDF-хранилище, выдача по запросу ───────

def _archive_pdf_copy(src_path: str, number: str) -> str:
    """Копия PDF счёта в постоянное хранилище invoices_pdf/<номер>.pdf."""
    try:
        if not src_path or not os.path.exists(src_path):
            return ""
        os.makedirs(INVOICES_PDF_DIR, exist_ok=True)
        safe = re.sub(r"[^\w.\-]", "_", (number or "").strip()) or datetime.now().strftime("%Y%m%d%H%M%S")
        dest = os.path.join(INVOICES_PDF_DIR, f"{safe}.pdf")
        import shutil
        shutil.copyfile(src_path, dest)
        return dest
    except Exception as e:
        log.error(f"pdf archive copy: {e}")
        return ""


def invoice_pdf_path(number: str) -> str:
    """Путь к PDF счёта в хранилище по номеру ('' — файла нет)."""
    safe = re.sub(r"[^\w.\-]", "_", (number or "").strip())
    p = os.path.join(INVOICES_PDF_DIR, f"{safe}.pdf")
    return p if safe and os.path.exists(p) else ""


def register_own_invoice(number, recipient, customer_no, desc, total, pdf_path, vat_rate=None):
    """ЕДИНАЯ регистрация выставленного счёта: журнал invoices + аналитический
    invoice_archive (оборот, /showinvoices, .xls — «таблица» Юриста) + постоянная
    PDF-копия. Раньше сгенерированные счета попадали только в invoices — Директор
    и вся аналитика их не видели (кейс «Cosmopop 2000€»)."""
    today_iso = datetime.now().strftime("%Y-%m-%d")
    client = (recipient or "").split(chr(10))[0].strip()
    try:
        rate = float(vat_rate) if vat_rate else 0.0
    except (TypeError, ValueError):
        rate = 0.0
    gross = float(total or 0)
    net = round(gross / (1 + rate / 100), 2) if rate else gross
    vat = round(gross - net, 2)
    with db() as conn:
        conn.execute(
            "INSERT INTO invoices (number, date, recipient, customer_no, description, total, source) "
            "VALUES (?,?,?,?,?,?, 'bot')",
            (number, datetime.now().strftime("%d.%m.%Y"), client, customer_no or "", desc, gross))
        conn.execute(
            "INSERT OR IGNORE INTO invoice_archive "
            "(number, inv_date, year, client_name, items, net, vat, gross, kleinunternehmer, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (number, today_iso, datetime.now().year, client,
             jsonlib.dumps([desc], ensure_ascii=False), net, vat, gross,
             0 if rate else 1, jsonlib.dumps({"source": "bot", "desc": desc}, ensure_ascii=False)))
    _archive_pdf_copy(pdf_path, number)


def looks_like_invoice_fetch(text: str) -> bool:
    """Просьба ПРИСЛАТЬ готовые PDF счетов (не выставить новый): «пришли инвойс
    Cosmopop», «скинь все счета за 2026», «отправь Rechnung 39». Проверяется
    ДО looks_like_invoice_request — глаголы отправки, не создания."""
    t = text or ""
    return bool(re.search(
        r"(пришл|скин|отправ|вышл|перешл|покаж|сгруз|выгруз|найд)\w*[^.\n]{0,40}"
        r"(сч[ёе]т|инвойс|invoice|rechnung|pdf)", t, re.IGNORECASE))


_RU2LAT = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
                         "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
                         "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
                         "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y",
                         "ь": "", "э": "e", "ю": "yu", "я": "ya"})


def _inv_norm(s: str) -> str:
    """Нормализация имени для матчинга «космопоп» ↔ «Cosmopop»: нижний регистр,
    транслит кириллицы, c→k."""
    return (s or "").lower().replace("ё", "е").translate(_RU2LAT).replace("c", "k")


_INV_STOP = {"пришли", "скинь", "отправь", "вышли", "покажи", "сгрузи", "выгрузи", "найди",
             "перешли", "мне", "все", "счета", "инвойс", "инвойсы", "инвойса", "rechnung",
             "invoice", "pdf", "евро", "eur", "год", "года", "пожалуйста", "для", "сумму"}


def find_invoice_rows(query: str):
    """Детерминированный поиск по единой таблице invoice_archive (0 токенов):
    «все [за 2026]» · точный номер · сумма ±1€ · клиент (с транслитом)."""
    q = (query or "").lower().replace("ё", "е")
    rows = all_archive_rows()
    # Год — только с предлогом («за 2026», «в 2025», «2026 год»): иначе сумма
    # вроде «на 2000 евро» ошибочно принималась за год и убивала совпадения
    year_m = re.search(r"(?:за|в)\s+(20\d{2})\b|\b(20\d{2})\s*год", q)
    year = int(year_m.group(1) or year_m.group(2)) if year_m else None

    def _yr(r):
        return year is None or r["year"] == year

    if re.search(r"\bвсе\b", q):
        return [r for r in rows if _yr(r)]
    # точный номер
    for tok in re.findall(r"[\w\-]+", q):
        if re.fullmatch(r"r?\d{1,4}(-\d+)?|\d{8}-\d+", tok):
            hit = [r for r in rows
                   if (r["number"] or "").lower().lstrip("r") == tok.lstrip("r")]
            if hit:
                return hit
    sel, used = [], False
    # сумма (gross ±1€)
    for tok in re.findall(r"\d{2,6}(?:[.,]\d{2})?", q):
        try:
            val = float(tok.replace(",", "."))
        except ValueError:
            continue
        if val >= 20:
            hit = [r for r in rows if abs((r["gross"] or 0) - val) < 1.0 and _yr(r)]
            if hit:
                used = True
                sel += [r for r in hit if r not in sel]
    # клиент (подстрока, транслит-нормализация)
    for w in re.findall(r"[a-zа-я]{3,}", q):
        if w in _INV_STOP:
            continue
        wn = _inv_norm(w)
        hit = [r for r in rows if wn and wn in _inv_norm(r["client_name"]) and _yr(r)]
        if hit:
            used = True
            sel += [r for r in hit if r not in sel]
    if not used and year is not None:
        return [r for r in rows if r["year"] == year]
    if not sel:
        # «счета 2026» без предлога: голое 20xx считаем годом, только если такой
        # год реально есть в архиве (сумму 2000-2099 это не заденет)
        m = re.search(r"\b(20\d{2})\b", q)
        if m and int(m.group(1)) in {r["year"] for r in rows}:
            return [r for r in rows if r["year"] == int(m.group(1))]
    return sel


async def send_invoice_pdfs(update: Update, query: str):
    """Отправить PDF счетов по описанию. В сами PDF не заглядываем: матчим по
    данным единой таблицы, шлём готовые файлы из хранилища. Работает и у
    Директора, и у Юриста (шлётся ботом, чей update)."""
    rows = find_invoice_rows(query)
    if not rows:
        recent = all_archive_rows()[-5:]
        hint = "\n".join(
            f"• {r['number'] or '—'} · {r['inv_date'] or ''} · {r['client_name'] or ''} · {r['gross'] or 0:.0f}€"
            for r in reversed(recent)) or "таблица пуста"
        await update.message.reply_text(
            "Не нашёл счетов по этому описанию. Последние в таблице:\n" + hint
            + "\n\nУточни: клиент / номер / сумма / «все за 2026».")
        return
    total = sum(r["gross"] or 0 for r in rows)
    await update.message.reply_text(f"🧾 Нашёл: {len(rows)} шт · {total:.0f}€. Отправляю PDF…")
    missing = []
    for r in rows[:40]:
        p = invoice_pdf_path(r["number"] or "")
        if not p:
            missing.append(f"{r['number'] or '—'} ({r['client_name'] or ''})")
            continue
        try:
            with open(p, "rb") as doc:
                await update.message.reply_document(doc, filename=os.path.basename(p))
        except Exception as e:
            log.error(f"send invoice pdf {p}: {e}")
    tail = []
    if len(rows) > 40:
        tail.append(f"…показал 40 из {len(rows)} — уточни запрос.")
    if missing:
        tail.append("Есть в таблице, но без PDF на сервере: " + ", ".join(missing[:10])
                    + ". Пришли эти PDF мне или Юристу — сохраню в хранилище.")
    if tail:
        await update.message.reply_text("\n".join(tail))


def all_archive_rows():
    """Все инвойсы архива по всем годам, по возрастанию даты."""
    try:
        with db() as conn:
            return conn.execute(
                "SELECT number, inv_date, year, client_name, net, vat, gross, kleinunternehmer "
                "FROM invoice_archive ORDER BY year, inv_date, number").fetchall()
    except Exception:
        return []


def archive_years():
    """Список годов, за которые есть инвойсы (по возрастанию)."""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT year FROM invoice_archive WHERE year IS NOT NULL ORDER BY year").fetchall()
        return [r["year"] for r in rows]
    except Exception:
        return []


def year_archive_context(year: int = 2025) -> str:
    """Компактная сводка архива за год для контекста — БЕЗ перечитывания PDF."""
    rows = year_archive_rows(year)
    if not rows:
        return ""
    total = sum((r["gross"] or 0) for r in rows)
    net_total = sum((r["net"] or 0) for r in rows)
    vat_total = sum((r["vat"] or 0) for r in rows)
    by_client = {}
    for r in rows:
        by_client[r["client_name"] or "—"] = by_client.get(r["client_name"] or "—", 0) + (r["gross"] or 0)
    lines = [f"АРХИВ ИНВОЙСОВ {year} (из присланных счетов, {len(rows)} шт — используй как ФАКТЫ, файлы не перечитывай):",
             f"  Итоговый оборот (brutto): {total:.2f}€ · netto {net_total:.2f}€ · USt {vat_total:.2f}€"]
    lines.append("  По клиентам: " + "; ".join(f"{k}: {v:.0f}€" for k, v in sorted(by_client.items(), key=lambda x: -x[1])))
    lines.append("  Счета:")
    for r in rows:
        lines.append(f"    №{r['number'] or '—'} {r['inv_date'] or ''} · {(r['client_name'] or '—')[:28]} · "
                     f"{r['gross'] or 0:.0f}€{' §19' if r['kleinunternehmer'] else ''}")
    saved = _settings_get(f"analysis_summary_{year}")
    if saved:
        lines.append(f"\nСВОДКА-ВЫВОДЫ ПО {year} (уже сделанный анализ):\n{saved}")
    return "\n".join(lines)


# ── Бюрократические дела (права, §24, паспорт, KSK…) ─────────────────────────
def upsert_bureau_case(topic, title=None, status=None, next_step=None, due_date=None, note=None):
    """Создать/обновить дело по теме. Пустые поля не затирают существующие."""
    topic = (topic or "").strip().lower()
    if not topic:
        return
    try:
        with db() as conn:
            row = conn.execute("SELECT id FROM bureau_cases WHERE topic=?", (topic,)).fetchone()
            if row:
                sets, vals = [], []
                for col, v in [("title", title), ("status", status), ("next_step", next_step),
                               ("due_date", due_date), ("note", note)]:
                    if v is not None and str(v).strip() != "":
                        sets.append(f"{col}=?"); vals.append(str(v).strip())
                if sets:
                    sets.append("updated_at=CURRENT_TIMESTAMP")
                    conn.execute(f"UPDATE bureau_cases SET {', '.join(sets)} WHERE topic=?", (*vals, topic))
            else:
                conn.execute(
                    "INSERT INTO bureau_cases(topic,title,status,next_step,due_date,note) VALUES(?,?,?,?,?,?)",
                    (topic, title or topic, status or "open", next_step or "", due_date or "", note or ""))
    except Exception as e:
        log.error(f"upsert_bureau_case: {e}")


def ensure_bureau_seed():
    """Стартовые бюрократические треки владельца (однократно, только если пусто)."""
    try:
        with db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM bureau_cases").fetchone()[0]
        if n:
            return
    except Exception:
        return
    upsert_bureau_case("fuehrerschein", "Обмен украинских прав на немецкие (Umtausch)",
                       "open", "Записаться в Führerscheinstelle Frankfurt (frankfurt.de) и уточнить пакет: перевод прав, Sehtest, фото", "",
                       "По §24 ездить можно с украинскими; обмен — подстраховка до конца защиты. См. legal_kb/references/buerokratie.md")
    upsert_bureau_case("aufenthalt24", "Aufenthalt §24 — срок действия/продление",
                       "open", "Проверить срок действия карты §24 и правила продления (Ausländerbehörde Frankfurt)", "",
                       "Держать копии; следить за анонсами о продлении временной защиты")
    upsert_bureau_case("ua-pass", "Украинский загранпаспорт — срок действия",
                       "open", "Проверить срок действия; при <12 мес — записаться в консульство/паспортный сервис", "", "")
    upsert_bureau_case("ksk", "KSK — вступление (экономия ~50% на страховке)",
                       "open", "Собрать доказательства художественной деятельности (счета есть) и подать Antrag", "",
                       "См. legal_kb/references/ksk.md")
    upsert_bureau_case("est2025", "Steuererklärung 2025 (ESt + EÜR + Anlage S)",
                       "open", "Подготовить EÜR по инвойсам и банковской картине; подать до 31.07.2026", "2026-07-31",
                       "Данные готовы: инвойсы + bank_seed. Финал — со Steuerberater")
    log.info("bureau_cases: стартовые треки созданы")


def bureau_context() -> str:
    """Открытые бюрократические дела для контекста Юриста."""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT topic,title,status,next_step,due_date,note FROM bureau_cases "
                "WHERE status != 'done' ORDER BY CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date").fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["БЮРОКРАТИЧЕСКИЕ ДЕЛА (открытые треки; обновляй через action case при новостях от пользователя):"]
    for r in rows:
        due = f" · срок {r['due_date']}" if r["due_date"] else ""
        lines.append(f"  • [{r['topic']}] {r['title']} — {r['status']}{due}\n    следующий шаг: {r['next_step'] or '—'}")
    return "\n".join(lines)


def bureau_digest_text() -> str:
    """Текст еженедельной сводки по открытым делам (детерминированный, без LLM)."""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT topic,title,status,next_step,due_date FROM bureau_cases "
                "WHERE status != 'done' ORDER BY CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date").fetchall()
    except Exception:
        rows = []
    if not rows:
        return ""
    today = datetime.now(BERLIN).date() if BERLIN else date.today()
    lines = ["🗂 *Еженедельная сводка: документы и бюрократия*\n"]
    for r in rows:
        flag = "🟡"
        due = ""
        if r["due_date"]:
            try:
                d = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
                days = (d - today).days
                due = f" · срок {d.strftime('%d.%m.%Y')} ({'просрочен' if days < 0 else f'через {days} дн.'})"
                flag = "🔴" if days < 14 else "🟡"
            except Exception:
                due = f" · срок {r['due_date']}"
        lines.append(f"{flag} *{r['title']}*{due}\n   → {r['next_step'] or 'следующий шаг не задан'}")
    lines.append("\n_Обновить: просто расскажи Юристу новость («записался на термин 15.08») — он изменит статус. Полный список: /docs_")
    return "\n".join(lines)


async def bureau_digest_check(ctx: ContextTypes.DEFAULT_TYPE):
    """Еженедельная сводка (шлётся из jurist_bot по понедельникам)."""
    chat_id = get_chat_id()
    if not chat_id:
        return
    key = f"bureau_digest:{(datetime.now(BERLIN) if BERLIN else datetime.now()).strftime('%G-%V')}"
    if _settings_get(key):
        return  # уже слали на этой ISO-неделе
    text = bureau_digest_text()
    if not text:
        return
    _settings_set(key, "1")
    if _send_via_director(text):
        return  # доставлено в чат главного бота (Директора)
    try:
        await ctx.bot.send_message(chat_id, text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"bureau digest send: {e}")


def bank_context() -> str:
    """Сводка банковских выписок из bank_seed.json (Naspa, 12.2024–12.2025) для
    контекста Юриста/стратега: помесячные потоки, категории, деловые операции.
    Личные траты — только агрегатами. Файл собран из выписок офлайн, оригиналы удалены."""
    d = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(d, "bank_seed.json")
    if not os.path.exists(path):
        return ""
    try:
        seed = jsonlib.load(open(path, encoding="utf-8"))
    except Exception as e:
        log.error(f"bank_seed: {e}")
        return ""
    lines = [f"БАНКОВСКИЕ ВЫПИСКИ ({seed['meta']['period']}, {seed['meta']['transactions_parsed']} операций — ФАКТЫ, файлы не читать):",
             "Помесячно (приход/расход):"]
    for m, v in seed.get("monthly", {}).items():
        lines.append(f"  {m}: +{v['in']:.0f} / {v['out']:.0f}")
    lines.append("Категории за период:")
    for c, v in seed.get("categories", {}).items():
        lines.append(f"  {c}: {v['total']:.0f}€ ({v['count']})")
    # ПОЛНЫЙ список операций (деловые + личные) — компактно, одна строка на операцию.
    # Отфильтрованное подмножество в контексте путало бота («это все транзакции?»),
    # поэтому даём всё; формат ужат до минимума, чтобы не раздувать промпт.
    txs = seed.get("transactions") or seed.get("business_transactions", [])
    if txs:
        label = "ВСЕ ОПЕРАЦИИ ПО СЧЁТУ" if seed.get("transactions") else "Деловые операции (полного списка нет)"
        lines.append(f"{label} ({len(txs)} шт, деловые и личные, полный список — ничего не отфильтровано):")
        for t in txs:
            d = t["date"]
            lines.append(f"  {d[:6]}{d[8:]} {t['amount']:+.0f} [{t['cat']}] {(t['party'] or '')[:44]}")
    lines.append("ВАЖНО для Юриста: subcontractor_artists — выплаты другим художникам "
                 "(релевантно Künstlersozialabgabe); client_income по банку сверяй с инвойсами "
                 "(расхождение = наличные/неоплаченные счета). Суммы выше в €. "
                 f"Тот же список в JSON: {path} (ключ transactions).")
    return "\n".join(lines)


def archive_context() -> str:
    """Компактная сводка архива ПО ВСЕМ ГОДАМ для контекста — БЕЗ перечитывания PDF.
    Оборот считается по годам (важно для годового порога Kleinunternehmer §19)."""
    rows = all_archive_rows()
    if not rows:
        return ""
    by_year = {}
    for r in rows:
        y = r["year"] or 0
        d = by_year.setdefault(y, {"g": 0.0, "n": 0.0, "v": 0.0, "cnt": 0})
        d["g"] += r["gross"] or 0
        d["n"] += r["net"] or 0
        d["v"] += r["vat"] or 0
        d["cnt"] += 1
    lines = [f"АРХИВ ИНВОЙСОВ ({len(rows)} шт по всем годам — это ФАКТЫ из присланных счетов, "
             "файлы НЕ перечитывай):",
             "ОБОРОТ ПО ГОДАМ (Umsatz, важно для годового порога Kleinunternehmer §19):"]
    for y in sorted(by_year):
        d = by_year[y]
        lines.append(f"  {y}: {d['g']:.2f}€ brutto (netto {d['n']:.2f} · USt {d['v']:.2f}) · {d['cnt']} счетов")
    lines.append("Счета:")
    for r in rows:
        lines.append(f"  №{r['number'] or '—'} {r['inv_date'] or ''} · {(r['client_name'] or '—')[:26]} · "
                     f"{r['gross'] or 0:.0f}€{' §19' if r['kleinunternehmer'] else ''}")
    saved = _settings_get("analysis_summary_all")
    if saved:
        lines.append(f"\nСВОДКА-ВЫВОДЫ (уже сделанный совокупный анализ):\n{saved}")
    return "\n".join(lines)


def _esc_x(v) -> str:
    import html as _html
    return _html.escape(str(v if v is not None else ""))


def _eur_de(n) -> str:
    """2000 → «2.000,00»."""
    s = f"{float(n or 0):,.2f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def export_invoices_xls() -> str:
    """Собрать .xls (HTML-таблица, без зависимостей) со ВСЕМИ инвойсами архива
    по всем годам: подытоги по каждому году + общий итог. Оформление — в стиле
    инвойсов (шапка FARBAHOLIX, красный акцент, тёмная строка заголовков)."""
    rows = all_archive_rows()
    stand = datetime.now().strftime("%d.%m.%Y")
    g_all = sum((r["gross"] or 0) for r in rows)
    n_all = sum((r["net"] or 0) for r in rows)
    v_all = sum((r["vat"] or 0) for r in rows)
    years = sorted({(r["year"] or 0) for r in rows})

    def cell(v, extra=""):
        return f"<td style='border:1px solid #cfcfcf;padding:6px 8px;{extra}'>{v}</td>"

    body, idx = [], 0
    for y in years:
        yrows = [r for r in rows if (r["year"] or 0) == y]
        yg = sum((r["gross"] or 0) for r in yrows)
        yn = sum((r["net"] or 0) for r in yrows)
        yv = sum((r["vat"] or 0) for r in yrows)
        body.append(
            f"<tr><td colspan='8' style='background:#b23a3a;color:#fff;font-weight:700;"
            f"padding:7px 8px'>{y or '—'}</td></tr>")
        for r in yrows:
            idx += 1
            bg = "#ffffff" if idx % 2 else "#f7f7f7"
            klein = "§19" if r["kleinunternehmer"] else "USt"
            c = f"border:1px solid #cfcfcf;background:{bg};padding:6px 8px"
            body.append(
                f"<tr>"
                f"<td style='{c}'>{idx}</td>"
                f"<td style='{c}'>{_esc_x(r['number'])}</td>"
                f"<td style='{c}'>{_esc_x(r['inv_date'])}</td>"
                f"<td style='{c}'>{_esc_x(r['client_name'])}</td>"
                f"<td style='{c};text-align:right'>{_eur_de(r['net'])}</td>"
                f"<td style='{c};text-align:right'>{_eur_de(r['vat'])}</td>"
                f"<td style='{c};text-align:right;font-weight:700'>{_eur_de(r['gross'])}</td>"
                f"<td style='{c};text-align:center'>{klein}</td>"
                f"</tr>")
        sc = "border:1px solid #222;padding:7px 8px;font-weight:700;background:#efefef"
        body.append(
            f"<tr><td colspan='4' style='{sc}'>Summe {y or '—'}</td>"
            f"<td style='{sc};text-align:right'>{_eur_de(yn)}</td>"
            f"<td style='{sc};text-align:right'>{_eur_de(yv)}</td>"
            f"<td style='{sc};text-align:right'>{_eur_de(yg)}</td>"
            f"<td style='{sc}'></td></tr>")

    th = "background:#333333;color:#ffffff;font-weight:700;border:1px solid #222;padding:8px 8px;text-align:left"
    thr = th + ";text-align:right"
    gc = "border:2px solid #222;padding:9px 8px;font-weight:700;background:#dddddd;font-size:14px"
    html = f"""<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8">
<style>body{{font-family:'Helvetica Neue',Arial,sans-serif;color:#1a1a1a}}</style></head><body>
<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px">
  <tr><td colspan="8" style="font-size:22px;font-weight:700;padding:6px 8px 0">FARBAHOLIX</td></tr>
  <tr><td colspan="8" style="color:#b23a3a;font-size:14px;padding:0 8px 2px">Rechnungen — Gesamtübersicht</td></tr>
  <tr><td colspan="8" style="border-bottom:4px solid #b23a3a;height:4px;padding:0"></td></tr>
  <tr><td colspan="8" style="padding:8px;color:#555">Stand: {stand} · Belege: {len(rows)} · Jahre: {', '.join(str(y) for y in years) or '—'}</td></tr>
  <tr><td colspan="8" style="height:4px"></td></tr>
  <tr>
    <th style="{th}">#</th><th style="{th}">Rechnung Nr.</th><th style="{th}">Datum</th>
    <th style="{th}">Kunde</th><th style="{thr}">Netto (€)</th><th style="{thr}">USt (€)</th>
    <th style="{thr}">Brutto (€)</th><th style="{th};text-align:center">Steuer</th>
  </tr>
  {''.join(body)}
  <tr>
    <td colspan="4" style="{gc}">Gesamt (alle Jahre)</td>
    <td style="{gc};text-align:right">{_eur_de(n_all)}</td>
    <td style="{gc};text-align:right">{_eur_de(v_all)}</td>
    <td style="{gc};text-align:right">{_eur_de(g_all)}</td>
    <td style="{gc}"></td>
  </tr>
</table></body></html>"""
    out_path = os.path.join(tempfile.gettempdir(), "Rechnungen_alle.xls")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def analyze_all_sync() -> str:
    """Совокупный юр-анализ ВСЕХ инвойсов архива по всем годам. Сохраняет сводку."""
    rows = all_archive_rows()
    if not rows:
        return ""
    table = archive_context()
    years = archive_years()
    yrs = ", ".join(str(y) for y in years) or "—"
    sys_prompt = (LAWYER_PROMPT
                  .replace("{kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    prompt = (
        f"{get_legal_context()}\n\n"
        f"ЗАДАЧА: сделай СОВОКУПНЫЙ налогово-правовой анализ ВСЕХ инвойсов за годы {yrs} "
        "(данные ниже — уже распознанная таблица, файлы перечитывать НЕ нужно). "
        "Не разбирай счета по одному — дай выводы по всей картине, ОБЯЗАТЕЛЬНО в разрезе ПО ГОДАМ:\n"
        "1) оборот (Umsatz) ПО КАЖДОМУ году и как он соотносится с порогом Kleinunternehmer "
        "(§19 UStG) для этого года — в каком году порог превышен, с какого момента статус "
        "Kleinunternehmer теряется и появляется обязанность по НДС (Regelbesteuerung);\n"
        "2) динамика год к году, распределение по клиентам, риски (переквалификация Freiberufler→"
        "Gewerbe, зависимость от одного заказчика);\n"
        "3) что это значит для деклараций каждого года (ESt, Anlage EÜR/S, при необходимости USt);\n"
        "4) конкретные рекомендации и следующие шаги (финал — со Steuerberater).\n"
        "Ответ по-русски, структурно, по годам. В reply — сам анализ; actions по необходимости.\n\n"
        f"{table}"
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch", "--model", "sonnet", "--max-turns", "10"], timeout=300)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        reply = ""
        if s >= 0 and e > s:
            try:
                reply = (jsonlib.loads(raw[s:e + 1]) or {}).get("reply", "")
            except Exception:
                reply = ""
        if not reply:
            reply = raw
        if reply:
            _settings_set("analysis_summary_all", reply[:6000])
        return reply
    except Exception as e:
        log.error(f"analyze_all: {e}")
        return ""


# ── Стратегический совет: финансист + маркетолог + арт-менеджер (+ юр-контекст) ─
STRATEGY_PROMPT = """Ты — модератор СТРАТЕГИЧЕСКОГО СОВЕТА для художника-фрилансера Вячеслава (Slavik), бренд FARBAHOLIX: граффити/мурал Künstler в Германии, украинец на §24 (временная защита), Kleinunternehmer §19 (оборот превысил порог — статус под вопросом), gesetzlich krankenversichert, в KSK не состоит, есть долги. Задача — дать КОМПЛЕКСНЫЕ антикризисные стратегические рекомендации.

В совете три эксперта — прочитай их базы знаний инструментом Read ПЕРЕД ответом:
- 💰 Финансист: {kb}/references/finance.md
- 📣 Маркетолог: {kb}/references/marketing.md
- 🎨 Арт-менеджер: {kb}/references/art-manager.md
Карта совета и правила: {kb}/SKILL.md. Налогово-правовой контекст (Kleinunternehmer, KSK, §24, декларации) — из {legal_kb} (читай при необходимости).

ГЛАВНОЕ: рекомендации строй ИЗ ДАННЫХ. Тебе дана реальная картина из таблицы инвойсов (оборот по годам, по клиентам, число счетов), финансов (баланс, долги, платежи) И ПЛАНОВ владельца из friedman_bot (проекты, шаги, цели, парковка задач, события). Считай тренды год-к-году, средний чек, концентрацию по клиентам, сезонность, кэш против долгов. ОБЯЗАТЕЛЬНО увязывай рекомендации с уже существующими проектами/целями/задачами владельца — что усилить, что притормозить, что добавить. Не выдумывай цифры; если чего-то не хватает — скажи, что домерить. Для актуальных ставок/порогов/рыночных цен можешь сделать web_search.

Ответ дай по-русски, структурно, приоритет — конкретные действия:
1. КАРТИНА — диагноз по цифрам (оборот и тренд по годам, средний чек, топ-клиенты и концентрация/риск зависимости, сезонность, кэш vs долги).
2. ТРИ ВЗГЛЯДА — по сжатому блоку от Финансиста, Маркетолога, Арт-менеджера: главный риск + главный рычаг у каждого.
3. ЕДИНЫЙ ПЛАН ВЫХОДА ИЗ КРИЗИСА — интегрированный, приоритизированный: 30 дней (кэш, срочные долги) / 90 дней (поток заказов, цена, каналы) / 6–12 мес (позиционирование, диверсификация, статус §19/KSK). Каждый шаг — конкретный, измеримый, с ожидаемым эффектом.
4. РИСКИ И РАЗВИЛКИ — включая налоговые (переход на Regelbesteuerung, KSK, Gewerbe) с пометкой, что финал по налогам подтверждает Steuerberater.

Жёсткие правила: не заменяй Steuerberater (давай механику и пороги); не выдумывай данные; учитывай §24 (доход влияет на Bürgergeld/Jobcenter); без воды.

Сегодня: {today}.

Ответь строго в JSON: {"reply": "весь текст рекомендаций (можно с заголовками и списками)", "actions": []}. actions по желанию (remind/contact). Никакого текста вне JSON."""


def get_plans_context() -> str:
    """Все планы владельца из friedman_bot: проекты+шаги, цели, парковка, события.
    Для стратегического совета — чтобы рекомендации учитывали, что человек уже задумал."""
    try:
        with db() as conn:
            projects = conn.execute("SELECT id, name, area FROM projects ORDER BY id DESC LIMIT 30").fetchall()
            steps = conn.execute("SELECT project_id, text, done FROM steps").fetchall()
            goals = conn.execute("SELECT text, area, period FROM goals WHERE done=0 ORDER BY id DESC LIMIT 30").fetchall()
            chaos = conn.execute("SELECT text, area, priority FROM chaos WHERE done=0 ORDER BY id DESC LIMIT 40").fetchall()
            today = datetime.now().strftime("%Y-%m-%d")
            events = conn.execute("SELECT text, date, time FROM events WHERE date >= ? ORDER BY date LIMIT 20", (today,)).fetchall()
    except Exception as e:
        log.error(f"get_plans_context: {e}")
        return ""
    lines = []
    if projects:
        steps_by = {}
        for s in steps:
            steps_by.setdefault(s["project_id"], []).append(s)
        lines.append("ПРОЕКТЫ (и шаги):")
        for p in projects:
            ps = steps_by.get(p["id"], [])
            done = sum(1 for s in ps if s["done"])
            lines.append(f"  • {p['name']} [{p['area']}] — шагов {done}/{len(ps)}")
            for s in ps[:8]:
                lines.append(f"      {'✓' if s['done'] else '·'} {(s['text'] or '')[:80]}")
    if goals:
        lines.append("ЦЕЛИ:")
        for g in goals:
            lines.append(f"  • [{g['period']}/{g['area']}] {(g['text'] or '')[:100]}")
    if chaos:
        lines.append("ПАРКОВКА (незакрытые задачи/идеи):")
        for c in chaos:
            lines.append(f"  • ({c['priority']}/{c['area']}) {(c['text'] or '')[:100]}")
    if events:
        lines.append("БЛИЖАЙШИЕ СОБЫТИЯ:")
        for e in events:
            lines.append(f"  • {e['date']} {e['time'] or ''} {(e['text'] or '')[:80]}")
    if not lines:
        return ""
    return "ПЛАНЫ ВЛАДЕЛЬЦА (из friedman_bot — учитывай в стратегии, увязывай рекомендации с ними):\n" + "\n".join(lines)


def strategy_council_sync() -> str:
    """Комплексные антикризисные рекомендации на основе картины из таблицы инвойсов
    и финансов. Синтез финансиста + маркетолога + арт-менеджера (+ юр-контекст)."""
    sys_prompt = (STRATEGY_PROMPT
                  .replace("{kb}", STRATEGY_KB_DIR)
                  .replace("{legal_kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    plans = get_plans_context()
    prompt = (
        f"{get_legal_context()}\n\n"
        + (plans + "\n\n" if plans else "")
        + "ЗАПРОС: собери СТРАТЕГИЧЕСКИЙ СОВЕТ и дай комплексные антикризисные "
        "рекомендации по картине выше (таблица инвойсов по годам + финансы + планы "
        "владельца). Увяжи рекомендации с уже существующими проектами/целями/задачами. "
        "Карта совета уже в системном промпте; файлы экспертов (references/finance.md, "
        "marketing.md, art-manager.md) читай Read'ом по мере надобности, затем отвечай "
        "по структуре из системного промпта."
    )
    skill = _kb_inline(os.path.join(STRATEGY_KB_DIR, "SKILL.md"))
    if skill:
        sys_prompt += "\n\n=== SKILL.md (уже прочитан, Read не нужен) ===\n" + skill
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch", "--model", "sonnet", "--max-turns", "10"], timeout=360)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        reply = ""
        if s >= 0 and e > s:
            try:
                reply = (jsonlib.loads(raw[s:e + 1]) or {}).get("reply", "")
            except Exception:
                reply = ""
        if not reply:
            reply = raw
        if reply:
            _settings_set("strategy_summary", reply[:6000])
        return reply
    except Exception as e:
        log.error(f"strategy_council: {e}")
        return ""


def ensure_strategy_kb():
    """Самолечение: подтянуть strategy_kb с ветки, если файлов нет на диске."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    need = [x for x in UPDATE_FILES if x.startswith("strategy_kb/")]
    for f in need:
        dest = os.path.join(d, f)
        if os.path.exists(dest):
            continue
        try:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(data)
            log.info(f"strategy_kb fetched: {f}")
        except Exception as e:
            log.error(f"strategy_kb fetch {f}: {e}")


# ── Продавец: закрытие сделок (воронка лид → согласовано → счёт → оплачено) ────
SALES_PROMPT = """Ты — «Продавец», закрывающий сделки для художника-фрилансера Вячеслава (Slavik), бренд FARBAHOLIX: граффити/мурал Künstler в Германии, украинец на §24, Kleinunternehmer §19 (оборот у порога), есть долги и регулярные платежи. Твоя цель — превращать интерес в ОПЛАЧЕННЫЕ заказы и закрывать кассовые разрывы.

ТВОЯ БАЗА ЗНАНИЙ: карта роли и правила (SKILL.md) уже вшита в конец этого промпта — НЕ читай её через Read. Read'ом читай ТОЛЬКО при реальной необходимости: {kb}/references/product.md (что умеет приложение), {strategy_kb}/references/marketing.md (верх воронки), {legal_kb} (механика счетов/налогов; финал — Steuerberater).

ГЛАВНОЕ: работай ИЗ ДАННЫХ. Тебе дана воронка сделок (проекты со стадиями лид/согласовано/счёт/оплачено, ожидаемые суммы и даты), финансы (баланс, долги, регулярные платежи), таблица инвойсов (оборот, клиенты, средний чек) и планы владельца. Считай взвешенный прогноз (лид ×0.5, согласовано ×0.8, счёт ×0.95), сравнивай с потребностями ближайших 30/60 дней, называй КОНКРЕТНО: какой проект, до какой даты и на какую сумму дожать, чтобы не было разрыва. Не выдумывай цифры; чего не хватает — скажи, что домерить. Письма клиентам — по-немецки (если не просили иначе), коротко, с чётким следующим шагом.

Жёсткие правила: не заменяй Юриста/Steuerberater; не демпингуй; предоплата — нормальная часть переговоров; с пользователем — по-русски.

Сегодня: {today}.

Ответь строго в JSON: {"reply": "весь текст (можно с заголовками, списками, текстами писем)", "actions": []}. actions по желанию (remind/contact). Никакого текста вне JSON."""


def get_funnel_context() -> str:
    """Воронка сделок из проектов дашборда: стадия, ожидаемая сумма, дата оплаты.
    Рабочая доска Продавца — что дожимать, чтобы закрыть кассовый разрыв."""
    stage_label = {"lead": "🔵 лид", "agreed": "🟡 согласовано",
                   "invoiced": "🟠 счёт выставлен", "paid": "✅ оплачено"}
    stage_w = {"lead": 0.5, "agreed": 0.8, "invoiced": 0.95}
    try:
        with db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
            if "expected_income" not in cols:
                return ""
            rows = conn.execute(
                "SELECT name, area, expected_income, income_date, income_status FROM projects "
                "WHERE COALESCE(expected_income,0)>0 AND COALESCE(income_status,'lead')!='paid' "
                "ORDER BY CASE COALESCE(income_status,'lead') WHEN 'invoiced' THEN 0 "
                "WHEN 'agreed' THEN 1 ELSE 2 END, expected_income DESC").fetchall()
    except Exception as e:
        log.error(f"get_funnel_context: {e}")
        return ""
    if not rows:
        return ""
    total = sum(r["expected_income"] or 0 for r in rows)
    weighted = sum((r["expected_income"] or 0) * stage_w.get(r["income_status"] or "lead", 0.5) for r in rows)
    lines = ["ВОРОНКА СДЕЛОК (открытые, отсортированы «ближе к деньгам» сверху):"]
    for r in rows:
        st = stage_label.get(r["income_status"] or "lead", r["income_status"] or "лид")
        lines.append(f"  • {r['name']} [{r['area']}] — {r['expected_income']:.0f}€ · {st}"
                     + (f" · оплата ~{r['income_date']}" if r["income_date"] else ""))
    lines.append(f"Итого ожидаемо: {total:.0f}€ · взвешенно (лид×0.5/согл×0.8/счёт×0.95): {weighted:.0f}€")
    return "\n".join(lines)


def get_leads_context() -> str:
    """Доска лидов бизнес-пульта (dashboard_biz.py): стадии, касания, просрочки."""
    st = {"new": "📥 новый", "contacted": "📞 контакт",
          "qualified": "✅ квалифицирован", "offer": "📄 оферта"}
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT name, channel, budget_est, stage, next_action, next_action_date, touches "
                "FROM leads WHERE stage IN ('new','contacted','qualified','offer') "
                "ORDER BY CASE WHEN next_action_date IS NULL THEN 1 ELSE 0 END, "
                "next_action_date").fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = ["ДОСКА ЛИДОВ (до воронки денег; правило: у живого лида всегда следующее касание):"]
    for r in rows:
        over = " ⚠ПРОСРОЧЕНО" if r["next_action_date"] and r["next_action_date"] < today else ""
        na = (f" · след: {r['next_action']} до {r['next_action_date']}{over}"
              if r["next_action"] else " · ⚠нет следующего шага")
        b = f" · ~{r['budget_est']:.0f}€" if r["budget_est"] else ""
        lines.append(f"  • {r['name']} [{st.get(r['stage'], r['stage'])}]{b}"
                     f" · касаний {r['touches'] or 0}{na}")
    return "\n".join(lines)


def sales_agent_sync(user_text: str = "") -> str:
    """Продавец: разбор воронки и дожатие сделок до оплаты по реальной картине
    (воронка + лиды + финансы + таблица инвойсов + планы владельца)."""
    sys_prompt = (SALES_PROMPT
                  .replace("{kb}", SALES_KB_DIR)
                  .replace("{strategy_kb}", STRATEGY_KB_DIR)
                  .replace("{legal_kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    funnel = get_funnel_context()
    leads = get_leads_context()
    plans = get_plans_context()
    ask = user_text.strip() or (
        "разбери воронку: что дожимать в первую очередь и до каких дат, чтобы прогноз "
        "потока стал зелёным; по каждой сделке — конкретный следующий шаг (и текст письма, где уместно)")
    prompt = (
        f"{get_legal_context()}\n\n"
        + (funnel + "\n\n" if funnel else "")
        + (leads + "\n\n" if leads else "")
        + (plans + "\n\n" if plans else "")
        + "ЗАПРОС К ПРОДАВЦУ: " + ask + "\n"
        "Правила роли уже в системном промпте; отвечай по данным выше."
    )
    skill = _kb_inline(os.path.join(SALES_KB_DIR, "SKILL.md"))
    if skill:
        sys_prompt += "\n\n=== SKILL.md (уже прочитан, Read не нужен) ===\n" + skill
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch", "--model", "sonnet", "--max-turns", "8"], timeout=360)
        raw = (result.stdout or "").strip()
        if not raw or raw.startswith("Error:"):
            log.error(f"Sales CLI пусто/ошибка: rc={result.returncode} "
                      f"out={raw[:200]!r} err={(result.stderr or '')[:300]!r}")
        s, e = raw.find("{"), raw.rfind("}")
        reply = ""
        if s >= 0 and e > s:
            try:
                reply = (jsonlib.loads(raw[s:e + 1]) or {}).get("reply", "")
            except Exception:
                reply = ""
        if not reply:
            reply = raw
        if reply:
            _settings_set("sales_summary", reply[:6000])
        return reply
    except Exception as e:
        log.error(f"sales_agent: {e}")
        return ""


def ensure_sales_kb():
    """Самолечение: подтянуть sales_kb с ветки, если файлов нет на диске."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    need = [x for x in UPDATE_FILES if x.startswith("sales_kb/")]
    for f in need:
        dest = os.path.join(d, f)
        if os.path.exists(dest):
            continue
        try:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(data)
            log.info(f"sales_kb fetched: {f}")
        except Exception as e:
            log.error(f"sales_kb fetch {f}: {e}")


INVOICES_SEED_VERSION = "1"


def ensure_invoices_seed():
    """Однократно залить исторические счета из invoices_seed.json в архив аналитики
    (invoice_archive). Идемпотентно: флаг версии + дедуп по (number, inv_date).
    Файл: [{number, date(YYYY-MM-DD или ДД.ММ.ГГГГ), recipient, customer_no,
    description, total, net?, vat?, kleinunternehmer?}]. Секретов там нет."""
    d = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(d, "invoices_seed.json")
    if not os.path.exists(path):
        return
    if _settings_get("invoices_seed_v") == INVOICES_SEED_VERSION:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = jsonlib.load(f)
    except Exception as e:
        log.error(f"invoices_seed load: {e}")
        return

    def _iso(dt):
        s = (dt or "").strip()
        m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return s

    n = 0
    try:
        with db() as conn:
            for r in rows:
                inv_date = _iso(r.get("date"))
                year = _year_of_iso(inv_date)
                total = float(r.get("total") or 0)
                net = float(r.get("net") if r.get("net") is not None else total)
                vat = float(r.get("vat") or 0)
                gross = float(r.get("gross") or total or (net + vat))
                klein = 1 if r.get("kleinunternehmer", True) else 0
                client = (r.get("recipient") or "").split(chr(10))[0].strip()
                cur = conn.execute(
                    "INSERT OR IGNORE INTO invoice_archive "
                    "(number, inv_date, year, client_name, items, net, vat, gross, kleinunternehmer, raw_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ((r.get("number") or "").strip(), inv_date, year, client, "[]",
                     net, vat, gross, klein, jsonlib.dumps(r, ensure_ascii=False)))
                n += cur.rowcount
    except Exception as e:
        log.error(f"invoices_seed insert: {e}")
        return
    _settings_set("invoices_seed_v", INVOICES_SEED_VERSION)
    log.info(f"invoices_seed: залито {n} счетов в архив")


def apply_actions(actions: list) -> list:
    results = []
    for a in actions:
        try:
            if a.get("type") == "save":
                area = a.get("area") if a.get("area") in AREAS else detect_area(a.get("text", ""))

                def _clamp(v):
                    try:
                        return max(0, min(10, int(v)))
                    except (ValueError, TypeError):
                        return 0
                imp = _clamp(a.get("importance", 0))
                urg = _clamp(a.get("urgency", 0))
                if imp or urg:
                    pri = "high" if (imp >= 6 and urg >= 6) else ("low" if (imp < 6 and urg < 6) else "mid")
                else:
                    pri = a.get("priority") if a.get("priority") in ("high", "mid", "low") else "mid"
                item_id = save_item(a["text"], area, pri, imp, urg)
                results.append(("save", item_id, a["text"], area, pri))
            elif a.get("type") == "done":
                with db() as conn:
                    row = conn.execute("SELECT text FROM chaos WHERE id=?", (a["id"],)).fetchone()
                    conn.execute("UPDATE chaos SET done=1 WHERE id=?", (a["id"],))
                if row:
                    results.append(("done", a["id"], row["text"], "", ""))
            elif a.get("type") == "finance":
                amount = float(a["amount"])
                comment = a.get("comment", "")
                account = a.get("account") if a.get("account") in ("cash", "card") else "card"
                with db() as conn:
                    conn.execute("INSERT INTO finance (amount, comment, account) VALUES (?,?,?)",
                                 (amount, comment, account))
                    total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
                acc_ru = "наличные" if account == "cash" else "карта"
                results.append(("finance", 0, f"{amount:+.0f}€ {comment} ({acc_ru}) · всего {total:+.2f}€", "", ""))
            elif a.get("type") == "remind":
                with db() as conn:
                    conn.execute("INSERT INTO reminders (due_at, text) VALUES (?,?)",
                                 (a["when"], a["text"]))
                results.append(("remind", 0, f"{a['when']} — {a['text']}", "", ""))
            elif a.get("type") == "contact":
                with db() as conn:
                    conn.execute("INSERT INTO contacts (name, note) VALUES (?,?)",
                                 (a["name"], a["note"]))
                results.append(("contact", 0, f"{a['name']}: {a['note']}", "", ""))
            elif a.get("type") == "invoice":
                from invoice import generate_invoice
                recipient = a.get("recipient", "")
                items = a.get("items", [])
                salutation = a.get("salutation")
                customer_no = a.get("customer_no", "")
                # Клиент назван коротко (без адреса) — подтянуть полные данные из памяти
                if recipient and "\n" not in recipient.strip():
                    c = find_client(recipient)
                    if c:
                        recipient = c["recipient_full"]
                        salutation = salutation or c["salutation"]
                        customer_no = customer_no or c["customer_no"] or ""
                if recipient and items:
                    path, total, number = generate_invoice(
                        recipient=recipient, items=items,
                        salutation=salutation,
                        customer_no=customer_no,
                        number=next_invoice_number(),
                        intro=a.get("intro") or None,
                        vat_rate=a.get("vat_rate") or None,
                    )
                    desc = "; ".join(it.get("desc", "") for it in items)
                    register_own_invoice(number, recipient, customer_no, desc, total,
                                         path, a.get("vat_rate"))
                    upsert_client(recipient, salutation or "", customer_no)  # запомнить клиента целиком
                    results.append(("invoice", 0, f"Rechnung {number} · {total:.2f}€", path, ""))
            elif a.get("type") == "case":
                upsert_bureau_case(a.get("topic"), a.get("title"), a.get("status"),
                                   a.get("next_step"), a.get("due"), a.get("note"))
                results.append(("case", 0, f"{a.get('topic')}: {a.get('status') or 'обновлено'}"
                                + (f" → {a.get('next_step')}" if a.get("next_step") else ""), "", ""))
            elif a.get("type") == "project":
                area = a.get("area") if a.get("area") in AREAS else "work"
                with db() as conn:
                    exists = conn.execute("SELECT id FROM projects WHERE LOWER(name)=LOWER(?)",
                                          (a["name"],)).fetchone()
                    if not exists:
                        cur = conn.execute("INSERT INTO projects (name, area) VALUES (?,?)",
                                           (a["name"], area))
                        pid = cur.lastrowid
                        for s in a.get("steps", []):
                            conn.execute("INSERT INTO steps (project_id, text) VALUES (?,?)", (pid, s))
                        results.append(("project", pid,
                                        f"{a['name']} · {len(a.get('steps', []))} шагов", area, ""))
            elif a.get("type") == "progress":
                pid = int(a["project_id"])
                count = int(a.get("count", 1))
                with db() as conn:
                    proj = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
                    steps = conn.execute(
                        "SELECT id FROM steps WHERE project_id=? AND done=0 ORDER BY id LIMIT ?",
                        (pid, count)).fetchall()
                    for s in steps:
                        conn.execute("UPDATE steps SET done=1 WHERE id=?", (s["id"],))
                    stats = conn.execute(
                        "SELECT COUNT(*) total, COALESCE(SUM(done),0) done FROM steps WHERE project_id=?",
                        (pid,)).fetchone()
                if proj and steps:
                    pct = int(stats["done"] / stats["total"] * 100) if stats["total"] else 0
                    results.append(("progress", pid, f"{proj['name']}: {pct}% ({stats['done']}/{stats['total']})", "", ""))
            elif a.get("type") == "stage":
                # Сдвиг сделки по воронке («согласовано», «счёт выставлен», «оплата пришла»).
                # Приход денег при "paid" НЕ проводится автоматически — его даёт отдельный
                # action finance (иначе возможен двойной учёт с дашбордом).
                pid = int(a["project_id"])
                stage = a.get("stage")
                if stage in ("lead", "agreed", "invoiced", "paid"):
                    with db() as conn:
                        proj = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
                        if proj:
                            conn.execute("UPDATE projects SET income_status=? WHERE id=?", (stage, pid))
                    if proj:
                        lbl = {"lead": "🔵 лид", "agreed": "🟡 согласовано",
                               "invoiced": "🟠 счёт выставлен", "paid": "✅ оплачено"}[stage]
                        results.append(("stage", pid, f"{proj['name']} → {lbl}", "", ""))
            elif a.get("type") == "unremind":
                # Снять напоминание, потерявшее смысл («оплата пришла» → не напоминать
                # «проверь оплату»): помечаем sent=1 — оно больше не сработает.
                rid = int(a["id"])
                with db() as conn:
                    rem = conn.execute("SELECT text FROM reminders WHERE id=? AND sent=0", (rid,)).fetchone()
                    if rem:
                        conn.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
                if rem:
                    results.append(("unremind", rid, f"снято напоминание: {rem['text']}", "", ""))
        except Exception as e:
            log.error(f"action error: {e}")
    return results


def remember(role: str, text: str):
    with db() as conn:
        conn.execute("INSERT INTO messages (role, text) VALUES (?,?)", (role, text))
        conn.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 50)")


# ── Долгая память Юриста ──────────────────────────────────────────────────────
# Дословно в контекст идут последние LAWYER_WINDOW реплик; всё, что выходит за
# окно, сжимается в постоянную сводку (settings['lawyer_summary']). Так Юрист
# помнит практически весь диалог, не раздувая каждый запрос.
LAWYER_WINDOW = 30          # сколько последних реплик показывать дословно
LAWYER_MSG_MAXLEN = 1600    # макс. длина одной реплики в контексте
LAWYER_STORE_CAP = 2000     # жёсткий потолок строк в lawyer_messages (старое уже в сводке)


def remember_lawyer(role: str, text: str):
    """Сохранить полную реплику диалога с Юристом в его отдельную долгую память."""
    try:
        with db() as conn:
            conn.execute("INSERT INTO lawyer_messages (role, text) VALUES (?,?)", (role, text))
            conn.execute("DELETE FROM lawyer_messages WHERE id NOT IN "
                         "(SELECT id FROM lawyer_messages ORDER BY id DESC LIMIT ?)", (LAWYER_STORE_CAP,))
    except Exception as e:
        log.error(f"remember_lawyer: {e}")


def get_lawyer_memory():
    """(сводка, [последние реплики]) — постоянная память Юриста для контекста."""
    summary = _settings_get("lawyer_summary") or ""
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT id, role, text FROM lawyer_messages ORDER BY id DESC LIMIT ?",
                (LAWYER_WINDOW,)).fetchall()
        recent = list(reversed(rows))
    except Exception as e:
        log.error(f"get_lawyer_memory: {e}")
        recent = []
    return summary, recent


def maybe_update_lawyer_summary():
    """Свернуть в сводку реплики, выпавшие за окно последних LAWYER_WINDOW.
    Вызывать ПОСЛЕ отправки ответа (в executor) — не задерживает ответ Юриста."""
    try:
        with db() as conn:
            newest = conn.execute("SELECT COALESCE(MAX(id),0) FROM lawyer_messages").fetchone()[0]
            if not newest:
                return
            # граница окна: всё с id <= cutoff уже вышло из дословного окна
            cutoff = conn.execute(
                "SELECT MIN(id) FROM (SELECT id FROM lawyer_messages ORDER BY id DESC LIMIT ?)",
                (LAWYER_WINDOW,)).fetchone()[0]
            upto = int(_settings_get("lawyer_summary_upto_id") or 0)
            if cutoff is None or cutoff - 1 <= upto:
                return  # нечего досворачивать
            pending = conn.execute(
                "SELECT role, text FROM lawyer_messages WHERE id > ? AND id < ? ORDER BY id",
                (upto, cutoff)).fetchall()
        if not pending:
            return
        prev = _settings_get("lawyer_summary") or "(пусто)"
        block = "\n".join(
            f"{'Человек' if r['role'] == 'user' else 'Юрист'}: {r['text']}" for r in pending)
        prompt = (
            "Ты ведёшь долгую память налогово-правового консультанта (Юриста) для одного клиента.\n"
            "Обнови сводку памяти: аккуратно впиши в неё новые обмены, сохранив ВСЕ факты, "
            "решения, статусы, суммы, сроки, обязательства и договорённости. Убирай воду, "
            "не выдумывай, не теряй важное. Пиши по-русски, компактно, тезисами.\n\n"
            f"ТЕКУЩАЯ СВОДКА:\n{prev}\n\nНОВЫЕ ОБМЕНЫ:\n{block}\n\n"
            "Верни ТОЛЬКО обновлённый текст сводки, без пояснений.")
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--tools", ""], timeout=90)
        new_summary = (result.stdout or "").strip()
        if new_summary and not new_summary.startswith("Error:"):
            _settings_set("lawyer_summary", new_summary[:8000])
            _settings_set("lawyer_summary_upto_id", str(cutoff - 1))
            log.info(f"lawyer summary updated up to id {cutoff - 1}")
    except Exception as e:
        log.error(f"maybe_update_lawyer_summary: {e}")


async def ai_converse(update: Update, user_text: str, source: str = "text"):
    save_chat_id(update.effective_chat.id)
    remember("user", user_text)

    resp = await asyncio.get_event_loop().run_in_executor(None, lambda: ask_claude_sync(user_text))

    reply = resp.get("reply", "")
    actions = resp.get("actions", [])
    applied = apply_actions(actions)

    if not reply:
        # Фоллбэк: старый механизм
        await save_and_reply(update, user_text, source=source)
        return

    remember("assistant", reply)

    prefix = f"🎤 _{user_text}_\n\n" if source == "voice" else ""

    extras = []
    for kind, item_id, text, area, pri in applied:
        if kind == "save":
            extras.append(f"📌 {area_emoji(area)} _{text}_")
        elif kind == "done":
            extras.append(f"✅ закрыто: _{text}_")
        elif kind == "finance":
            extras.append(f"💰 _{text}_")
        elif kind == "remind":
            extras.append(f"⏰ _{text}_")
        elif kind == "contact":
            extras.append(f"👤 _{text}_")
        elif kind == "project":
            extras.append(f"🎯 новый проект: _{text}_ — смотри прогресс на дашборде")
        elif kind == "progress":
            extras.append(f"📊 _{text}_")
        elif kind == "invoice":
            extras.append(f"🧾 _{text}_ — PDF ниже")

    msg = prefix + reply
    if extras:
        msg += "\n\n" + "\n".join(extras)

    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(prefix.replace("_", "") + reply)

    # отвечаем голосом, если обратились голосом и озвучка включена
    if source == "voice" and voice_enabled():
        await speak_reply(update, reply)

    for kind, _id, _text, path, _pri in applied:
        if kind == "invoice" and path:
            try:
                with open(path, "rb") as doc:
                    await update.message.reply_document(doc, filename=path.split("/")[-1])
            except Exception as e:
                log.error(f"send invoice: {e}")


# ─── Главный обработчик текста ────────────────────────────────────────────────

async def show_invoice_archive(update: Update):
    with db() as conn:
        rows = conn.execute(
            "SELECT number, date, recipient, total, COALESCE(date,created_at) AS d "
            "FROM invoices ORDER BY d DESC, id DESC"
        ).fetchall()
    if not rows:
        await update.message.reply_text(
            "🧾 Архив инвойсов пуст.\n\nВыстави счёт через бота или пришли старые — занесу в архив.")
        return

    def year_of(r):
        d = r["date"] or ""
        # формат dd.mm.yyyy или ISO
        if "." in d:
            return d.split(".")[-1][:4]
        return (d or "")[:4] or "—"

    years = {}
    grand = 0.0
    for r in rows:
        y = year_of(r)
        years.setdefault(y, []).append(r)
        grand += (r["total"] or 0)

    lines = [f"🧾 *Архив инвойсов* — всего {len(rows)} на {grand:,.0f}€\n".replace(",", " ")]
    for y in sorted(years.keys(), reverse=True):
        ys = years[y]
        ysum = sum(x["total"] or 0 for x in ys)
        lines.append(f"*{y}* — {len(ys)} шт · {ysum:,.0f}€".replace(",", " "))
        for r in ys[:30]:
            rec = (r["recipient"] or "").split(chr(10))[0][:28]
            lines.append(f"  `{r['number'] or '—'}` {r['date'] or ''} · {rec} · {r['total'] or 0:.0f}€")
        if len(ys) > 30:
            lines.append(f"  …ещё {len(ys)-30}")
        lines.append("")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3950] + "\n…"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def _ensure_kbd_cleared(update: Update):
    """Разово снимает залипшую reply-клавиатуру (Хаос / Архив инвойсов) у владельца.
    Инлайн-кнопки подтверждения не могут нести ReplyKeyboardRemove в том же
    сообщении, поэтому один раз шлём отдельное тихое сообщение и ставим флаг."""
    if _settings_get("kbd_cleared"):
        return
    try:
        await update.message.reply_text("🗂 Обновил меню.", reply_markup=ReplyKeyboardRemove())
        _settings_set("kbd_cleared", "1")
    except Exception:
        pass


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return
    await _ensure_kbd_cleared(update)

    if text == "📋 Хаос":
        await show_list(update, area_filter="open")
        return

    if text == "🧾 Архив инвойсов":
        await show_invoice_archive(update)
        return

    # Остатки старой клавиатуры Юриста: гасим залипшие кнопки и возвращаем обычное меню
    if text in ("⚖️ Юрист", "⬅️ Выход из Юриста", "⬅️ Выход"):
        await update.message.reply_text(
            "Юрист теперь — отдельный бот, пиши ему напрямую (⚖️ @Farbaholix_jurist).\n"
            "Здесь я обычный секретарь 🗂",
            reply_markup=MAIN_KBD)
        return

    # Проверяем не ждём ли мы ввода от пользователя
    state = ctx.user_data.get("state")

    if state == "bridge_done":
        ctx.user_data["bridge_done"] = text
        ctx.user_data["state"] = "bridge_missed"
        await update.message.reply_text("Хорошо. Что *не* удалось сделать — и почему?\n_Напиши «—» если всё ок_", parse_mode="Markdown")
        return

    if state == "bridge_missed":
        ctx.user_data["bridge_missed"] = text
        ctx.user_data["state"] = "bridge_insight"
        await update.message.reply_text("Понятно. Какой главный вывод из этого периода?", parse_mode="Markdown")
        return

    if state == "bridge_insight":
        ctx.user_data["bridge_insight"] = text
        ctx.user_data["state"] = "bridge_next"
        await update.message.reply_text("Отлично! И последнее — *что главное на следующий период?*", parse_mode="Markdown")
        return

    if state == "bridge_next":
        d = ctx.user_data
        with db() as conn:
            conn.execute(
                "INSERT INTO bridge (period, done_text, missed_text, insight_text, next_text) VALUES (?,?,?,?,?)",
                (d.get("bridge_period", "day"), d.get("bridge_done", ""),
                 d.get("bridge_missed", ""), d.get("bridge_insight", ""), text)
            )
        period_ru = {"day": "день", "week": "неделю", "month": "месяц"}.get(d.get("bridge_period"), "период")
        ctx.user_data.clear()
        await update.message.reply_text(
            f"⚓ Разбор за {period_ru} сохранён. Хорошая работа!\n\n"
            f"Впереди: _{text}_",
            parse_mode="Markdown"
        )
        return

    if state == "proj_name":
        ctx.user_data["proj_name"] = text
        ctx.user_data["state"] = None
        area = detect_area(text)
        with db() as conn:
            cur = conn.execute("INSERT INTO projects (name, area) VALUES (?,?)", (text, area))
            proj_id = cur.lastrowid
        await update.message.reply_text(
            f"📁 Проект создан: *{text}*\n\n"
            f"Добавляй шаги — просто пиши «шаг: текст» или /proj_{proj_id}",
            parse_mode="Markdown"
        )
        return

    # Быстрое закрытие по паттерну "готово N" или "✅ N"
    match = re.match(r'^(готово|done|✅|закрыл|сделал)\s+(\d+)$', text.lower())
    if match:
        item_id = int(match.group(2))
        with db() as conn:
            row = conn.execute("SELECT text FROM chaos WHERE id=?", (item_id,)).fetchone()
            conn.execute("UPDATE chaos SET done=1 WHERE id=?", (item_id,))
        if row:
            await update.message.reply_text(f"✅ Закрыла: _{row['text']}_\n\nМолодец! 💪", parse_mode="Markdown")
        return

    # Быстрое добавление шага "шаг: текст"
    if text.lower().startswith("шаг:") or text.lower().startswith("шаг "):
        step_text = text[4:].strip() if text.lower().startswith("шаг:") else text[4:].strip()
        with db() as conn:
            projs = conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 1").fetchone()
        if projs:
            with db() as conn:
                conn.execute("INSERT INTO steps (project_id, text) VALUES (?,?)", (projs["id"], step_text))
            await update.message.reply_text(
                f"📌 Шаг добавлен в *{projs['name']}*: _{step_text}_",
                parse_mode="Markdown"
            )
            return

    # «в хаос [текст]» или «[текст] в хаос» — мгновенно в Парковку без вопросов
    chaos_match = re.match(r'^в\s+хаос[:\s]+(.+)$', text, re.IGNORECASE | re.DOTALL) \
               or re.match(r'^(.+?)\s+в\s+хаос$', text, re.IGNORECASE | re.DOTALL)
    if chaos_match:
        task = chaos_match.group(1).strip()
        with db() as conn:
            min_pos = conn.execute(
                "SELECT COALESCE(MIN(position), 1) FROM chaos WHERE done=0"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO chaos (text, area, priority, importance, urgency, position) VALUES (?,?,?,?,?,?)",
                (task, "other", "mid", 0, 0, min_pos - 1)
            )
        await update.message.reply_text(f"📌 Припарковано: _{task}_", parse_mode="Markdown")
        return

    # «новая цель [текст]» — мгновенно создаёт проект с декомпозицией без лишних вопросов
    new_goal_match = re.match(r'^новая\s+цель[:\s—-]+(.+)$', text, re.IGNORECASE | re.DOTALL) \
                  or re.match(r'^новая\s+цель\s+(.+)$', text, re.IGNORECASE | re.DOTALL)
    if new_goal_match:
        await create_goal_project(update, new_goal_match.group(1).strip())
        return

    # Явное добавление цели: «добавь цель ...» / «цель: ...»
    goal_match = re.match(r'^(?:добавь\s+)?цель[:\s—-]+(.+)$', text, re.IGNORECASE | re.DOTALL)
    if goal_match:
        await create_goal_project(update, goal_match.group(1).strip())
        return

    # Явный счёт: «выстави счёт …», «сделай инвойс …», «Rechnung …»
    if looks_like_invoice_request(text):
        await create_invoice_from_text(update, text)
        return

    if state == "img_event_date":
        plan = ctx.user_data.get("pending_plan") or {}
        title = plan.get("title", "Событие")
        time_str = plan.get("time") or ""
        # Разбираем дату из свободного текста через Claude
        def parse_date_sync(raw: str) -> str:
            today = datetime.now().strftime("%Y-%m-%d")
            prompt = (
                f"Сегодня {today}. Человек написал дату: «{raw}». "
                "Верни её в формате YYYY-MM-DD одной строкой без пояснений. "
                "Если не понять — верни пустую строку."
            )
            try:
                r = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--tools", ""], timeout=30)
                out = r.stdout.strip()
                m = re.search(r'\d{4}-\d{2}-\d{2}', out)
                return m.group() if m else ""
            except Exception:
                return ""
        date_str = await asyncio.get_event_loop().run_in_executor(None, lambda: parse_date_sync(text))
        if date_str:
            save_event(title, date_str, time_str)
            months_ru = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
            try:
                from datetime import datetime as _dt
                d = _dt.strptime(date_str, "%Y-%m-%d")
                date_nice = f"{d.day} {months_ru[d.month-1]}"
            except Exception:
                date_nice = date_str
            ctx.user_data.pop("pending_plan", None)
            ctx.user_data["state"] = None
            await update.message.reply_text(
                f"📅 Добавлено в календарь: *{title}*\n{date_nice}{' · ' + time_str if time_str else ''}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "Не понял дату. Напиши, например: «15 марта», «2026-07-10» или «следующая пятница»."
            )
        return

    # Всё остальное — живой разговор через Claude
    await ai_converse(update, text)


def looks_like_invoice_request(text: str) -> bool:
    """Просьба ВЫСТАВИТЬ счёт (не вопрос про счета) — тогда идём детерминированным путём."""
    t = text or ""
    return bool(
        re.search(r"(выстав|сдела|выпиш|оформ|подготов|сгенер|создай|сформир)\w*\s+.{0,15}(сч[ёе]т|инвойс|invoice|rechnung)",
                  t, re.IGNORECASE)
        or re.search(r"(сч[ёе]т|инвойс|invoice|rechnung)\b.{0,40}(на |для )", t, re.IGNORECASE)
    )


def looks_like_contract_request(text: str) -> bool:
    """Просьба СОСТАВИТЬ договор (не вопрос про договоры)."""
    t = text or ""
    return bool(
        re.search(r"(состав|сдела|подготов|сгенер|создай|сформир|напиши|оформ)\w*\s+.{0,15}(договор|контракт|vertrag|werkvertrag)",
                  t, re.IGNORECASE)
        or re.search(r"(договор|контракт|vertrag)\b.{0,40}(с |на |для |между)", t, re.IGNORECASE)
    )


async def create_invoice_from_text(update: Update, text: str):
    await update.message.reply_text("🧾 Готовлю счёт...")

    known = clients_for_context()
    known_block = ("\n\n" + known + "\nЕсли получатель назван коротко и он есть в этом списке — "
                   "верни его ПОЛНЫЙ recipient (с адресом) и salutation оттуда дословно.") if known else ""

    def extract():
        prompt = (
            "Из сообщения извлеки данные для немецкого счёта (Rechnung). Сообщение: «" + text + "».\n"
            "Описание работы сформулируй НА НЕМЕЦКОМ профессионально, с умляутами ä ö ü ß "
            "(напр. «Künstlerische Gestaltung der Fassade»).\n"
            "Ответь строго JSON без иного текста: {\"recipient\": \"получатель: название и адрес, "
            "каждая часть с новой строки \\n\", \"items\": [{\"desc\": \"работа по-немецки\", "
            "\"price\": 1200}], \"salutation\": \"Frau Müller или Herr Schmidt если известно, иначе пусто\", "
            "\"customer_no\": \"\", \"intro\": \"вводная фраза счёта по-немецки, если из сообщения ясен "
            "повод/проект (напр. Hiermit berechne ich Ihnen wie vorab besprochen für ... folgende "
            "Vorauszahlung:), иначе пусто\"}. Если сумма не названа — верни {\"need\": \"чего не хватает\"}."
            + known_block
        )
        try:
            result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--tools", ""], timeout=120)
            raw = result.stdout.strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s >= 0 and e > s:
                return jsonlib.loads(raw[s:e+1])
        except Exception as ex:
            log.error(f"invoice extract: {ex}")
        return None

    data = await asyncio.get_event_loop().run_in_executor(None, extract)

    recipient = (data or {}).get("recipient", "") or ""
    salutation = (data or {}).get("salutation") or ""
    customer_no = (data or {}).get("customer_no", "") or ""
    # Клиент назван коротко/без адреса — подтянуть полные данные из памяти клиентов
    if recipient and "\n" not in recipient.strip():
        c = find_client(recipient)
        if c:
            recipient = c["recipient_full"]
            salutation = salutation or c["salutation"]
            customer_no = customer_no or c["customer_no"] or ""

    if not data or data.get("need") or not recipient or not data.get("items"):
        miss = (data or {}).get("need", "получателя (название, адрес) и сумму")
        await update.message.reply_text(
            f"Чтобы выставить счёт, не хватает: {miss}.\nНапиши, например: "
            "_«счёт Galerie Hertz, Bahnhofstraße 12, 60311 Frankfurt, роспись фасада 1200€»_",
            parse_mode="Markdown")
        return

    from invoice import generate_invoice
    try:
        path, total, number = generate_invoice(
            recipient=recipient, items=data["items"],
            salutation=salutation or None,
            customer_no=customer_no,
            number=next_invoice_number(),
            intro=data.get("intro") or None,
        )
    except Exception as ex:
        log.error(f"invoice gen: {ex}")
        await update.message.reply_text(
            "Не получилось собрать PDF 😔\n"
            f"Причина: `{str(ex)[:250]}`", parse_mode="Markdown")
        return

    desc = "; ".join(it.get("desc", "") for it in data["items"])
    register_own_invoice(number, recipient, customer_no, desc, total, path,
                         data.get("vat_rate"))
    upsert_client(recipient, salutation, customer_no)  # запомнить клиента целиком

    remember("user", "счёт: " + text)
    remember("assistant", f"выставлен счёт Rechnung {number} на {total:.2f}€")

    await update.message.reply_text(
        f"🧾 Готово! *Rechnung {number}* на *{total:.2f}€*\nПолучатель: {recipient.split(chr(10))[0]}",
        parse_mode="Markdown")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename=path.split("/")[-1])
    except Exception as ex:
        log.error(f"invoice send: {ex}")


async def create_contract_from_text(update: Update, text: str):
    """Составить договор из описания (текст/голос) и выдать PDF в дизайне инвойса.
    Учитывает контекст (Kleinunternehmer §19, §24) и нюансы прошлых договоров."""
    await update.message.reply_text("📄 Готовлю договор…")

    known = clients_for_context()
    past = contracts_context()

    def draft():
        prompt = (
            "Составь профессиональный НЕМЕЦКИЙ договор (Werkvertrag/Künstlervertrag) для художника-"
            "фрилансера Viacheslav Balabaiev (бренд FARBAHOLIX, Graffiti/Mural Künstler, Kleinunternehmer "
            "§19 UStG — без НДС, §24 в Германии) с заказчиком, по описанию ниже.\n"
            "ОПИСАНИЕ ПРОЕКТА: «" + text + "»\n"
            + (("\n" + known) if known else "")
            + (("\n" + past) if past else "")
            + "\nУчитывай нюансы прошлых договоров (типичные условия оплаты, права на изображения/"
            "Urheberrecht, ответственность, расторжение). Формулировки — юридически аккуратные, "
            "по-немецки. Разделы: Vertragsgegenstand, Leistungsbeschreibung, Vergütung (укажи сумму; "
            "оговорка Kleinunternehmer §19), Zahlungsbedingungen, Termine, Nutzungsrechte/Urheberrecht, "
            "Haftung/Gewährleistung, Kündigung, Schlussbestimmungen (по релевантности).\n"
            "Ответь СТРОГО JSON без иного текста: {\"client_recipient\": \"заказчик: название и адрес, "
            "каждая часть с новой строки \\n\", \"title\": \"напр. Werkvertrag — Wandgestaltung\", "
            "\"intro\": \"Präambel одной-двумя фразами\", \"sections\": [{\"heading\": \"Vertragsgegenstand\", "
            "\"body\": \"текст раздела на немецком\"}, ...], \"place\": \"город подписания если известен\"}. "
            "Если не хватает заказчика или сути работы или суммы — верни {\"need\": \"чего не хватает\"}."
        )
        try:
            result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "sonnet", "--tools", ""], timeout=180)
            raw = result.stdout.strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s >= 0 and e > s:
                return jsonlib.loads(raw[s:e + 1])
        except Exception as ex:
            log.error(f"contract draft: {ex}")
        return None

    data = await asyncio.get_event_loop().run_in_executor(None, draft)

    if not data or data.get("need") or not data.get("sections") or not data.get("client_recipient"):
        miss = (data or {}).get("need", "заказчика (название, адрес), суть работы и сумму")
        await update.message.reply_text(
            f"Чтобы составить договор, не хватает: {miss}.\nОпиши (можно голосом), например: "
            "_«договор с Café Sa'Sis, роспись стены 18 м², 2400€, предоплата 50%, август, "
            "права на фото за мной»_", parse_mode="Markdown")
        return

    from invoice import generate_contract
    try:
        path, ref = generate_contract(
            client=data["client_recipient"], title=data.get("title"),
            intro=data.get("intro"), sections=data["sections"], place=data.get("place"))
    except Exception as ex:
        log.error(f"contract gen: {ex}")
        await update.message.reply_text(f"Не получилось собрать PDF договора 😔\nПричина: `{str(ex)[:250]}`",
                                        parse_mode="Markdown")
        return

    client_line = data["client_recipient"].split(chr(10))[0]
    upsert_client(data["client_recipient"], "", "")
    remember("user", "договор: " + text)
    remember("assistant", f"составлен договор для {client_line}")
    await update.message.reply_text(
        f"📄 Готово! Договор для *{client_line}*.\n"
        "_Проверь текст перед подписанием; по налоговым нюансам финал — со Steuerberater._",
        parse_mode="Markdown")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename=path.split("/")[-1])
    except Exception as ex:
        log.error(f"contract send: {ex}")


async def create_goal_project(update: Update, goal_text: str):
    await update.message.reply_text("🎯 Принято! Раскладываю цель на шаги...")

    def decompose():
        prompt = (
            f"Цель человека: «{goal_text}». Он стрит-арт художник (FARBAHOLIX) в Германии.\n"
            "Разбей цель на 4-8 конкретных выполнимых шагов (декомпозиция по Фридману).\n"
            'Ответь строго JSON без другого текста: {"name": "короткое название проекта", '
            '"area": "work|health|money|people|home|self|other", "steps": ["шаг 1", "шаг 2"]}'
        )
        try:
            result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--max-turns", "8", "--tools", ""], timeout=120)
            raw = result.stdout.strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                return jsonlib.loads(raw[start:end+1])
        except Exception as e:
            log.error(f"decompose: {e}")
        return None

    data = await asyncio.get_event_loop().run_in_executor(None, decompose)

    if not data or not data.get("steps"):
        # Создаём проект без шагов, чтобы цель не потерялась
        with db() as conn:
            conn.execute("INSERT INTO projects (name, area) VALUES (?,?)", (goal_text[:80], "work"))
        await update.message.reply_text(
            f"🎯 Цель записана: *{goal_text}*\n"
            "Шаги придумать не получилось — добавь их сам или попроси меня позже.",
            parse_mode="Markdown")
        return

    name = data.get("name", goal_text[:80])
    area = data.get("area") if data.get("area") in AREAS else "work"
    steps = data["steps"]

    with db() as conn:
        exists = conn.execute("SELECT id FROM projects WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
        if exists:
            await update.message.reply_text(f"Проект «{name}» уже есть — смотри на дашборде.")
            return
        cur = conn.execute("INSERT INTO projects (name, area) VALUES (?,?)", (name, area))
        pid = cur.lastrowid
        for s in steps:
            conn.execute("INSERT INTO steps (project_id, text) VALUES (?,?)", (pid, s))

    remember("user", f"цель: {goal_text}")
    remember("assistant", f"создан проект {name} с шагами: {'; '.join(steps)}")

    steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
    await update.message.reply_text(
        f"🎯 *{name}* {area_emoji(area)}\n\nШаги:\n{steps_text}\n\n"
        f"📊 Прогресс-бар уже на дашборде. Говори «продвинулся по {name.lower()}» — буду отмечать.",
        parse_mode="Markdown")


# ─── Голос ────────────────────────────────────────────────────────────────────

async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ensure_kbd_cleared(update)
    await update.message.reply_text("🎤 Слушаю...")
    voice = update.message.voice
    file = await ctx.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    text = await asyncio.get_event_loop().run_in_executor(None, lambda: _transcribe_sync(tmp_path))
    os.unlink(tmp_path)

    if not text:
        await update.message.reply_text("Не смогла разобрать голос 😔 Попробуй написать текстом.")
        return

    # Те же быстрые шорткаты, что и в текстовом handle_text
    chaos_m = re.match(r'^в\s+хаос[:\s]+(.+)$', text, re.IGNORECASE | re.DOTALL) \
           or re.match(r'^(.+?)\s+в\s+хаос$', text, re.IGNORECASE | re.DOTALL)
    if chaos_m:
        task = chaos_m.group(1).strip()
        with db() as conn:
            min_pos = conn.execute(
                "SELECT COALESCE(MIN(position), 1) FROM chaos WHERE done=0"
            ).fetchone()[0]
            conn.execute("INSERT INTO chaos (text, area, priority, importance, urgency, position) VALUES (?,?,?,?,?,?)",
                         (task, "other", "mid", 0, 0, min_pos - 1))
        await update.message.reply_text(f"🎤 _{text}_\n\n📌 Припарковано: _{task}_", parse_mode="Markdown")
        return

    goal_m = re.match(r'^новая\s+цель[:\s—-]+(.+)$', text, re.IGNORECASE | re.DOTALL) \
          or re.match(r'^новая\s+цель\s+(.+)$', text, re.IGNORECASE | re.DOTALL)
    if goal_m:
        await create_goal_project(update, goal_m.group(1).strip())
        return

    await ai_converse(update, text, source="voice")


_whisper_model = None

def _transcribe_sync(path: str) -> str:
    global _whisper_model
    try:
        import imageio_ffmpeg
        import subprocess
        import whisper

        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()

        wav_path = path.replace(".ogg", ".wav")
        subprocess.run(
            [ffmpeg_bin, "-y", "-i", path, "-ar", "16000", "-ac", "1", wav_path],
            check=True, capture_output=True
        )

        if _whisper_model is None:
            _whisper_model = whisper.load_model("small")
        result = _whisper_model.transcribe(wav_path, language="ru")
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        return result["text"].strip()
    except Exception as e:
        log.error(f"Whisper: {e}")
        return ""


# ─── Фото: оценка размеров стены ──────────────────────────────────────────────

WALL_PROMPT = """Прочитай изображение по пути {path} (инструмент Read).
Это фото стены/поверхности для граффити. Оцени её размеры.

Метод: найди на фото объекты с известными размерами и посчитай от них:
- дверь ~2.0-2.1 м высотой
- ряд кирпичной кладки ~7.5 см (с швом), кирпич ~25 см длиной
- этаж здания ~2.8-3.0 м
- человек ~1.7-1.8 м
- окно ~1.2-1.5 м высотой
- гаражные ворота ~2.5-3 м
- поддон/паллета 1.2 м, евроконтейнер, машина ~4.5 м длиной

Ответь по-русски кратко:
1. Ширина и высота стены (диапазон, м)
2. Площадь (м²)
3. По каким ориентирам считал
4. Примерный расход краски (баллон 400мл ≈ 1-1.5 м² в один слой)
Если ориентиров нет — скажи честно что оценка очень грубая."""

DOC_KEYWORDS = ["чек", "счёт", "счет", "фактур", "rechnung", "kassenbon", "quittung",
                "invoice", "receipt", "kontoauszug", "договор", "квитанция", "выписка",
                "dokument", "документ", "pdf", "финанс", "расход", "доход", "оплат"]

DOC_PROMPT = """Внимательно прочитай файл по пути {path} (инструмент Read).

Если это ФОТО бумажного документа — оно может быть снято под углом, бумага помята, со
складками, тенями и сгибами. Всё равно аккуратно распознай ВЕСЬ текст и ВСЕ числа, мысленно
выровняв страницу. Не пропускай строки и суммы. Если цифра нечёткая — выбери наиболее
вероятную по контексту, но не выдумывай.

Немецкий формат чисел: 4.372,32 = 4372.32 (точка — разделитель тысяч, запятая — десятичная).

Это официальный/финансовый документ (чек, Rechnung, Kassenbon, Kontoauszug, письмо из
ведомства или кассы — Krankenkasse/Finanzamt/AOK и т.п., договор и т.д.).

Проанализируй по немецкому праву и верни ТОЛЬКО JSON без markdown:
{{
  "doc_type": "Kassenbon|Rechnung|Kontoauszug|Vertrag|Behoerdenbrief|Sonstiges",
  "date": "YYYY-MM-DD или null",
  "amount": число или null,
  "currency": "EUR",
  "is_expense": true/false,
  "category": "краткая категория по-русски",
  "counterparty": "от кого документ (организация) или null",
  "mwst_rate": 7 или 19 или 0 или null,
  "mwst_amount": число или null,
  "vorsteuer": true если можно заявить Vorsteuerabzug (только если корректная Rechnung с MwSt-Ausweis),
  "betriebsausgabe": true если деловой расход по §4 EStG,
  "summary": "1-2 строки по-русски: что это за документ и ключевые суммы/сроки",
  "tax_note": "комментарий о налогово-правовой значимости по немецкому праву, 1-2 предложения по-русски",
  "recommendation": "что сделать с документом по-русски",
  "finance_comment": "короткое описание для записи в финансы",
  "add_to_finance": true если стоит записать в финансы
}}

ВАЖНО про amount: бери ИТОГОВУЮ сумму. Для Kontoauszug — конечное сальдо «Saldo neu» / сумму
к оплате. Для счёта (Rechnung) — Gesamtbetrag. Для письма с требованием оплаты — итог к оплате.
Никогда не вписывай в ответ IBAN, BIC, Steuernummer или Versichertennummer."""


def _is_doc_caption(caption: str) -> bool:
    if not caption:
        return False
    low = caption.lower()
    return any(k in low for k in DOC_KEYWORDS)


def analyze_doc_sync(path: str) -> dict:
    """Распознаёт финансовый/официальный документ через Claude CLI (sonnet — точнее OCR)."""
    result = _claude_exec([CLAUDE_BIN, "-p", DOC_PROMPT.format(path=path),
         "--allowedTools", "Read",
         "--model", "sonnet",
         "--max-turns", "5"], timeout=160)
    raw = result.stdout.strip()
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return jsonlib.loads(m.group())
    raise ValueError(f"no JSON in response: {raw[:200]}")


async def _send_doc_analysis(update: Update, ctx: ContextTypes.DEFAULT_TYPE, r: dict):
    """Отправляет результат анализа документа с кнопкой добавления в финансы."""
    import json as _json
    sign = "📤 Расход" if r.get("is_expense", True) else "📥 Доход"
    try:
        amt = float(r["amount"]) if r.get("amount") is not None else None
    except (TypeError, ValueError):
        amt = None
    amt_str = f"{amt:.2f} {r.get('currency','EUR')}" if amt else "сумма не определена"

    lines = [
        f"📄 *{r.get('doc_type','Документ')}*",
        f"📅 {r.get('date') or 'дата не указана'}",
        f"{sign}: *{amt_str}*",
        f"🏪 {r.get('counterparty') or '—'}",
        f"🏷 {r.get('category','—')}",
    ]
    if r.get("summary"):
        lines.append(f"\n📋 _{r['summary']}_")

    mwst = r.get("mwst_rate")
    if mwst is not None:
        mwst_line = f"🧾 MwSt {mwst}%"
        if r.get("mwst_amount"):
            mwst_line += f" = {r['mwst_amount']:.2f}€"
        lines.append(mwst_line)

    flags = []
    if r.get("vorsteuer"):
        flags.append("✅ Vorsteuerabzug")
    if r.get("betriebsausgabe"):
        flags.append("✅ Betriebsausgabe")
    if flags:
        lines.append(" · ".join(flags))

    if r.get("tax_note"):
        lines.append(f"\n💡 _{r['tax_note']}_")
    if r.get("recommendation"):
        lines.append(f"📌 {r['recommendation']}")

    # Письма из ведомств/касс — это профиль Юриста: подскажем переслать туда
    if r.get("doc_type") in ("Behoerdenbrief", "Kontoauszug", "Vertrag"):
        lines.append("\n⚖️ Это вопрос для Юриста — перешли документ боту @Farbaholix_jurist, "
                     "он разберёт по сути и подскажет, что делать.")

    text = "\n".join(lines)

    keyboard = None
    if r.get("add_to_finance") and amt:
        signed_amt = round(amt * (-1 if r.get("is_expense", True) else 1), 2)
        comment = (r.get("finance_comment") or r.get("category") or "документ")[:80]
        cb = _json.dumps({"a": "doc_add", "v": signed_amt, "c": comment})
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ В финансы", callback_data=cb),
            InlineKeyboardButton("❌ Пропустить", callback_data='{"a":"doc_skip"}'),
        ]])

    chat_id = update.effective_chat.id
    try:
        await ctx.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await ctx.bot.send_message(chat_id, text, reply_markup=keyboard)


async def handle_doc_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик файлов-документов (PDF и т.д.)."""
    doc = update.message.document
    if not doc:
        return
    allowed_mime = {"image/jpeg", "image/png", "image/webp", "application/pdf",
                    "image/gif", "image/heic"}
    if doc.mime_type not in allowed_mime and not (doc.file_name or "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".pdf", ".webp")):
        await update.message.reply_text("📎 Пришли фото или PDF — проанализирую по немецким законам.")
        return

    wait = await update.message.reply_text("🔍 Анализирую документ...")
    ext = os.path.splitext(doc.file_name or ".bin")[1] or ".jpg"
    tmp = os.path.join(tempfile.gettempdir(), f"doc_{doc.file_id[:16]}{ext}")
    tg_file = await ctx.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(tmp)

    try:
        r = await asyncio.to_thread(analyze_doc_sync, tmp)
        await _send_doc_analysis(update, ctx, r)
        try:
            await ctx.bot.delete_message(update.effective_chat.id, wait.message_id)
        except Exception:
            pass
    except Exception as e:
        log.error(f"doc analysis: {e}")
        try:
            await ctx.bot.edit_message_text(f"⚠️ Не удалось распознать: {str(e)[:120]}", update.effective_chat.id, wait.message_id)
        except Exception:
            await update.message.reply_text(f"⚠️ Ошибка анализа: {str(e)[:120]}")
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


async def doc_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок добавления документа в финансы."""
    import json as _json
    q = update.callback_query
    await q.answer()
    try:
        data = _json.loads(q.data)
    except Exception:
        return
    if data.get("a") == "doc_add":
        v = float(data["v"])
        c = data.get("c", "документ")
        with db() as conn:
            conn.execute("INSERT INTO finance (amount, comment, account) VALUES (?,?,?)",
                         (v, c, "card"))
        sign = "📤" if v < 0 else "📥"
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(f"{sign} Записано: *{abs(v):.2f}€* — {c}", parse_mode="Markdown")
    elif data.get("a") == "doc_skip":
        await q.edit_message_reply_markup(None)
    elif data.get("a") == "klarna_skip":
        await q.edit_message_reply_markup(None)
    elif data.get("a") == "klarna_add":
        plans = ctx.user_data.get("klarna_plans") or []
        if not plans:
            await q.edit_message_text("⚠️ Данные устарели, пришли скриншот заново.")
            return
        await q.edit_message_reply_markup(None)
        today = date.today()
        added = 0
        with db() as conn:
            for p in plans:
                try:
                    monthly = round(float(p.get("monthly") or 0), 2)
                    if monthly <= 0:
                        continue
                    count = int(p["count"]) if p.get("count") else 0
                    done = int(p["done"]) if p.get("done") else 0
                    total = round(float(p["total"]), 2) if p.get("total") else round(monthly * (count or 1), 2)
                    paid = round(total * done / count, 2) if count else round(monthly * done, 2)
                    due_day = int(p["due_day"]) if p.get("due_day") else today.day
                    # ближайшая дата списания
                    dd = min(due_day, _calendar.monthrange(today.year, today.month)[1])
                    nxt = date(today.year, today.month, dd)
                    if nxt < today:
                        ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                        dd = min(due_day, _calendar.monthrange(ny, nm)[1])
                        nxt = date(ny, nm, dd)
                    name = str(p.get("merchant") or "Klarna")
                    if count:
                        name = f"{name} ({done}/{count})"
                    conn.execute(
                        """INSERT INTO debts (name, kind, total, paid, due_date, monthly, icon, note)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (name, "long", total, paid, nxt.isoformat(), monthly,
                         _klarna_icon(p.get("merchant")), "Klarna рассрочка")
                    )
                    added += 1
                except Exception as ex:
                    log.error(f"klarna insert: {ex}")
        await q.message.reply_text(
            f"✅ Добавил в долгосрочные долги: *{added}* {'план' if added == 1 else 'плана/планов'}.\n"
            "Смотри на дашборде → 💰 Финансы → 🏦 Долгосрочные долги.",
            parse_mode="Markdown")
    elif data.get("a") == "img_plan_cal":
        plan = ctx.user_data.get("pending_plan") or {}
        title = plan.get("title", "Событие")
        date_str = plan.get("date")
        time_str = plan.get("time") or ""
        if date_str:
            save_event(title, date_str, time_str)
            date_nice = date_str
            try:
                from datetime import datetime as _dt
                d = _dt.strptime(date_str, "%Y-%m-%d")
                months_ru = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
                date_nice = f"{d.day} {months_ru[d.month-1]}"
            except Exception:
                pass
            await q.edit_message_text(
                f"📅 Добавлено в календарь: *{title}*\n{date_nice}{' · ' + time_str if time_str else ''}",
                parse_mode="Markdown"
            )
            ctx.user_data.pop("pending_plan", None)
        else:
            ctx.user_data["state"] = "img_event_date"
            await q.edit_message_text(
                f"📅 *{title}* — дата не найдена на скриншоте.\n\nНапиши дату (например: «15 марта» или «2026-03-15»):",
                parse_mode="Markdown"
            )

    elif data.get("a") == "img_plan_park":
        plan = ctx.user_data.get("pending_plan") or {}
        title = plan.get("title", "Вводная со скриншота")
        note = plan.get("note")
        full = f"{title} — {note}" if note else title
        item_id = save_item(full, detect_area(full), detect_priority(full))
        await q.edit_message_text(
            f"📌 Припарковано: *{title}*",
            parse_mode="Markdown",
            reply_markup=confirm_kbd(item_id)
        )
        ctx.user_data.pop("pending_plan", None)

    elif data.get("a") in ("img_plan_guess", "img_plan_guess_park"):
        file_id = ctx.user_data.get("last_img_file_id")
        if not file_id:
            await q.edit_message_text("⚠️ Фото устарело, пришли заново.")
            return
        await q.edit_message_reply_markup(None)
        tg_file = await ctx.bot.get_file(file_id)
        tmp = os.path.join(tempfile.gettempdir(), f"img_{file_id[:16]}.jpg")
        await tg_file.download_to_drive(tmp)
        forced = "event" if data["a"] == "img_plan_guess" else "parking"
        try:
            wait = await q.message.reply_text("🔍 Читаю...")
            await _analyze_as_planning(update, ctx, tmp, wait, forced_kind=forced)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    elif data.get("a") in ("img_doc", "img_wall"):
        # Пользователь вручную выбрал тип неоднозначного фото
        file_id = ctx.user_data.get("last_img_file_id")
        if not file_id:
            await q.edit_message_text("⚠️ Фото устарело, пришли заново.")
            return
        await q.edit_message_reply_markup(None)
        tg_file = await ctx.bot.get_file(file_id)
        tmp = os.path.join(tempfile.gettempdir(), f"img_{file_id[:16]}.jpg")
        await tg_file.download_to_drive(tmp)
        try:
            if data["a"] == "img_doc":
                wait = await q.message.reply_text("🧾 Анализирую документ...")
                await _analyze_as_document(update, ctx, tmp, wait)
            else:
                wait = await q.message.reply_text("📐 Оцениваю размеры стены...")
                await _analyze_as_wall(update, ctx, tmp, wait)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass


CLASSIFY_PROMPT = """Прочитай изображение по пути {path} (инструмент Read).
Определи, что это:
- event — приглашение на мероприятие, билет (авиа, поезд, автобус, концерт, кино, театр, спорт, ресторан, день рождения), скриншот встречи/события с датой, подтверждение бронирования.
- parking — задача, идея, заметка, ссылка, напоминание — то, что надо не забыть, без конкретной даты или события.
- klarna — скриншот приложения рассрочек/платежей (Klarna, PayPal Ratenzahlung и т.п.):
  список предстоящих платежей, «Autopay», «Due in N days», рассрочка «X of Y», суммы в €.
- document — финансовый/официальный ДОКУМЕНТ (чек, счёт, Rechnung, Kassenbon,
  Kontoauszug, договор, письмо, квитанция, выписка, инвойс).
- wall — СТЕНА/поверхность для граффити (фото улицы, здания, забора, фасада).
- other — что-то ещё.
Ответь СТРОГО одним словом: event ИЛИ parking ИЛИ klarna ИЛИ document ИЛИ wall ИЛИ other"""


def classify_image_sync(path: str) -> str:
    """Быстрая классификация: event / parking / klarna / document / wall / other."""
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", CLASSIFY_PROMPT.format(path=path),
             "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "3"], timeout=90)
        out = (result.stdout or "").strip().lower()
        if "klarna" in out:
            return "klarna"
        if "document" in out:
            return "document"
        if "wall" in out:
            return "wall"
        if "event" in out:
            return "event"
        if "parking" in out:
            return "parking"
        return "other"
    except Exception as e:
        log.error(f"classify: {e}")
        return "other"


PLANNING_EXTRACT_PROMPT = """Прочитай изображение по пути {path} (инструмент Read).
Извлеки структурированную информацию. Верни СТРОГО JSON без пояснений:
{{
  "kind": "event если это мероприятие/билет/встреча с датой, иначе parking",
  "title": "короткое название по-русски, 2-7 слов — ЧТО именно",
  "date": "YYYY-MM-DD если есть, иначе null",
  "time": "HH:MM если есть, иначе null",
  "place": "место если есть, иначе null",
  "note": "контекст в 2-4 слова: откуда это, кто прислал, маршрут — или null"
}}"""


def extract_planning_sync(path: str) -> dict:
    """Извлекает title/date/time/place/note из скриншота приглашения или задачи."""
    result = _claude_exec([CLAUDE_BIN, "-p", PLANNING_EXTRACT_PROMPT.format(path=path),
         "--allowedTools", "Read", "--model", "haiku", "--max-turns", "3"], timeout=90)
    raw = result.stdout.strip()
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return jsonlib.loads(m.group())
    raise ValueError(f"no JSON: {raw[:200]}")


KLARNA_PROMPT = """Прочитай изображение по пути {path} (инструмент Read).
Это скриншот приложения рассрочек (Klarna или похожего). Извлеки ВСЕ планы рассрочки/платежи.
Для каждого определи:
- merchant: название продавца (eBay, Rex и т.п.)
- monthly: сумма ОДНОГО ежемесячного платежа в евро (число)
- total: полная сумма рассрочки в евро, если указана в скобках (число или null)
- done: сколько платежей уже сделано (число из «X of Y» → X) или null
- count: всего платежей в рассрочке (число из «X of Y» → Y) или null
- due_day: день месяца списания (из даты «Sep 22» → 22) или null
Объединяй дубликаты одного плана (один и тот же merchant с одинаковой суммой = один план).
Верни СТРОГО JSON без пояснений:
{{"plans":[{{"merchant":"...","monthly":12.65,"total":73,"done":3,"count":6,"due_day":1}}]}}"""


def analyze_klarna_sync(path: str) -> dict:
    """Разбирает скриншот Klarna в список планов рассрочки."""
    result = _claude_exec([CLAUDE_BIN, "-p", KLARNA_PROMPT.format(path=path),
         "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "5"], timeout=120)
    raw = result.stdout.strip()
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return jsonlib.loads(m.group())
    raise ValueError(f"no JSON in response: {raw[:200]}")


def _klarna_icon(merchant: str) -> str:
    m = (merchant or "").lower()
    if "ebay" in m:
        return "🛒"
    if "amazon" in m:
        return "📦"
    if "zalando" in m:
        return "👟"
    if "apple" in m:
        return "🍎"
    return "🛍"


async def _analyze_as_klarna(update, ctx, path, wait):
    import json as _json
    chat_id = update.effective_chat.id
    try:
        data = await asyncio.to_thread(analyze_klarna_sync, path)
        plans = data.get("plans") or []
        # дедупликация по (merchant, monthly)
        seen, uniq = set(), []
        for p in plans:
            key = (str(p.get("merchant", "")).lower(), round(float(p.get("monthly") or 0), 2))
            if key in seen or key[1] <= 0:
                continue
            seen.add(key)
            uniq.append(p)
        if not uniq:
            await ctx.bot.edit_message_text("🤔 Не нашёл планов рассрочки на скриншоте.",
                                            chat_id, wait.message_id)
            return
        lines = ["💳 *Рассрочки Klarna* — нашёл:"]
        total_monthly = 0.0
        for p in uniq:
            mon = float(p.get("monthly") or 0)
            total_monthly += mon
            prog = ""
            if p.get("done") and p.get("count"):
                prog = f" · {p['done']}/{p['count']}"
            tot = f" из {float(p['total']):.0f}€" if p.get("total") else ""
            day = f" · {p['due_day']}-го" if p.get("due_day") else ""
            lines.append(f"{_klarna_icon(p.get('merchant'))} *{p.get('merchant','?')}* — {mon:.2f}€/мес{tot}{prog}{day}")
        lines.append(f"\nИтого в месяц: *{total_monthly:.2f}€*")
        ctx.user_data["klarna_plans"] = uniq
        kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ В долги", callback_data='{"a":"klarna_add"}'),
            InlineKeyboardButton("❌ Пропустить", callback_data='{"a":"klarna_skip"}'),
        ]])
        await ctx.bot.edit_message_text("\n".join(lines), chat_id, wait.message_id,
                                        parse_mode="Markdown", reply_markup=kbd)
    except Exception as e:
        log.error(f"klarna: {e}")
        try:
            await ctx.bot.edit_message_text(f"⚠️ Ошибка разбора Klarna: {str(e)[:120]}", chat_id, wait.message_id)
        except Exception:
            await ctx.bot.send_message(chat_id, f"⚠️ Ошибка разбора Klarna: {str(e)[:120]}")


async def _analyze_as_document(update, ctx, path, wait):
    try:
        r = await asyncio.to_thread(analyze_doc_sync, path)
        await _send_doc_analysis(update, ctx, r)
        try:
            await ctx.bot.delete_message(update.effective_chat.id, wait.message_id)
        except Exception:
            pass
    except Exception as e:
        log.error(f"doc photo: {e}")
        try:
            await ctx.bot.edit_message_text(f"⚠️ Ошибка: {str(e)[:120]}", update.effective_chat.id, wait.message_id)
        except Exception:
            await ctx.bot.send_message(update.effective_chat.id, f"⚠️ Ошибка анализа: {str(e)[:120]}")


async def _analyze_as_wall(update, ctx, path, wait):
    def analyze():
        try:
            result = _claude_exec([CLAUDE_BIN, "-p", WALL_PROMPT.format(path=path),
                 "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "10"], timeout=180)
            return result.stdout.strip()
        except Exception as e:
            log.error(f"wall analyze: {e}")
            return ""

    answer = await asyncio.to_thread(analyze)
    try:
        await ctx.bot.delete_message(update.effective_chat.id, wait.message_id)
    except Exception:
        pass
    chat_id = update.effective_chat.id
    if not answer:
        await ctx.bot.send_message(chat_id, "Не получилось проанализировать фото 😔 Попробуй ещё раз.")
        return
    caption = (update.message.caption if update.message else "") or ""
    if caption:
        remember("user", f"[фото стены] {caption}")
    remember("assistant", answer[:500])
    try:
        await ctx.bot.send_message(chat_id, f"📐 {answer}", parse_mode="Markdown")
    except Exception:
        await ctx.bot.send_message(chat_id, f"📐 {answer}")


def save_event(text: str, date_str: str, time_str: str = "") -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO events (text, date, time) VALUES (?,?,?)",
            (text, date_str, time_str or None)
        )
        return cur.lastrowid


async def _analyze_as_planning(update, ctx, path, wait, forced_kind: str = None):
    """Извлекает событие/задачу из скриншота и предлагает выбор: календарь или парковка."""
    import json as _json
    chat_id = update.effective_chat.id
    try:
        data = await asyncio.to_thread(extract_planning_sync, path)
    except Exception as e:
        log.error(f"planning extract: {e}")
        try:
            await ctx.bot.edit_message_text("⚠️ Не удалось прочитать скриншот", chat_id, wait.message_id)
        except Exception:
            pass
        return

    kind = forced_kind or data.get("kind", "parking")
    title = (data.get("title") or "").strip() or "Без названия"
    date_str = data.get("date")
    time_str = data.get("time") or ""
    place = data.get("place")
    note = data.get("note")

    # Собираем человекочитаемое резюме
    lines = [f"{'📅' if kind == 'event' else '📌'} *{title}*"]
    if date_str:
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(date_str, "%Y-%m-%d")
            months_ru = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
            dstr = f"{d.day} {months_ru[d.month-1]}"
            lines.append(f"🗓 {dstr}{' · ' + time_str if time_str else ''}")
        except Exception:
            lines.append(f"🗓 {date_str}{' · ' + time_str if time_str else ''}")
    if place:
        lines.append(f"📍 {place}")
    if note:
        lines.append(f"💬 _{note}_")
    lines.append("")
    lines.append("Куда добавить?")

    ctx.user_data["pending_plan"] = {
        "title": title, "date": date_str, "time": time_str,
        "place": place, "note": note, "kind": kind,
    }

    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 В календарь", callback_data=_json.dumps({"a": "img_plan_cal"})),
        InlineKeyboardButton("📌 На парковку", callback_data=_json.dumps({"a": "img_plan_park"})),
    ]])
    try:
        await ctx.bot.edit_message_text(
            "\n".join(lines), chat_id, wait.message_id,
            parse_mode="Markdown", reply_markup=kbd
        )
    except Exception:
        await ctx.bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kbd)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ensure_kbd_cleared(update)
    caption = update.message.caption or ""
    photo = update.message.photo[-1]
    tg_file = await ctx.bot.get_file(photo.file_id)
    tmp = os.path.join(tempfile.gettempdir(), f"img_{photo.file_id[:16]}.jpg")
    await tg_file.download_to_drive(tmp)

    wait = await update.message.reply_text("🔍 Смотрю на фото...")

    # Подпись-подсказка имеет приоритет, иначе — автоклассификация
    if _is_doc_caption(caption):
        kind = "document"
    else:
        kind = await asyncio.to_thread(classify_image_sync, tmp)

    if kind in ("event", "parking"):
        try:
            lbl = "📅 Похоже на событие — читаю..." if kind == "event" else "📌 Похоже на задачу — читаю..."
            await ctx.bot.edit_message_text(lbl, update.effective_chat.id, wait.message_id)
        except Exception:
            pass
        await _analyze_as_planning(update, ctx, tmp, wait, forced_kind=kind)
    elif kind == "klarna":
        try:
            await ctx.bot.edit_message_text("💳 Скриншот рассрочек — разбираю...",
                                            update.effective_chat.id, wait.message_id)
        except Exception:
            pass
        await _analyze_as_klarna(update, ctx, tmp, wait)
    elif kind == "document":
        try:
            await ctx.bot.edit_message_text("🧾 Это документ — анализирую по немецким законам...",
                                            update.effective_chat.id, wait.message_id)
        except Exception:
            pass
        await _analyze_as_document(update, ctx, tmp, wait)
    elif kind == "wall":
        try:
            await ctx.bot.edit_message_text("📐 Это стена — оцениваю размеры...",
                                            update.effective_chat.id, wait.message_id)
        except Exception:
            pass
        await _analyze_as_wall(update, ctx, tmp, wait)
    else:
        # неоднозначно — спрашиваем пользователя кнопками
        import json as _json
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Событие", callback_data=_json.dumps({"a": "img_plan_guess"})),
             InlineKeyboardButton("📌 Задача/идея", callback_data=_json.dumps({"a": "img_plan_guess_park"}))],
            [InlineKeyboardButton("🧾 Документ", callback_data=_json.dumps({"a": "img_doc"})),
             InlineKeyboardButton("📐 Стена", callback_data=_json.dumps({"a": "img_wall"}))],
        ])
        ctx.user_data["last_img_file_id"] = photo.file_id
        try:
            await ctx.bot.edit_message_text("🤔 Не уверен, что это. Подскажи:",
                                            update.effective_chat.id, wait.message_id, reply_markup=kbd)
        except Exception:
            await update.message.reply_text("🤔 Не уверен, что это. Подскажи:", reply_markup=kbd)

    try:
        os.unlink(tmp)
    except Exception:
        pass


# ─── Callback кнопки ──────────────────────────────────────────────────────────

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("done:"):
        item_id = int(data.split(":")[1])
        with db() as conn:
            row = conn.execute("SELECT text FROM chaos WHERE id=?", (item_id,)).fetchone()
            conn.execute("UPDATE chaos SET done=1 WHERE id=?", (item_id,))
        await q.edit_message_text(f"✅ Закрыто: _{row['text'] if row else item_id}_", parse_mode="Markdown")

    elif data.startswith("del:"):
        item_id = int(data.split(":")[1])
        with db() as conn:
            row = conn.execute("SELECT text FROM chaos WHERE id=?", (item_id,)).fetchone()
            conn.execute("DELETE FROM chaos WHERE id=?", (item_id,))
        await q.edit_message_text(f"🗑 Удалено: _{row['text'] if row else item_id}_", parse_mode="Markdown")

    elif data.startswith("rezone:"):
        item_id = int(data.split(":")[1])
        ctx.user_data["rezone_id"] = item_id
        await q.edit_message_reply_markup(reply_markup=area_kbd(f"setzone:{item_id}"))

    elif data.startswith("setzone:"):
        parts = data.split(":")
        item_id = int(parts[1])
        area = parts[2]
        with db() as conn:
            conn.execute("UPDATE chaos SET area=? WHERE id=?", (area, item_id))
        await q.edit_message_text(f"Область обновлена: {AREAS[area]}")

    elif data.startswith("list:"):
        area = data.split(":")[1]
        await show_list_edit(q, area)

    elif data.startswith("bridge:"):
        period = data.split(":")[1]
        ctx.user_data["bridge_period"] = period
        ctx.user_data["state"] = "bridge_done"
        period_ru = {"day": "день", "week": "неделю", "month": "месяц"}.get(period, "период")
        await q.edit_message_text(
            f"⚓ Разбор за {period_ru}.\n\n*Что сделано?* Перечисли главные результаты:",
            parse_mode="Markdown"
        )

    elif data.startswith("proj:"):
        proj_id = int(data.split(":")[1])
        await show_proj_detail_msg(q.message, proj_id, edit=True, query=q)


# ─── Показ списков ────────────────────────────────────────────────────────────

def build_list_text(rows, title="📋 Список") -> str:
    if not rows:
        return f"{title}\n\n_Пусто! Всё под контролем_ 🎉"
    done_count = sum(1 for r in rows if r["done"])
    lines = [f"{title} — {done_count}/{len(rows)} закрыто\n"]
    for r in rows:
        if r["done"]:
            continue
        icon = area_emoji(r["area"])
        pri = "🔴 " if r["priority"] == "high" else ""
        lines.append(f"{pri}{icon} `[{r['id']}]` {r['text']}")
    if done_count:
        lines.append(f"\n_+ {done_count} закрытых_")
    return "\n".join(lines)


async def show_list(update: Update, area_filter: str = None):
    with db() as conn:
        if area_filter and area_filter not in ("all", "open"):
            rows = conn.execute(
                "SELECT * FROM chaos WHERE area=? ORDER BY done, priority='high' DESC, created_at DESC",
                (area_filter,)
            ).fetchall()
            title = f"📋 {AREAS.get(area_filter, 'Список')}"
        elif area_filter == "open":
            rows = conn.execute(
                "SELECT * FROM chaos WHERE done=0 AND id NOT IN "
                "(SELECT chaos_id FROM events WHERE chaos_id IS NOT NULL) "
                "ORDER BY priority='high' DESC, created_at DESC"
            ).fetchall()
            title = "📋 Парковка"
        else:
            rows = conn.execute(
                "SELECT * FROM chaos ORDER BY done, priority='high' DESC, created_at DESC"
            ).fetchall()
            title = "📋 Все записи"

    text = build_list_text(rows, title)
    if len(text) > 4000:
        text = text[:3900] + "\n…"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=list_filter_kbd())


async def show_list_edit(query, area_filter: str):
    with db() as conn:
        if area_filter == "open":
            rows = conn.execute(
                "SELECT * FROM chaos WHERE done=0 ORDER BY priority='high' DESC"
            ).fetchall()
            title = "📋 Открытые задачи"
        elif area_filter == "all":
            rows = conn.execute(
                "SELECT * FROM chaos ORDER BY done, priority='high' DESC"
            ).fetchall()
            title = "📋 Все записи"
        else:
            rows = conn.execute(
                "SELECT * FROM chaos WHERE area=? ORDER BY done, priority='high' DESC",
                (area_filter,)
            ).fetchall()
            title = f"📋 {AREAS.get(area_filter, '')}"

    text = build_list_text(rows, title)
    if len(text) > 4000:
        text = text[:3900] + "\n…"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=list_filter_kbd())


async def show_projects(update: Update):
    with db() as conn:
        projs = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()

    if not projs:
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("➕ создать проект", callback_data="newproj")]])
        await update.message.reply_text("Проектов пока нет. Создать первый?", reply_markup=kbd)
        return

    lines = ["📁 *Проекты*\n"]
    kbd_rows = []
    with db() as conn:
        for p in projs:
            steps = conn.execute("SELECT * FROM steps WHERE project_id=?", (p["id"],)).fetchall()
            done = sum(1 for s in steps if s["done"])
            total = len(steps)
            pct = f"{done}/{total}" if total else "нет шагов"
            icon = area_emoji(p["area"])
            lines.append(f"{icon} *{p['name']}* — {pct}")
            kbd_rows.append([InlineKeyboardButton(f"📁 {p['name']}", callback_data=f"proj:{p['id']}")])

    kbd_rows.append([InlineKeyboardButton("➕ новый проект", callback_data="newproj")])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kbd_rows)
    )


async def show_proj_detail_msg(message, proj_id: int, edit=False, query=None):
    with db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=?", (proj_id,)).fetchone()
        steps = conn.execute("SELECT * FROM steps WHERE project_id=? ORDER BY id", (proj_id,)).fetchall()
    if not proj:
        return

    done = sum(1 for s in steps if s["done"])
    total = len(steps)
    pct = int(done / total * 100) if total else 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

    lines = [f"📁 *{proj['name']}*  {AREAS.get(proj['area'], '')}\n"]
    for s in steps:
        mark = "✅" if s["done"] else "◻️"
        lines.append(f"{mark} {s['text']}")

    if not steps:
        lines.append("_Шагов пока нет_")
    else:
        lines.append(f"\n{bar} {pct}%")

    lines.append(f"\n_Добавить шаг: напиши «шаг: текст»_")

    text = "\n".join(lines)
    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ все проекты", callback_data="back:projects"),
    ]])

    if edit and query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kbd)
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=kbd)


async def show_stats(update: Update):
    with db() as conn:
        chaos_total = conn.execute("SELECT COUNT(*) FROM chaos").fetchone()[0]
        chaos_done = conn.execute("SELECT COUNT(*) FROM chaos WHERE done=1").fetchone()[0]
        chaos_high = conn.execute("SELECT COUNT(*) FROM chaos WHERE priority='high' AND done=0").fetchone()[0]
        proj_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        steps_total = conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0]
        steps_done = conn.execute("SELECT COUNT(*) FROM steps WHERE done=1").fetchone()[0]
        goals_open = conn.execute("SELECT COUNT(*) FROM goals WHERE done=0").fetchone()[0]
        bridge_count = conn.execute("SELECT COUNT(*) FROM bridge").fetchone()[0]

    chaos_pct = int(chaos_done / chaos_total * 100) if chaos_total else 0
    steps_pct = int(steps_done / steps_total * 100) if steps_total else 0

    msg = (
        f"📊 *Общая картина*\n\n"
        f"📋 Записей: {chaos_total} · закрыто {chaos_pct}%"
        + (f" · 🔴 срочных: {chaos_high}" if chaos_high else "") + "\n"
        f"📁 Проектов: {proj_count}  |  шаги: {steps_pct}% выполнено\n"
        f"🎯 Открытых целей: {goals_open}\n"
        f"⚓ Разборов: {bridge_count}\n"
    )

    if chaos_high:
        msg += f"\n⚠️ У тебя {chaos_high} срочных задач без закрытия"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── Команды ──────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    h = datetime.now().hour
    greeting = "Доброе утро" if h < 12 else ("Добрый день" if h < 17 else "Добрый вечер")
    await update.message.reply_text(
        f"{greeting}! 👋\n\n"
        "Я твой личный секретарь. Просто пиши или диктуй — я сохраню, "
        "разложу по полочкам и напомню.\n\n"
        "*Примеры:*\n"
        "• _Позвонить Роберту по поводу денег_\n"
        "• _Срочно! Оплатить страховку_\n"
        "• 🎤 Голосовое сообщение\n\n"
        "*Меню:*\n"
        "/ip — ссылка на дашборд\n"
        "/brief — сводка сейчас\n"
        "/update — обновить вручную прямо сейчас",
        parse_mode="Markdown",
        reply_markup=MAIN_KBD
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_list(update)


async def cmd_projects(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_projects(update)


async def cmd_goals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or ["week"]
    period = args[0] if args and args[0] in ("week", "month", "quarter", "year") else "week"
    period_names = {"week": "неделя", "month": "месяц", "quarter": "квартал", "year": "год"}

    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE period=? ORDER BY done, created_at DESC", (period,)
        ).fetchall()

    period_kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton(v, callback_data=f"goals_period:{k}")
        for k, v in period_names.items()
    ]])

    if not rows:
        await update.message.reply_text(
            f"🎯 *Цели — {period_names[period]}*\n\n_Целей нет. Пиши: «цель: текст»_",
            parse_mode="Markdown", reply_markup=period_kbd
        )
        return

    lines = [f"🎯 *Цели — {period_names[period]}*\n"]
    for g in rows:
        mark = "✅" if g["done"] else area_emoji(g["area"])
        lines.append(f"{mark} {g['text']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=period_kbd)


async def cmd_bridge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 день", callback_data="bridge:day"),
        InlineKeyboardButton("🗓 неделю", callback_data="bridge:week"),
        InlineKeyboardButton("📆 месяц", callback_data="bridge:month"),
    ]])
    await update.message.reply_text(
        "⚓ *Капитанский мостик*\n\nЗа какой период делаем разбор?",
        parse_mode="Markdown", reply_markup=kbd
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_stats(update)


# ─── Дополнительные callback ──────────────────────────────────────────────────

async def extra_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "newproj":
        ctx.user_data["state"] = "proj_name"
        await q.message.reply_text("📁 Как назовём проект?")

    elif q.data == "back:projects":
        await show_projects(q.message)

    elif q.data.startswith("goals_period:"):
        period = q.data.split(":")[1]
        period_names = {"week": "неделя", "month": "месяц", "quarter": "квартал", "year": "год"}
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE period=? ORDER BY done, created_at DESC", (period,)
            ).fetchall()
        period_kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton(v, callback_data=f"goals_period:{k}")
            for k, v in period_names.items()
        ]])
        if not rows:
            await q.edit_message_text(
                f"🎯 *Цели — {period_names[period]}*\n\n_Пусто_",
                parse_mode="Markdown", reply_markup=period_kbd
            )
            return
        lines = [f"🎯 *Цели — {period_names[period]}*\n"]
        for g in rows:
            mark = "✅" if g["done"] else area_emoji(g["area"])
            lines.append(f"{mark} {g['text']}")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=period_kbd)


# ─── Чат для рассылок ─────────────────────────────────────────────────────────

def save_chat_id(chat_id: int):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('chat_id', ?)", (str(chat_id),))


def get_chat_id():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='chat_id'").fetchone()
    return int(row["value"]) if row else None


# ─── Фоновые задачи ───────────────────────────────────────────────────────────

async def check_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id()
    if not chat_id:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with db() as conn:
        due = conn.execute(
            "SELECT * FROM reminders WHERE sent=0 AND due_at <= ?", (now,)
        ).fetchall()
        for r in due:
            conn.execute("UPDATE reminders SET sent=1 WHERE id=?", (r["id"],))
    for r in due:
        text = f"⏰ Напоминание: *{r['text']}*"
        if _send_via_director(text):
            continue  # доставлено в чат главного бота (Директора)
        try:
            await ctx.bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            log.error(f"reminder send: {e}")


# ─── Плановые затраты (регулярные + разовые платежи + текущие задолженности) ───

def _month_iter(d0, d1):
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def _payment_occurrences(p, d0, d1):
    out = []
    if p["kind"] == "planned" and p["date"]:
        try:
            dt = datetime.strptime(p["date"][:10], "%Y-%m-%d").date()
            if d0 <= dt <= d1:
                out.append(dt)
        except ValueError:
            pass
        return out
    recur = p["recur"] or "monthly"
    day = p["day"] or 1
    if recur == "monthly":
        for y, m in _month_iter(d0, d1):
            dd = min(day, _calendar.monthrange(y, m)[1])
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


def planned_spend(d0, d1):
    """[{date,title,amount,icon}] к оплате в диапазоне [d0,d1]."""
    items = []
    with db() as conn:
        try:
            pays = conn.execute("SELECT * FROM payments WHERE active=1").fetchall()
        except sqlite3.OperationalError:
            pays = []
        for p in pays:
            for dt in _payment_occurrences(p, d0, d1):
                items.append({"date": dt.isoformat(), "title": p["title"],
                              "amount": float(p["amount"]), "icon": p["icon"] or "💸"})
        try:
            debts = conn.execute(
                "SELECT * FROM debts WHERE kind='current' AND due_date IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            debts = []
        for d in debts:
            try:
                dt = datetime.strptime(d["due_date"][:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if d0 <= dt <= d1:
                items.append({"date": dt.isoformat(), "title": d["name"],
                              "amount": float(d["total"]), "icon": d["icon"] or "🔴"})
        # долгосрочные долги (включая рассрочки Klarna) — ежемесячный платёж в день due_date
        try:
            long_debts = conn.execute(
                "SELECT * FROM debts WHERE kind='long' AND monthly>0 AND due_date IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            long_debts = []
        for d in long_debts:
            try:
                base = datetime.strptime(d["due_date"][:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            day = base.day
            for y, m in _month_iter(d0, d1):
                dd = min(day, _calendar.monthrange(y, m)[1])
                dt = date(y, m, dd)
                if d0 <= dt <= d1:
                    items.append({"date": dt.isoformat(), "title": d["name"],
                                  "amount": float(d["monthly"]), "icon": d["icon"] or "💳"})
    items.sort(key=lambda x: x["date"])
    return items


def culture_for_today_sync() -> dict:
    """Праздник дня + факт из истории хип-хоп культуры на сегодня. Тихо падает в {}."""
    today = datetime.now().strftime("%d %B")           # напр. "26 June"
    today_num = datetime.now().strftime("%d.%m")        # напр. "26.06"
    prompt = (
        f"Сегодня {today} ({today_num}). Найди в интернете точные факты на ЭТУ дату "
        "(день и месяц, любой год) с помощью WebSearch и верни СТРОГО JSON без пояснений: "
        '{"holiday":"...","hiphop":"..."}. '
        "holiday — один интересный праздник/событие в мире на эту дату, который может быть "
        "интересен уличному художнику (искусство, культура, граффити, необычные мировые дни); "
        "коротко, по-русски, с эмодзи. "
        "hiphop — ОБЯЗАТЕЛЬНО заполни, никогда не оставляй пустым. Один точный факт из истории "
        "хип-хоп культуры, привязанный именно к этой дате. Приоритет выбора: "
        "1) день рождения легенды хип-хопа (рэпер, продюсер, диджей, граффити-райтер, брейкер, битбоксер) "
        "— имя, год рождения и одной фразой почему важен; "
        "2) либо важное событие/праздник хип-хоп культуры на эту дату (выход культового альбома или трека, "
        "основание лейбла/группы, рекорд, ключевое событие культуры) — что именно, год, в двух словах; "
        "3) если на точную дату ничего нет — приведи любой значимый факт «в этот день в истории хип-хопа». "
        "Проверяй даты по интернету, не выдумывай. По-русски, начни с эмодзи 🎤, 🎂 или 🎧."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--model", "haiku", "--max-turns", "6"], timeout=110)
        raw = result.stdout.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"culture: {ex}")
    # Фоллбэк без интернета: хотя бы хип-хоп факт из знаний модели
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--max-turns", "1", "--tools", ""], timeout=60)
        raw = result.stdout.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"culture fallback: {ex}")
    return {}


def legal_news_ua_men_sync() -> dict:
    """Свежие новости немецкого/ЕС законодательства о пребывании украинцев
    призывного возраста (муж. 18–60) в Германии и ЕС. Веб-исследование через
    Claude CLI + WebSearch с оценкой достоверности и важности. Кэш — на сутки
    (settings-ключ на дату), чтобы /brief несколько раз в день не перезапрашивал.
    Тихо возвращает {} при сбое сети."""
    cache_key = "ua_legal_brief:" + datetime.now().strftime("%Y-%m-%d")
    cached = _settings_get(cache_key)
    if cached:
        try:
            return jsonlib.loads(cached)
        except Exception:
            pass
    today = datetime.now().strftime("%d.%m.%Y")
    prompt = (
        f"Сегодня {today}. Найди через WebSearch/WebFetch САМЫЕ СВЕЖИЕ (за последние ~2-4 недели) "
        "новости и официальные публикации Германии и ЕС по теме: правовой статус и пребывание "
        "УКРАИНЦЕВ ПРИЗЫВНОГО ВОЗРАСТА — мужчин 18–60 лет — в Германии и Евросоюзе. "
        "Смотри: продление временной защиты (§24 AufenthG / EU Massenzustrom-Richtlinie, сроки до 2026/2027), "
        "изменения по Aufenthaltstitel/Bürgergeld/Jobcenter для этой группы, украинские правила выезда/паспортов/"
        "консульских услуг за границей и их влияние на статус в ЕС, любые решения ЕС/Бундестага/BAMF/МВД (BMI), "
        "заявления о возможной депортации/невыезде/мобилизации в контексте пребывания в Германии. "
        "Приоритет надёжным источникам: bamf.de, bundesregierung.de, auswaertiges-amt.de, bmi.bund.de, "
        "tagesschau.de, mediendienst-integration.de, официальные пресс-релизы ЕС. "
        "Проверяй даты и первоисточник, не выдумывай. Верни СТРОГО JSON без пояснений: "
        '{"summary":"...","importance":"...","confidence":"...","date":"..."}. '
        "summary — 1–3 очень коротких пункта самого важного и свежего (по-русски, через « · » как разделитель, "
        "без воды); если реально ничего нового за период — напиши «существенных изменений нет, статус прежний». "
        "importance — одной фразой, касается ли это лично украинца-мужчины призывного возраста на §24 в Германии. "
        "confidence — оценка достоверности: «высокая/средняя/низкая» + очень кратко почему (офиц. источник или СМИ). "
        "date — период/дата новостей."
    )
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--model", "haiku", "--max-turns", "10"], timeout=200)
        raw = result.stdout.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            data = jsonlib.loads(raw[s:e + 1])
            if data.get("summary"):
                _settings_set(cache_key, jsonlib.dumps(data, ensure_ascii=False))
                return data
    except Exception as ex:
        log.error(f"legal_news_ua: {ex}")
    return {}


async def morning_focus(ctx: ContextTypes.DEFAULT_TYPE, verbose: bool = False):
    chat_id = get_chat_id()
    if not chat_id:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    # Когда активен Директор (главный бот) — утро ведёт он: тот же постер шлёт его
    # бот. Ручной /brief в чате Секретаря работает по-прежнему.
    if not verbose and get_director_token():
        return
    # Защита от двойной сводки: автоматическую утреннюю отправляет только один
    # процесс/один раз в день (атомарная заявка в общей БД). Ручной /brief — всегда.
    if not verbose and not _claim_daily("brief_sent:" + today):
        return
    await render_owner_brief(ctx.bot, chat_id, verbose)


async def render_owner_brief(bot, chat_id: int, verbose: bool = False):
    """Утренний постер владельца (та самая «картинка» из сводки Секретаря). Общий
    рендер: зовётся и Секретарём (morning_focus), и Директором (его 07:00 и /brief),
    каждый шлёт своим ботом — картинка идентична, кто бы ни отправлял."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_d = date.today()
    with db() as conn:
        high = conn.execute(
            "SELECT text FROM chaos WHERE done=0 AND priority='high' ORDER BY importance DESC, urgency DESC, created_at LIMIT 5"
        ).fetchall()
        mid = conn.execute(
            "SELECT text FROM chaos WHERE done=0 AND priority='mid' ORDER BY created_at LIMIT 3"
        ).fetchall()
        todays = conn.execute(
            "SELECT due_at, text FROM reminders WHERE sent=0 AND due_at LIKE ?", (today + "%",)
        ).fetchall()
        cash = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'").fetchone()[0]
        card = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='card'").fetchone()[0]
        balance = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
        _hap_row = conn.execute("SELECT logged_at FROM happiness_log ORDER BY logged_at DESC LIMIT 1").fetchone()
        try:
            _hap_days = (datetime.now() - datetime.fromisoformat((_hap_row["logged_at"] if _hap_row else "")[:19])).days if _hap_row else 999
        except Exception:
            _hap_days = 999
        # Последний срез счастья — для «звезды Ж» внизу постера-сводки
        _hap_full = conn.execute(
            "SELECT work,friendship,health,wellbeing,hobby,love FROM happiness_log ORDER BY logged_at DESC LIMIT 1"
        ).fetchone()
        happiness = dict(_hap_full) if _hap_full else {
            "work": 3, "friendship": 3, "health": 3, "wellbeing": 3, "hobby": 3, "love": 3}
        # Проекты с флагом «в утреннюю сводку»
        try:
            brief_projs = conn.execute(
                "SELECT p.id, p.name, COUNT(s.id) as total, COALESCE(SUM(s.done),0) as done "
                "FROM projects p LEFT JOIN steps s ON s.project_id=p.id "
                "WHERE p.morning_brief=1 GROUP BY p.id ORDER BY p.created_at DESC LIMIT 5"
            ).fetchall()
        except Exception:
            brief_projs = []
        # События с флагом «в утреннюю сводку» начиная с сегодня
        try:
            brief_events = conn.execute(
                "SELECT text, date, time FROM events WHERE morning_brief=1 AND date>=? ORDER BY date, time LIMIT 5",
                (today,)
            ).fetchall()
        except Exception:
            brief_events = []

    spend_today = planned_spend(today_d, today_d)
    spend_week = planned_spend(today_d, today_d + timedelta(days=6))
    sum_today = sum(x["amount"] for x in spend_today)
    sum_week = sum(x["amount"] for x in spend_week)

    from wisdom import today_wisdom
    # Культурная справка (праздник дня + хип-хоп календарь)
    culture = await asyncio.to_thread(culture_for_today_sync)
    # Свежие немецкие/ЕС правовые новости про украинцев призывного возраста (кэш на день)
    ua_legal = await asyncio.to_thread(legal_news_ua_men_sync)

    lines = [f"☀️ *Доброе утро, Слава!*\n", f"_{today_wisdom()}_\n"]

    if high:
        lines.append("🔥 *Срочное на сегодня:*")
        for h in high:
            lines.append(f"• {h['text']}")
    elif mid:
        lines.append("🟡 *Важное на сегодня:*")
        for m in mid:
            lines.append(f"• {m['text']}")
    else:
        lines.append("✅ Срочного нет — день для важного.")

    if todays:
        lines.append("\n⏰ *Напоминания:*")
        for t in todays:
            lines.append(f"• {t['due_at'][11:16]} — {t['text']}")

    if brief_projs:
        lines.append("\n📁 *Проекты в фокусе:*")
        for p in brief_projs:
            pct = int(p["done"] / p["total"] * 100) if p["total"] else 0
            lines.append(f"• {p['name']} — {pct}% ({p['done']}/{p['total']})")

    if brief_events:
        lines.append("\n📌 *Задачи на сводку:*")
        for e in brief_events:
            d_fmt = f"{e['date'][8:10]}.{e['date'][5:7]}"
            t_fmt = f" {e['time']}" if e["time"] else ""
            lines.append(f"• {d_fmt}{t_fmt} — {e['text']}")

    lines.append(f"\n💸 *Расходы сегодня — {sum_today:.0f}€:*")
    if spend_today:
        for s in spend_today:
            lines.append(f"• {s['title']} — {s['amount']:.0f}€")
    else:
        lines.append("• плановых платежей нет")
    if sum_week:
        wnames = " · ".join(dict.fromkeys(s["title"] for s in spend_week))
        lines.append(f"_Ближайшие 7 дней: {sum_week:.0f}€ — {wnames}_")

    lines.append(f"\n💰 *Баланс: {balance:.0f}€* (💵 {cash:.0f} · 💳 {card:.0f})")

    if culture.get("holiday"):
        lines.append(f"\n🎉 *Праздник дня:* {culture['holiday']}")
    if culture.get("hiphop"):
        lines.append(f"🎤 *Хип-хоп календарь:* {culture['hiphop']}")

    if ua_legal.get("summary"):
        lines.append(f"\n🛂 *Украинцы призывного возраста (DE/ЕС):*\n{ua_legal['summary']}")
        conf = ua_legal.get("confidence")
        if conf:
            lines.append(f"_Достоверность: {conf}_")

    hap_reminder = ""
    if _hap_days >= 3:
        hap_reminder = f"🤗 *Переосознай счастье* — последняя оценка {_hap_days} дн. назад. Открой дашборд → вкладка Счастье."
        lines.append(f"\n{hap_reminder}")

    # Сначала пробуем красивую JPEG-сводку (постер под iPhone), иначе — текст
    urgent = [h["text"] for h in high] if high else ([m["text"] for m in mid] if mid else [])
    brief_data = {
        "date_str": datetime.now().strftime("%A, %d.%m · %H:%M"),
        "wisdom": today_wisdom(),
        "urgent": urgent,
        "reminders": [(t["due_at"][11:16], t["text"]) for t in todays],
        "spend_today": [(s["title"], s["amount"]) for s in spend_today],
        "sum_today": sum_today,
        "sum_week": sum_week,
        "week_names": " · ".join(dict.fromkeys(s["title"] for s in spend_week)),
        "balance": balance, "cash": cash, "card": card,
        "holiday": culture.get("holiday", ""),
        "hiphop": culture.get("hiphop", ""),
        "ua_legal": ua_legal or {},
        "brief_projs": [(p["name"], int(p["done"]/p["total"]*100) if p["total"] else 0)
                        for p in brief_projs],
        "brief_events": [(e["text"], e["date"], e["time"] or "") for e in brief_events],
        "happiness": happiness,
    }
    img_path = os.path.join(os.path.dirname(__file__), "brief_today.jpg")
    try:
        from brief_render import render_brief_jpeg
        # высота постера в CSS-px: если сводка выше ~1.4 экрана iPhone (844pt),
        # Telegram обрезает высокое фото в ленте — тогда шлём картинку ДОКУМЕНТОМ
        # (не режется, открываешь и листаешь целиком). Короткие — обычным фото.
        height_css = await asyncio.to_thread(render_brief_jpeg, brief_data, img_path)
        tall = (height_css or 0) > 1180
        with open(img_path, "rb") as f:
            if tall:
                await bot.send_document(
                    chat_id, f, filename="Сводка.jpg",
                    caption="☀️ Сводка на сегодня — открой, чтобы пролистать целиком")
            else:
                await bot.send_photo(chat_id, f, caption="☀️ Сводка на сегодня")
        if hap_reminder:
            await bot.send_message(chat_id, hap_reminder, parse_mode="Markdown")
        return
    except Exception as e:
        log.error(f"morning image failed, fallback to text: {e}")
        if verbose:
            await bot.send_message(
                chat_id,
                "ℹ️ Постер-картинка не собралась — шлю текстом.\n"
                f"Причина: {type(e).__name__}: {str(e)[:300]}\n\n"
                "Чтобы включить картинку, напиши /setupbrief")

    try:
        await bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        log.error(f"morning: {e}")


async def sunday_bridge(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id()
    if not chat_id:
        return
    week_ago = datetime.now().strftime("%Y-%m-%d", )
    with db() as conn:
        closed_week = conn.execute(
            "SELECT COUNT(*) FROM chaos WHERE done=1 AND created_at >= date('now','-7 days')"
        ).fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM chaos WHERE done=0").fetchone()[0]
        high_count = conn.execute(
            "SELECT COUNT(*) FROM chaos WHERE done=0 AND priority='high'"
        ).fetchone()[0]
        fin_week = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM finance WHERE created_at >= date('now','-7 days')"
        ).fetchone()[0]

    msg = (
        "⚓ *Воскресный мостик*\n\n"
        f"За неделю:\n"
        f"✅ закрыто задач: {closed_week}\n"
        f"📋 открыто сейчас: {open_count}" + (f" (🔴 {high_count} срочных)" if high_count else "") + "\n"
        f"💰 движение денег: {fin_week:+.2f}€\n\n"
        "Давай разберём неделю? Напиши /bridge — займёт 5 минут.\n"
        "_Система живёт только когда мостик регулярный._"
    )
    try:
        await ctx.bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        log.error(f"sunday: {e}")


# ─── Утренний дайджест ────────────────────────────────────────────────────────

async def morning_digest(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.chat_id
    with db() as conn:
        high = conn.execute(
            "SELECT * FROM chaos WHERE priority='high' AND done=0 ORDER BY created_at"
        ).fetchall()
        total_open = conn.execute("SELECT COUNT(*) FROM chaos WHERE done=0").fetchone()[0]
        goals = conn.execute(
            "SELECT * FROM goals WHERE period='week' AND done=0"
        ).fetchall()

    if not high and not goals:
        return

    lines = ["☀️ *Доброе утро!*\n"]
    if high:
        lines.append(f"🔴 Срочных задач: {len(high)}")
        for h in high[:3]:
            lines.append(f"  • {h['text']}")
        if len(high) > 3:
            lines.append(f"  _...и ещё {len(high)-3}_")
    lines.append(f"\n📋 Всего открытых: {total_open}")
    if goals:
        lines.append(f"🎯 Целей на неделю: {len(goals)}")

    await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")


async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Прислать утреннюю сводку прямо сейчас (ручной запуск)."""
    save_chat_id(update.effective_chat.id)
    await ctx.bot.send_message(update.effective_chat.id, "☀️ Собираю сводку…")
    await morning_focus(ctx, verbose=True)


# ─── Юрист: проактивные напоминания о немецких сроках/отчётах ──────────────────
# (месяц, день, ярлык, [за сколько дней предупредить], пояснение)
LEGAL_DEADLINES = [
    (7, 31, "Einkommensteuererklärung (ESt + Anlage EÜR + Anlage S)",
     [45, 14, 3, 0],
     "Срок самостоятельной подачи декларации о доходах за прошлый год (Freiberufler). "
     "Нужны: Anlage S (свободная профессия), Anlage EÜR (приход−расход). "
     "Со Steuerberater срок продлевается. Нужна помощь — нажми «⚖️ Юрист»."),
    (12, 1, "KSK · Änderungsmitteilung (если состоишь в KSK)",
     [10, 0],
     "Годовая оценка дохода от художественной деятельности на следующий год. "
     "Актуально только если ты член KSK. Если ещё думаешь о вступлении — спроси Юриста."),
    (1, 15, "Новый налоговый год: пороги и ставки обновились",
     [0],
     "Ставки KSK/Künstlersozialabgabe, порог Kleinunternehmer и правила §24 пересматриваются ежегодно. "
     "Хороший момент свериться с Юристом: не пора ли менять статус, вступать в KSK, проверить оборот."),
]


def _settings_get(key):
    try:
        with db() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None
    except Exception:
        return None


def _settings_set(key, val):
    try:
        with db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, str(val)))
    except Exception as e:
        log.error(f"settings_set: {e}")


def _claim_daily(key) -> bool:
    """Атомарная заявка «сделать один раз»: возвращает True только первому, кто
    вставил ключ (INSERT OR IGNORE → rowcount). Переживает несколько процессов
    и рестарты, так как состояние в общей БД. Используется, чтобы утренняя сводка
    не отправлялась дважды."""
    try:
        with db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
            cur = conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, '1')", (key,))
            return cur.rowcount == 1
    except Exception as e:
        log.error(f"claim_daily: {e}")
        return True  # при сбое БД лучше отправить, чем промолчать


def get_jurist_token() -> str:
    """Токен Юрист-бота: сначала окружение, затем настройка в БД (никогда не в git).
    Чистим любые пробелы/переводы строк — токен их не содержит, а автокоррекция в Telegram
    иногда вставляет пробел внутрь (из-за чего Telegram отвергает токен как невалидный)."""
    raw = os.environ.get("JURIST_BOT_TOKEN") or _settings_get("jurist_bot_token") or ""
    return "".join(raw.split())


# ── Продавец: отдельный бот (sales_bot.py) ───────────────────────────────────
SELLER_WINDOW = 30      # последних реплик диалога дословно в контекст
SELLER_STORE_CAP = 400  # реплик хранить в БД максимум


def get_sales_token() -> str:
    """Токен Продавец-бота: окружение → настройка в БД (не в git). Пробелы чистим —
    автокоррекция Telegram иногда вставляет пробел внутрь токена."""
    raw = os.environ.get("SALES_BOT_TOKEN") or _settings_get("sales_bot_token") or ""
    return "".join(raw.split())


def _seller_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS seller_messages ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, text TEXT, "
                 "ts TEXT DEFAULT (datetime('now')))")


def remember_seller(role: str, text: str):
    """Реплика диалога с Продавцом — в его отдельную память (по образцу Юриста)."""
    try:
        with db() as conn:
            _seller_table(conn)
            conn.execute("INSERT INTO seller_messages (role, text) VALUES (?,?)", (role, text))
            conn.execute("DELETE FROM seller_messages WHERE id NOT IN "
                         "(SELECT id FROM seller_messages ORDER BY id DESC LIMIT ?)",
                         (SELLER_STORE_CAP,))
    except Exception as e:
        log.error(f"remember_seller: {e}")


def get_seller_memory():
    """Последние реплики диалога с Продавцом (старые → новые)."""
    try:
        with db() as conn:
            _seller_table(conn)
            rows = conn.execute("SELECT role, text FROM seller_messages ORDER BY id DESC LIMIT ?",
                                (SELLER_WINDOW,)).fetchall()
        return list(reversed(rows))
    except Exception as e:
        log.error(f"get_seller_memory: {e}")
        return []


def sales_dialog_sync(user_text: str) -> str:
    """Диалоговый Продавец для отдельного бота: как sales_agent_sync, но помнит
    переписку (окно последних реплик) и отвечает в живом диалоговом ритме."""
    sys_prompt = (SALES_PROMPT
                  .replace("{kb}", SALES_KB_DIR)
                  .replace("{strategy_kb}", STRATEGY_KB_DIR)
                  .replace("{legal_kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    funnel = get_funnel_context()
    leads = get_leads_context()
    plans = get_plans_context()
    hist = "\n".join(
        f"{'Владелец' if r['role'] == 'user' else 'Продавец'}: {r['text']}"
        for r in get_seller_memory())
    prompt = (
        f"{get_legal_context()}\n\n"
        + (funnel + "\n\n" if funnel else "")
        + (leads + "\n\n" if leads else "")
        + (plans + "\n\n" if plans else "")
        + (f"ПОСЛЕДНИЕ РЕПЛИКИ ДИАЛОГА (помни их, не повторяйся):\n{hist}\n\n" if hist else "")
        + "НОВОЕ СООБЩЕНИЕ ВЛАДЕЛЬЦА: " + user_text.strip() + "\n"
        "Правила роли уже в системном промпте; по теме при необходимости читай "
        "references/leadgen.md, references/tools.md, references/product.md. "
        "Это живой диалог: отвечай по делу, без повторения уже сказанного, длина — по ситуации."
    )
    skill = _kb_inline(os.path.join(SALES_KB_DIR, "SKILL.md"))
    if skill:
        sys_prompt += "\n\n=== SKILL.md (уже прочитан, Read не нужен) ===\n" + skill
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch", "--model", "sonnet", "--max-turns", "8"], timeout=360)
        raw = (result.stdout or "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        reply = ""
        if s >= 0 and e > s:
            try:
                reply = (jsonlib.loads(raw[s:e + 1]) or {}).get("reply", "")
            except Exception:
                reply = ""
        return reply or raw
    except Exception as e:
        log.error(f"sales_dialog: {e}")
        return ""


# ── Директор: отдельный бот (director_bot.py) ────────────────────────────────
DIRECTOR_WINDOW = 30      # последних реплик диалога дословно в контекст
DIRECTOR_STORE_CAP = 400  # реплик хранить в БД максимум


def get_director_token() -> str:
    """Токен Директор-бота: окружение → настройка в БД (не в git). Пробелы чистим —
    автокоррекция Telegram иногда вставляет пробел внутрь токена."""
    raw = os.environ.get("DIRECTOR_BOT_TOKEN") or _settings_get("director_bot_token") or ""
    return "".join(raw.split())


def _send_via_director(text: str) -> bool:
    """Доставить сообщение владельцу через ГЛАВНЫЙ бот (Директор): владелец общается
    только с ним, поэтому напоминания и плановые уведомления идут в его чат.
    False — если токена/чата нет или отправка не удалась (тогда шлёт вызывающий бот)."""
    token = get_director_token()
    chat_id = get_chat_id()
    if not token or not chat_id:
        return False
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Сначала Markdown; если Telegram отверг разметку — плоский текст
    for payload in ({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    {"chat_id": chat_id, "text": text.replace("*", "").replace("_", "")}):
        try:
            data = urllib.parse.urlencode(payload).encode()
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
                if r.status == 200:
                    return True
        except Exception as e:
            log.error(f"send via director: {e}")
    return False


def _director_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS director_messages ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, text TEXT, "
                 "ts TEXT DEFAULT (datetime('now')))")


def remember_director(role: str, text: str):
    """Реплика диалога с Директором — в его отдельную память (по образцу Продавца)."""
    try:
        with db() as conn:
            _director_table(conn)
            conn.execute("INSERT INTO director_messages (role, text) VALUES (?,?)", (role, text))
            conn.execute("DELETE FROM director_messages WHERE id NOT IN "
                         "(SELECT id FROM director_messages ORDER BY id DESC LIMIT ?)",
                         (DIRECTOR_STORE_CAP,))
    except Exception as e:
        log.error(f"remember_director: {e}")


def get_director_memory():
    """Последние реплики диалога с Директором (старые → новые)."""
    try:
        with db() as conn:
            _director_table(conn)
            rows = conn.execute("SELECT role, text FROM director_messages ORDER BY id DESC LIMIT ?",
                                (DIRECTOR_WINDOW,)).fetchall()
        return list(reversed(rows))
    except Exception as e:
        log.error(f"get_director_memory: {e}")
        return []


def get_director_snapshot() -> str:
    """Компактный срез показателей для триажа Директора — несколько строк вместо
    тяжёлых блоков (полные данные получают сами агенты на своём шаге)."""
    lines = []
    try:
        with db() as conn:
            cash = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'").fetchone()[0]
            card = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='card'").fetchone()[0]
            debts = conn.execute("SELECT COALESCE(SUM(total-COALESCE(paid,0)),0) FROM debts").fetchone()[0]
            try:
                regular = conn.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM payments WHERE active=1 "
                    "AND COALESCE(kind,'')!='planned'").fetchone()[0]
            except Exception:
                regular = 0
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                leads_n = conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE stage IN ('new','contacted','qualified','offer')"
                ).fetchone()[0]
                leads_over = conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE stage IN ('new','contacted','qualified','offer') "
                    "AND next_action_date IS NOT NULL AND next_action_date < ?", (today,)).fetchone()[0]
            except Exception:
                leads_n, leads_over = 0, 0
        lines.append(f"ДЕНЬГИ: карта {card:+.0f}€ · нал {cash:+.0f}€ · долги {debts:.0f}€ "
                     f"· регулярка ~{regular:.0f}€/мес")
        lines.append(f"ЛИДЫ: открыто {leads_n}, просрочено касаний {leads_over}")
    except Exception as e:
        log.error(f"director snapshot: {e}")
    try:
        yr = datetime.now().year
        with db() as conn:
            cnt, summ = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(gross),0) FROM invoice_archive WHERE year=?",
                (yr,)).fetchone()
            last3 = conn.execute(
                "SELECT number, client_name, gross FROM invoice_archive "
                "ORDER BY inv_date DESC, id DESC LIMIT 3").fetchall()
        if cnt:
            lines.append(f"СЧЕТА {yr}: {cnt} шт · оборот {summ:.0f}€ · последние: " + "; ".join(
                f"{r['number'] or '—'} {r['client_name'] or ''} {r['gross'] or 0:.0f}€" for r in last3))
    except Exception as e:
        log.error(f"director snapshot invoices: {e}")
    try:
        fun = get_funnel_context()
        if fun:
            lines.append(fun.splitlines()[-1])  # строка «Итого ожидаемо … взвешенно …»
    except Exception:
        pass
    return "\n".join(lines)


def get_director_state() -> str:
    """Энергоэкономная выжимка общей БД для триажа Директора: строка на объект,
    с id и обрезанными текстами — ровно столько, чтобы он мог актуализировать
    базу действиями (done/progress/stage/finance/unremind) за минимум токенов."""
    L = []
    try:
        with db() as conn:
            tasks = conn.execute(
                "SELECT id, text, priority FROM chaos WHERE done=0 "
                "ORDER BY priority='high' DESC, created_at DESC LIMIT 15").fetchall()
            if tasks:
                L.append("ЗАДАЧИ: " + " | ".join(
                    f"[{r['id']}]{'🔴' if r['priority'] == 'high' else ''} {r['text'][:45]}"
                    for r in tasks))
            cols = [c[1] for c in conn.execute("PRAGMA table_info(projects)").fetchall()]
            has_funnel = "income_status" in cols
            projs = conn.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 10").fetchall()
            plines = []
            for p in projs:
                nxt = conn.execute(
                    "SELECT text FROM steps WHERE project_id=? AND done=0 ORDER BY id LIMIT 1",
                    (p["id"],)).fetchone()
                seg = f"[{p['id']}] {p['name'][:30]}"
                if nxt:
                    seg += f" · след: {nxt['text'][:35]}"
                else:
                    seg += " · шаги закрыты"
                if has_funnel and (p["expected_income"] or 0) > 0 and (p["income_status"] or "lead") != "paid":
                    st = {"lead": "🔵", "agreed": "🟡", "invoiced": "🟠"}.get(p["income_status"] or "lead", "🔵")
                    seg += f" · {st}{p['expected_income']:.0f}€"
                plines.append(seg)
            if plines:
                L.append("ПРОЕКТЫ: " + " | ".join(plines))
            rems = conn.execute(
                "SELECT id, due_at, text FROM reminders WHERE sent=0 ORDER BY due_at LIMIT 5").fetchall()
            if rems:
                L.append("НАПОМИНАНИЯ: " + " | ".join(
                    f"[{r['id']}] {r['due_at'][5:16]} {r['text'][:30]}" for r in rems))
    except Exception as e:
        log.error(f"director state: {e}")
    return "\n".join(L)


def _director_route_fallback(user_text: str) -> dict:
    """Резервный детерминированный маршрут: если LLM-триаж дважды не ответил,
    поручение уходит агенту по ключевым словам — Директор никогда не молчит."""
    t = user_text.lower()
    if re.search(r"юрист|налог|счёт|счет|rechnung|invoice|договор|vertrag|ведомств|"
                 r"finanzamt|elster|ksk|krankenkass|виза|паспорт|правов|закон|легальн|"
                 r"штраф|деклара|kleinunternehmer|freiberufler|стран", t):
        to = "lawyer"
    elif re.search(r"прода|клиент|лид|цена|цену|оферт|\bкп\b|заказ|дожат|воронк|переговор|"
                   r"follow|аутрич|рассылк", t):
        to = "sales"
    elif re.search(r"стратег|кризис|план на год|куда ид|направлени|диверсифика|позиционир", t):
        to = "strategy"
    else:
        to = "secretary"
    return {"note": "распределяю экспресс-маршрутом", "fallback": True,
            "delegate": [{"to": to, "task": user_text}]}


DIRECTOR_PROMPT = """Ты — «Директор», главный агент и ЕДИНСТВЕННЫЙ интерфейс владельца: Вячеслав (Slavik), бренд FARBAHOLIX, граффити/мурал Künstler в Германии, украинец на §24, Kleinunternehmer §19 (оборот-2025 превысил порог — статус на 2026 под вопросом, правовой финал у Юриста), в KSK не состоит, есть долги и регулярные платежи. Владелец общается только с тобой.

Твоя задача СЕЙЧАС — быстрый триаж: решить, ответить самому или делегировать команде. Файлы читать не нужно — правила ниже, поручения из твоего JSON исполнятся агентами автоматически, результаты вернутся тебе на синтез.

КОМУ ЧТО (можно несколько поручений сразу):
- secretary — операционка и память: зафиксировать/запланировать/напомнить, проекты и шаги, финансы-учёт («потратил/получил», «сколько денег», «что горит»), контакты, сметы, письма-черновики.
- lawyer — немецкое право/налоги/статус (§19, §24, KSK, ELSTER, Finanzamt), счета (Rechnung), договоры, письма в ведомства, «можно ли по закону», выбор стран/каналов с правовой стороны.
- sales — клиенты и сделки: лиды, оферты, цена, переговоры, follow-up, дожатие, «что закрывать первым».
- strategy — большие развилки: «куда идём», кризис, план на год, диверсификация, позиционирование.
Пересечения: цена/большая сделка у порога §19 → sales И lawyer. Итог с записью в базу (оплата, новый проект, дедлайн) → добавь secretary.

АКТУАЛИЗАЦИЯ БАЗЫ — твоё право и обязанность. Вводные-факты владельца («сделано/отправлено X», «эскиз готов», «получил/потратил N€», «оплата пришла», «договорились на Y», «напомни…») фиксируй САМ полем actions, БЕЗ делегирования — база общая, все агенты сразу видят и не переспрашивают. Сопоставляй с блоком ТЕКУЩЕЕ СОСТОЯНИЕ (там id):
- {"type":"done","id":N} — задача [N] из списка выполнена
- {"type":"progress","project_id":N,"count":1} — шаг проекта [N] сделан
- {"type":"stage","project_id":N,"stage":"agreed|invoiced|paid"} — сделка сдвинулась; «оплата пришла» → stage paid И отдельный finance с суммой прихода
- {"type":"finance","amount":300 или -40,"comment":"...","account":"card|cash"} — получил/потратил (по умолчанию card)
- {"type":"save","text":"...","area":"work|money|health|people|home|self|other","importance":0-10,"urgency":0-10} — новая задача/вводная
- {"type":"remind","when":"YYYY-MM-DD HH:MM","text":"..."} — напоминание
- {"type":"unremind","id":N} — снять напоминание [N], потерявшее смысл (например, «проверь оплату» после «деньги пришли»)
- {"type":"contact","name":"...","note":"..."} — факт о человеке
Несколько фактов в одном сообщении → несколько actions. Если однозначно видно, о чём речь — фиксируй молча, не переспрашивая; неоднозначно (две похожие задачи) — один короткий вопрос в reply без actions.

Отвечай сам (reply) если: сообщение — вводные-факты (тогда reply = короткое подтверждение, 1-2 строки, + actions), ответ прямо в данных ниже (статус, цифра), уточнение или приветствие. В остальном — делегируй; в task передай ВСЕ данные из сообщения владельца, сформулировав как поручение специалисту.

Тон: по-русски, минимально. Не цитируй российских/советских авторов. Сегодня: {today}.

Ответь строго ОДНИМ JSON без текста вне его и без markdown-обёртки:
{"reply": "минимальный ответ владельцу", "actions": [...]}
или {"note": "1 строка владельцу: что делаешь", "delegate": [{"to": "secretary|lawyer|sales|strategy", "task": "чёткое поручение"}], "actions": [...]}
actions необязателен и может быть пустым."""


def director_dialog_sync(user_text: str) -> dict:
    """Диалоговый Директор, шаг 1: быстрый триаж (haiku, без инструментов, две
    попытки). Возвращает {"reply": ...} — прямой ответ, либо {"note": ...,
    "delegate": [...]} — поручения агентам. При полном сбое LLM — резервный
    маршрут по ключевым словам: пустого ответа не бывает."""
    sys_prompt = DIRECTOR_PROMPT.replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A"))
    snapshot = get_director_snapshot()
    state = get_director_state()
    hist = "\n".join(
        f"{'Владелец' if r['role'] == 'user' else 'Директор'}: {r['text'][:300]}"
        for r in get_director_memory()[-10:])
    prompt = (
        (snapshot + "\n\n" if snapshot else "")
        + (f"ТЕКУЩЕЕ СОСТОЯНИЕ (id для actions):\n{state}\n\n" if state else "")
        + (f"ПОСЛЕДНИЕ РЕПЛИКИ ДИАЛОГА:\n{hist}\n\n" if hist else "")
        + "СООБЩЕНИЕ ВЛАДЕЛЬЦА: " + user_text.strip()
    )
    for attempt in (1, 2):
        try:
            result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
                 "--model", "haiku", "--max-turns", "4", "--tools", ""], timeout=90)
        except subprocess.TimeoutExpired:
            log.error(f"director triage timeout (попытка {attempt})")
            continue
        except Exception as e:
            log.error(f"director triage (попытка {attempt}): {e}")
            continue
        raw = (result.stdout or "").strip()
        if not raw or raw.startswith("Error:") or "max turns" in raw.lower():
            log.error(f"director triage пусто/ошибка (попытка {attempt}): rc={result.returncode} "
                      f"out={raw[:200]!r} err={(result.stderr or '')[:300]!r}")
            continue
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            try:
                data = jsonlib.loads(raw[s:e + 1]) or {}
                if data.get("delegate") or data.get("reply") or data.get("actions"):
                    return data
            except Exception:
                pass
        return {"reply": raw}  # осмысленный текст без JSON — отдадим как есть
    return _director_route_fallback(user_text)


DIRECTOR_AGENT_LABEL = {"secretary": "🗂 Секретарь", "lawyer": "⚖️ Юрист",
                        "sales": "💼 Продавец", "strategy": "🧭 Стратег"}


def director_run_delegation(to: str, task: str):
    """Шаг 2: исполнить поручение Директора — вызвать нужного агента внутри
    процесса (те же мозги, что в их ботах). Возвращает (текст результата,
    заметки о записях в БД, файлы-приложения — например PDF счёта)."""
    notes, files = [], []

    def _applied(actions):
        applied = apply_actions(actions or [])
        notes.extend(f"{k}: {t}" for k, _i, t, _a, _p in applied)
        files.extend(p for k, _i, _t, p, _pr in applied if k == "invoice" and p)

    try:
        if to == "secretary":
            resp = ask_claude_sync(task) or {}
            _applied(resp.get("actions"))
            return resp.get("reply", "") or "", notes, files
        if to == "lawyer":
            remember_lawyer("user", "[поручение Директора] " + task[:300])
            resp = ask_lawyer_sync(task) or {}
            _applied(resp.get("actions"))
            reply = resp.get("reply", "") or ""
            if reply:
                remember_lawyer("lawyer", reply[:1500])
            return reply, notes, files
        if to == "sales":
            remember_seller("user", "[поручение Директора] " + task[:300])
            out = sales_agent_sync(task) or ""
            if out:
                remember_seller("assistant", out[:1500])
            return out, notes, files
        if to == "strategy":
            return strategy_council_sync() or "", notes, files
    except Exception as e:
        log.error(f"director delegation {to}: {e}")
    return "", notes, files


def director_finalize_sync(user_text: str, results: list) -> str:
    """Шаг 3: контроль и синтез. results = [(to, task, output, notes, files)].
    Директор проверяет результаты агентов и сводит владельцу минимум:
    итог · решения на подтверждение · задачи владельцу · следующий шаг."""
    blocks = []
    for to, task, output, notes, _files in results:
        label = DIRECTOR_AGENT_LABEL.get(to, to)
        out_cut = (output or "(пусто — агент не справился)")[:5000]  # диета токенов синтеза
        blocks.append(f"=== {label} ===\nПОРУЧЕНИЕ: {task[:500]}\nРЕЗУЛЬТАТ:\n{out_cut}"
                      + (("\nЗАПИСАНО В БАЗУ: " + "; ".join(notes)) if notes else ""))
    sys_prompt = (
        "Ты — «Директор» FARBAHOLIX. Твои агенты исполнили поручения — ниже их результаты. "
        "Проверь их (опора на данные, стыковка зон, соответствие поручению) и сведи владельцу "
        "МИНИМУМ по регламенту: 1) итог одной-тремя строками; 2) ✅ решения на подтверждение "
        "(если есть развилки); 3) 👤 задачи владельцу (только то, что агенты не могут сами); "
        "4) следующий шаг одной строкой. Слабые места результатов не пересказывай — учти молча. "
        "Тексты писем/документов, если агент их подготовил, приведи целиком (это результат, не процесс). "
        "По-русски, без воды. Telegram Markdown (жирный *одной звёздочкой*). "
        'Ответь строго JSON: {"reply": "текст владельцу"}. Никакого текста вне JSON.')
    prompt = (f"ЗАДАЧА ВЛАДЕЛЬЦА: {user_text}\n\n" + "\n\n".join(blocks)
              + "\n\nСведи по регламенту.")
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--model", "sonnet", "--max-turns", "4", "--tools", ""], timeout=240)
        raw = (result.stdout or "").strip()
        if not raw:
            log.error(f"director finalize пусто: rc={result.returncode} "
                      f"err={(result.stderr or '')[:300]!r}")
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            try:
                return (jsonlib.loads(raw[s:e + 1]) or {}).get("reply", "") or raw
            except Exception:
                pass
        return raw
    except Exception as e:
        log.error(f"director_finalize: {e}")
        return ""


def ensure_director_kb():
    """Самолечение: подтянуть director_kb с ветки, если файлов нет на диске."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    need = [x for x in UPDATE_FILES if x.startswith("director_kb/")]
    for f in need:
        dest = os.path.join(d, f)
        if os.path.exists(dest):
            continue
        try:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(data)
            log.info(f"director_kb fetched: {f}")
        except Exception as e:
            log.error(f"director_kb fetch {f}: {e}")


def ensure_secretary_kb():
    """Самолечение: подтянуть secretary_kb с ветки, если файлов нет на диске
    (Директор читает его для маршрутизации операционки)."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    need = [x for x in UPDATE_FILES if x.startswith("secretary_kb/")]
    for f in need:
        dest = os.path.join(d, f)
        if os.path.exists(dest):
            continue
        try:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(data)
            log.info(f"secretary_kb fetched: {f}")
        except Exception as e:
            log.error(f"secretary_kb fetch {f}: {e}")


def _sales_digest_history():
    """(последние 60 тем, ВСЕ использованные цитаты) — для антиповтора дайджеста."""
    topics, quotes = [], []
    try:
        with db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sales_digest_log ("
                         "id INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT, topic TEXT, "
                         "quotes TEXT, created_at TEXT DEFAULT (datetime('now')))")
            topics = [r["topic"] for r in conn.execute(
                "SELECT topic FROM sales_digest_log ORDER BY id DESC LIMIT 60") if r["topic"]]
            for r in conn.execute("SELECT quotes FROM sales_digest_log"):
                try:
                    quotes += jsonlib.loads(r["quotes"] or "[]")
                except Exception:
                    pass
    except Exception as e:
        log.error(f"sales_digest_history: {e}")
    return topics, quotes


def sales_digest_sync():
    """Утренний дайджест продаж (~7 минут чтения): тема + теория + цитаты + применение
    к реальной воронке + микро-задание. Антиповтор тем/цитат — по логу в БД.
    Возвращает (topic, text, quotes) или ("", "", [])."""
    topics, used_quotes = _sales_digest_history()
    protocol = os.path.join(SALES_KB_DIR, "references", "daily_digest.md")
    funnel = get_funnel_context()
    leads = get_leads_context()
    sys_prompt = (
        "Ты — Продавец, наставник по продажам художника FARBAHOLIX (Франкфурт, муралы/граффити). "
        f"Сгенерируй утренний дайджест СТРОГО по протоколу из файла {protocol} — прочитай его "
        "через Read ПЕРВЫМ действием и следуй структуре/объёму/тону из него. "
        "Сделай СЕГОДНЯ один WebSearch по свежим материалам о продажах и вплети находки, если ценные. "
        "Верни ТОЛЬКО JSON без чего-либо ещё: "
        '{"topic": "тема дня, коротко", "quotes": ["цитата — Книга, Автор", ...], '
        '"text": "полный текст дайджеста в Telegram Markdown (жирный *одной звёздочкой*)"}')
    prompt = (
        f"Сегодня {datetime.now().strftime('%Y-%m-%d, %A')}.\n\n"
        + (funnel + "\n\n" if funnel else "ВОРОНКА ПУСТА — сделай темой дня наполнение воронки.\n\n")
        + (leads + "\n\n" if leads else "")
        + ("ЗАПРЕЩЁННЫЕ ТЕМЫ (уже были, не повторяй и близко):\n- "
           + "\n- ".join(topics) + "\n\n" if topics else "")
        + ("ЗАПРЕЩЁННЫЕ ЦИТАТЫ (уже использованы, НИКОГДА не повторяй):\n- "
           + "\n- ".join(used_quotes[-200:]) + "\n\n" if used_quotes else "")
        + "Составь дайджест на сегодня.")
    try:
        result = _claude_exec([CLAUDE_BIN, "-p", prompt, "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch", "--model", "sonnet", "--max-turns", "16"], timeout=420)
        raw = (result.stdout or "").strip()
    except Exception as e:
        log.error(f"sales_digest run: {e}")
        return "", "", []
    topic, text, quotes = "", "", []
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        try:
            data = jsonlib.loads(raw[s:e + 1]) or {}
            topic = (data.get("topic") or "").strip()
            text = (data.get("text") or "").strip()
            quotes = [q for q in (data.get("quotes") or []) if isinstance(q, str)]
        except Exception:
            pass
    if not text:
        text = raw  # деградация: шлём как есть, лишь бы утро не пропало
    if text:
        try:
            with db() as conn:
                conn.execute("INSERT INTO sales_digest_log (d, topic, quotes) VALUES (?,?,?)",
                             (datetime.now().strftime("%Y-%m-%d"), topic,
                              jsonlib.dumps(quotes, ensure_ascii=False)))
        except Exception as ex:
            log.error(f"sales_digest log: {ex}")
    return topic, text, quotes


def render_sales_card(topic: str, quote: str, when: str):
    """Карточка дня к дайджесту: тема + цитата на тёмном градиенте (Pillow, офлайн).
    Возвращает путь к JPEG или None — ошибка рендера не блокирует текст."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import tempfile as _tf
        W, H = 1080, 1080
        MARGIN = 80
        MAXW = W - 2 * MARGIN  # рабочая ширина текста
        img = Image.new("RGB", (W, H))
        drw = ImageDraw.Draw(img)
        top_c, bot_c = (16, 22, 42), (74, 38, 94)  # тёмно-синий → фиолет
        for y in range(H):
            t = y / H
            drw.line([(0, y), (W, y)],
                     fill=tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3)))

        def _font(size, bold=False):
            for p in ("/System/Library/Fonts/Helvetica.ttc",
                      "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        def _tw(s, font):
            try:
                return drw.textlength(s, font=font)
            except Exception:
                b = drw.textbbox((0, 0), s, font=font)
                return b[2] - b[0]

        def _wrap_px(text, font, maxw):
            """Перенос по РЕАЛЬНОЙ ширине; слово шире полосы рубим по символам."""
            lines, cur = [], ""
            for word in (text or "").split():
                trial = (cur + " " + word).strip()
                if _tw(trial, font) <= maxw:
                    cur = trial
                    continue
                if cur:
                    lines.append(cur)
                if _tw(word, font) <= maxw:
                    cur = word
                else:
                    piece = ""
                    for ch in word:
                        if _tw(piece + ch, font) <= maxw:
                            piece += ch
                        else:
                            lines.append(piece)
                            piece = ch
                    cur = piece
            if cur:
                lines.append(cur)
            return lines

        y = 130
        drw.text((MARGIN, y), "УТРО ПРОДАЖ", font=_font(34), fill=(255, 208, 122))
        y += 92
        # заголовок: берём максимальный кегль (72→48), при котором ≤4 строк влезают
        title = topic or "Продажи сегодня"
        tf, tlines, size = _font(72, bold=True), None, 72
        for size in (72, 66, 60, 54, 48):
            tf = _font(size, bold=True)
            tlines = _wrap_px(title, tf, MAXW)
            if len(tlines) <= 4:
                break
        lh = int(size * 1.2)
        for line in (tlines or [])[:4]:
            drw.text((MARGIN, y), line, font=tf, fill=(255, 255, 255))
            y += lh
        if quote:
            y += 48
            drw.line([(MARGIN, y), (MARGIN + 120, y)], fill=(255, 208, 122), width=4)
            y += 40
            qf = _font(40)
            for line in _wrap_px("«" + quote.strip("«»\" ") + "»", qf, MAXW)[:8]:
                drw.text((MARGIN, y), line, font=qf, fill=(214, 220, 235))
                y += 56
        drw.text((MARGIN, H - 110), f"FARBAHOLIX · SALES · {when}",
                 font=_font(28), fill=(150, 158, 180))
        out = _tf.NamedTemporaryFile(suffix=".jpg", delete=False).name
        img.save(out, "JPEG", quality=90)
        return out
    except Exception as e:
        log.error(f"render_sales_card: {e}")
        return None


async def legal_deadlines_check(ctx: ContextTypes.DEFAULT_TYPE):
    """Раз в день: если до немецкого срока осталось ровно N дней — напомнить (без дублей)."""
    chat_id = get_chat_id()
    if not chat_id:
        return
    today = datetime.now(BERLIN).date() if BERLIN else date.today()
    for (mo, da, label, advs, note) in LEGAL_DEADLINES:
        try:
            dl = date(today.year, mo, da)
        except ValueError:
            continue
        for adv in advs:
            if dl - timedelta(days=adv) != today:
                continue
            key = f"legalremind:{label}:{today.year}:{adv}"
            if _settings_get(key):
                continue
            _settings_set(key, "1")
            days_left = (dl - today).days
            when = "сегодня" if days_left == 0 else f"через {days_left} дн."
            msg = (f"⚖️ *Юрист напоминает*\n\n📅 *{label}* — срок {dl.strftime('%d.%m.%Y')} "
                   f"({when}).\n\n{note}")
            if _send_via_director(msg):
                continue  # доставлено в чат главного бота (Директора)
            try:
                await ctx.bot.send_message(chat_id, msg, parse_mode="Markdown")
            except Exception as e:
                log.error(f"legal remind: {e}")


async def cmd_setupbrief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Разово доустановить Chromium (Playwright), чтобы сводка приходила красивым постером."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    import sys
    d = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable
    await ctx.bot.send_message(
        chat_id, "🛠 Ставлю Chromium для красивой сводки.\n"
                 "Это разово, ~1–3 минуты. Подожди, не закрывай чат…")

    def _run():
        steps = []
        r1 = subprocess.run([py, "-m", "pip", "install", "-q", "playwright"],
                            capture_output=True, text=True, cwd=d, timeout=900)
        steps.append(("pip install playwright", r1.returncode,
                      (r1.stderr or r1.stdout)))
        r2 = subprocess.run([py, "-m", "playwright", "install", "--with-deps", "chromium"],
                            capture_output=True, text=True, cwd=d, timeout=1200)
        steps.append(("playwright install chromium", r2.returncode,
                      (r2.stderr or r2.stdout)))
        # шрифты эмодзи + кириллица — по возможности
        subprocess.run("apt-get install -y fonts-noto-color-emoji fonts-dejavu "
                       ">/dev/null 2>&1 || true", shell=True, timeout=300)
        return steps

    try:
        steps = await asyncio.to_thread(_run)
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Установка прервалась: {type(e).__name__}: {e}")
        return

    if all(rc == 0 for _, rc, _ in steps):
        await ctx.bot.send_message(chat_id, "✅ Chromium установлен! Собираю постер для проверки…")
        await morning_focus(ctx, verbose=True)
    else:
        msg = "⚠️ Не всё установилось:\n"
        for name, rc, out in steps:
            msg += ("✅ " if rc == 0 else "❌ ") + name + "\n"
            if rc != 0 and out:
                msg += "   " + out.strip().replace("\n", " ")[-300:] + "\n"
        await ctx.bot.send_message(chat_id, msg[:3800])


# Откуда тянуть свежий код (raw GitHub, рабочая ветка)
REPO = "farbaholix-cloud/Bbbbasic"
BRANCH = "claude/schedule-display-app-ixjt6b"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
REPO_API = f"https://api.github.com/repos/{REPO}"
UPDATE_FILES = ["bot.py", "jurist_bot.py", "sales_bot.py", "director_bot.py", "invoice.py", "finance_report.py", "dashboard.py", "dashboard_biz.py", "dashboard_mac.py", "brief_render.py", "wisdom.py", "tts.py", "voicelive.py",
                "legal_kb/SKILL.md",
                "legal_kb/references/freiberufler-status.md",
                "legal_kb/references/kleinunternehmer.md",
                "legal_kb/references/elster-steuer.md",
                "legal_kb/references/ksk.md",
                "legal_kb/references/ihk-handwerk.md",
                "legal_kb/references/sozialversicherung.md",
                "legal_kb/references/letters.md",
                "legal_kb/references/invoice.md",
                "legal_kb/references/buerokratie.md",
                "strategy_kb/SKILL.md",
                "strategy_kb/references/finance.md",
                "strategy_kb/references/marketing.md",
                "strategy_kb/references/art-manager.md",
                "sales_kb/SKILL.md",
                "sales_kb/references/product.md",
                "sales_kb/references/leadgen.md",
                "sales_kb/references/daily_digest.md",
                "sales_kb/references/tools.md",
                "secretary_kb/SKILL.md",
                "director_kb/SKILL.md",
                "director_kb/references/ai-tools.md",
                "invoices_seed.json",
                "bank_seed.json"]
_SHA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deployed_sha")
_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gh_token")


def _load_gh_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    if os.path.exists(_TOKEN_FILE):
        try:
            with open(_TOKEN_FILE) as f:
                return f.read().strip()
        except Exception:
            pass
    return None


def _gh_headers():
    """Заголовки для GitHub API. Токен = 5000 req/h; без токена = 60 req/h."""
    h = {"Accept": "application/vnd.github.sha", "User-Agent": "friedman-bot"}
    tok = _load_gh_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _remote_sha():
    """Текущий SHA ветки на GitHub. Лёгкий запрос — отдаёт только хеш."""
    import urllib.request
    req = urllib.request.Request(f"{REPO_API}/commits/{BRANCH}", headers=_gh_headers())
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode().strip()


def _download_code(d, sha):
    """Скачать файлы по неизменяемому SHA — такие URL CDN никогда не отдаёт устаревшими.
    Двухфазно: сначала ВСЁ во временную папку с py_compile-проверкой .py-файлов,
    и только потом на место. Битый деплой не касается диска — иначе один
    синтаксис-фейл в bot.py кладёт сразу все боты (все его импортируют)."""
    import urllib.request
    import py_compile
    import shutil
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="deploy_", dir=d)
    staged = []  # (временный файл, куда класть)
    try:
        for f in UPDATE_FILES:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{sha}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            if len(data) < 100:
                raise RuntimeError(f"{f}: подозрительно мал ({len(data)} б)")
            tmp_path = os.path.join(tmpdir, f.replace("/", "__"))
            with open(tmp_path, "wb") as out:
                out.write(data)
            if f.endswith(".py"):
                py_compile.compile(tmp_path, doraise=True)  # SyntaxError → деплой отбит целиком
            staged.append((tmp_path, os.path.join(d, f)))
        for tmp_path, dest in staged:
            os.makedirs(os.path.dirname(dest), exist_ok=True)  # подпапки (legal_kb/…)
            shutil.move(tmp_path, dest)
        return list(UPDATE_FILES)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ensure_legal_kb():
    """Самолечение Юриста: если файлы legal_kb или сам jurist_bot.py отсутствуют (первый
    запуск новой версии до того, как авто-деплой подтянет подпапку/файл) — тянем с ветки."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    # + seed-файлы: при первом деплое /update качает по СТАРОМУ списку UPDATE_FILES,
    # поэтому новые файлы доезжают только самолечением
    need = (["jurist_bot.py", "sales_bot.py", "dashboard_biz.py", "invoice.py", "finance_report.py", "invoices_seed.json", "bank_seed.json"]
            + [x for x in UPDATE_FILES if x.startswith("legal_kb/")])
    for f in need:
        dest = os.path.join(d, f)
        if os.path.exists(dest):
            continue
        try:
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{f}", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(data)
            log.info(f"legal_kb fetched: {f}")
        except Exception as e:
            log.error(f"legal_kb fetch {f}: {e}")

    # Разовая ПРИНУДИТЕЛЬНАЯ замена шаблона счёта. Старый invoice.py мог уже лежать
    # на диске (клался руками, до git), поэтому обычное «если нет — скачать» его не
    # трогает и генерится старый дизайн. Один раз перетягиваем свежий шаблон с ветки,
    # дальше файл в UPDATE_FILES и обновляется обычным деплоем.
    try:
        if not _settings_get("invoice_tpl_v2"):
            h = {"User-Agent": "friedman-bot"}
            tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if tok:
                h["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/invoice.py", headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) > 500:  # страховка от пустого/битого ответа CDN
                with open(os.path.join(d, "invoice.py"), "wb") as out:
                    out.write(data)
                _settings_set("invoice_tpl_v2", "1")
                log.info("invoice.py template force-refreshed (v2)")
    except Exception as e:
        log.error(f"invoice tpl refresh: {e}")


def _self_restart(d: str):
    """Перезапускает bot.py через nohup-shell-скрипт в отдельной сессии.

    Не использует execv, потому что при падении нового процесса
    некому его поднять. Запускает новый бот в независимой сессии
    через subprocess.Popen с detach_process, затем текущий процесс завершается.
    """
    import sys
    log.info("перезапуск через detached subprocess")
    try:
        subprocess.Popen(
            [sys.executable, "-u", os.path.join(d, "bot.py")],
            cwd=d, stdout=open("/tmp/bot.log", "ab"), stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True
        )
        log.info("новый процесс запущен")
    except Exception as e:
        log.error(f"не удалось перезапустить: {e}")


def _proc_age_s(pid: int) -> int:
    """Возраст процесса в секундах (ps etimes); -1 — процесса нет/не узнали."""
    try:
        r = subprocess.run(["ps", "-o", "etimes=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=5)
        return int((r.stdout or "").strip() or -1)
    except Exception:
        return -1


def _kill_other_secretaries():
    """Синглтон Секретаря: при старте убиваем дубли-поллеры bot.py — иначе
    Telegram раздаёт апдейты между ними (Conflict в логах, ответы «через раз»,
    новые команды теряются у процесса со старым кодом).
    ВАЖНО (устранена гонка): убиваем только процессы СТАРШЕ себя (по возрасту,
    при равном возрасте — с меньшим PID). Если два новых Секретаря стартовали
    одновременно (авто-деплой + /update), взаимного уничтожения не будет —
    детерминированно выживает ровно один, самый новый.
    Паттерн `[ /]bot[.]py` не трогает jurist_/sales_/director_bot.py."""
    mypid = os.getpid()
    my_age = _proc_age_s(mypid)
    try:
        r = subprocess.run(["pgrep", "-f", "[ /]bot[.]py"],
                           capture_output=True, text=True, timeout=10)
    except Exception as e:
        log.error(f"kill dup secretaries (pgrep): {e}")
        return
    for tok in (r.stdout or "").split():
        try:
            pid = int(tok)
        except ValueError:
            continue
        if pid == mypid:
            continue
        age = _proc_age_s(pid)
        if age < 0:
            continue  # уже умер
        if age > my_age or (age == my_age and pid < mypid):
            try:
                os.kill(pid, 9)
                log.info(f"убил дубль секретаря PID {pid} (возраст {age}с)")
            except ProcessLookupError:
                pass
            except Exception as e:
                log.error(f"kill dup secretary PID {pid}: {e}")


def _restart_dashboard(d):
    """Перезапуск дашборда — освобождаем порт 8765 и поднимаем свежий процесс.
    Бизнес-пульт FARBAHOLIX смонтирован ВНУТРЬ dashboard.py (маршрут /biz на том
    же порту 8765) — отдельный процесс/порт не нужен, поднимается вместе с ним.
    На всякий случай гасим старый отдельный процесс 8770 из прежних версий."""
    import sys
    subprocess.run("pkill -9 -f dashboard.py; fuser -k 8765/tcp 2>/dev/null; true",
                   shell=True)
    subprocess.run("pkill -9 -f dashboard_biz.py; true", shell=True)  # снести legacy :8770
    logf = open("/tmp/dash.log", "ab")
    subprocess.Popen([sys.executable, "dashboard.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)


def _restart_jurist(d):
    """Поднять/перезапустить отдельного Юрист-бота (jurist_bot.py).
    Запускается только если есть токен (env или настройка в БД). Сначала гасим старый
    процесс, чтобы после деплоя поднялся свежий код, потом стартуем в отдельной сессии."""
    import sys
    if not get_jurist_token():
        log.info("Токен Юрист-бота не задан — Юрист-бот не запускаю")
        return
    subprocess.run("pkill -9 -f jurist_bot.py; true", shell=True)
    logf = open("/tmp/jurist.log", "ab")
    subprocess.Popen([sys.executable, "jurist_bot.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)
    log.info("Юрист-бот запущен (supervised)")


def _restart_sales(d):
    """Поднять/перезапустить отдельного Продавец-бота (sales_bot.py) — тот же
    паттерн, что _restart_jurist: только при наличии токена, старый процесс гасим."""
    import sys
    if not get_sales_token():
        log.info("Токен Продавец-бота не задан — Продавец-бот не запускаю")
        return
    subprocess.run("pkill -9 -f sales_bot.py; true", shell=True)
    logf = open("/tmp/sales.log", "ab")
    subprocess.Popen([sys.executable, "sales_bot.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)
    log.info("Продавец-бот запущен (supervised)")


def _ensure_sibling_file(d, filename):
    """Самолечение: если файл соседнего бота отсутствует на диске (первый деплой
    новой версии тянет код по СТАРОМУ списку UPDATE_FILES, где нового файла ещё
    нет) — дотягиваем его с ветки, чтобы `python <файл>` не падал «нет файла»."""
    dest = os.path.join(d, filename)
    if os.path.exists(dest):
        return True
    import urllib.request
    try:
        h = {"User-Agent": "friedman-bot"}
        tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(f"{RAW_BASE}/{BRANCH}/friedman_bot/{filename}", headers=h)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 100:
            raise RuntimeError(f"{filename}: подозрительно мал ({len(data)} б)")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            out.write(data)
        log.info(f"self-heal fetched: {filename}")
        return True
    except Exception as e:
        log.error(f"self-heal {filename}: {e}")
        return False


def _restart_director(d):
    """Поднять/перезапустить отдельного Директор-бота (director_bot.py) — тот же
    паттерн, что _restart_jurist/_restart_sales: только при наличии токена.
    Перед запуском чиним отсутствующий director_bot.py (самолечение)."""
    import sys
    if not get_director_token():
        log.info("Токен Директор-бота не задан — Директор-бот не запускаю")
        return
    if not _ensure_sibling_file(d, "director_bot.py"):
        log.error("director_bot.py отсутствует и не скачался — не запускаю Директора")
        return
    subprocess.run("pkill -9 -f director_bot.py; true", shell=True)
    logf = open("/tmp/director.log", "ab")
    subprocess.Popen([sys.executable, "director_bot.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)
    log.info("Директор-бот запущен (supervised)")


def _restart_secretary(d):
    """Перезапустить главный процесс Секретаря (bot.py) снаружи — по команде
    Директора (/update). Паттерн '[ /]bot[.]py' ловит «python bot.py» и запуск по
    абсолютному пути, но НЕ трогает jurist_bot.py/sales_bot.py/director_bot.py
    (перед их «bot.py» стоит «_»). Свежий bot.py при старте сам поднимет
    Юриста, Продавца и Директора."""
    import sys
    subprocess.run("pkill -9 -f '[ /]bot[.]py'; true", shell=True)
    logf = open("/tmp/bot.log", "ab")
    subprocess.Popen([sys.executable, "bot.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)
    log.info("Секретарь перезапущен (по команде Директора)")


def _restart_dashboard_mac(d):
    """Перезапуск Mac-дашборда. Он живёт как systemd-сервис (friedman-dashboard-mac),
    поэтому сначала пробуем systemctl — иначе systemd поднимет старую копию и они
    подерутся за порт 8766. Если сервиса нет — обычный pkill + запуск."""
    import sys
    r = subprocess.run("systemctl restart friedman-dashboard-mac", shell=True,
                       capture_output=True)
    if r.returncode == 0:
        return
    subprocess.run("pkill -9 -f dashboard_mac.py; fuser -k 8766/tcp 2>/dev/null; true",
                   shell=True)
    logf = open("/tmp/dash_mac.log", "ab")
    subprocess.Popen([sys.executable, "dashboard_mac.py"], cwd=d,
                     stdout=logf, stderr=logf, start_new_session=True)


def _download_file(d, sha, filename):
    """Скачать один файл по SHA (неизменяемый URL)."""
    import urllib.request
    h = {"User-Agent": "friedman-bot"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(f"{RAW_BASE}/{sha}/friedman_bot/{filename}", headers=h)
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    if len(data) < 100:
        raise RuntimeError(f"{filename}: подозрительно мал ({len(data)} б)")
    dest = os.path.join(d, filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        out.write(data)
    return filename


def _mac_file_version(d):
    """VERSION из dashboard_mac.py на диске — что именно будет запущено."""
    try:
        with open(os.path.join(d, "dashboard_mac.py")) as f:
            for line in f:
                if line.startswith("VERSION"):
                    return line.split('"')[1]
    except Exception:
        pass
    return "?"


def _update_mac_sync(d):
    """Обновить Mac-дашборд, возвращает подробный отчёт (каждый шаг — строка).

    Путь 1: /__deploy самого дашборда (проверка синтаксиса + systemctl restart) —
    это его штатный, проверенный механизм. Путь 2 (если дашборд не отвечает):
    скачать файл напрямую и перезапустить процесс."""
    import urllib.request
    steps = []
    # токен деплоя лежит в общей БД (его пишет сам dashboard_mac при старте)
    tok = _settings_get("deploy_token")
    if tok:
        try:
            url = f"http://127.0.0.1:8766/__deploy?token={tok}"
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read().decode(errors="replace")[:300]
            steps.append(f"✅ /__deploy: {body}")
            steps.append(f"📦 версия файла на диске: {_mac_file_version(d)}")
            return steps
        except Exception as e:
            steps.append(f"⚠️ /__deploy не сработал: {e}")
    else:
        steps.append("⚠️ deploy_token не найден в настройках (дашборд ни разу не стартовал?)")
    # запасной путь: скачать файл сами и перезапустить процесс
    try:
        sha = _remote_sha()
        _download_file(d, sha, "dashboard_mac.py")
        steps.append(f"✅ скачал dashboard_mac.py ({sha[:7]}), версия: {_mac_file_version(d)}")
    except Exception as e:
        steps.append(f"❌ скачивание: {e}")
        return steps
    r = subprocess.run("systemctl restart friedman-dashboard-mac", shell=True,
                       capture_output=True, text=True)
    if r.returncode == 0:
        steps.append("✅ systemctl restart friedman-dashboard-mac")
    else:
        err = (r.stderr or r.stdout or "").strip()[:200]
        steps.append(f"⚠️ systemctl: {err or 'код ' + str(r.returncode)} — пробую pkill")
        _restart_dashboard_mac(d)
        steps.append("✅ перезапустил процесс напрямую")
    # проверяем, что процесс жив
    import time as _t
    _t.sleep(2)
    chk = subprocess.run("pgrep -f dashboard_mac.py", shell=True, capture_output=True)
    steps.append("✅ процесс работает" if chk.returncode == 0 else
                 "❌ процесс НЕ поднялся — смотри /tmp/dash_mac.log")
    return steps


async def cmd_update_mac(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Быстрое обновление только Mac-дашборда, с пошаговым отчётом."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    d = os.path.dirname(os.path.abspath(__file__))
    await ctx.bot.send_message(chat_id, "🔄 Обновляю Mac-дашборд…")
    steps = await asyncio.get_event_loop().run_in_executor(None, lambda: _update_mac_sync(d))
    await ctx.bot.send_message(chat_id, "\n".join(steps) + "\n\n♻️ Обнови страницу (Cmd+Shift+R).")


async def cmd_setjuristtoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Принять токен Юрист-бота от владельца, сохранить в БД (не в git) и поднять бота.
    Сообщение с токеном сразу удаляем из чата ради безопасности."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    token = (update.message.text or "").partition(" ")[2]
    token = "".join(token.split())  # убираем любые пробелы/переводы строк (автокоррекция Telegram)
    # удаляем сообщение с токеном немедленно, чтобы он не висел в истории чата
    try:
        await ctx.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass
    if not re.match(r'^\d{6,}:[A-Za-z0-9_-]{30,}$', token):
        await ctx.bot.send_message(
            chat_id, "Это не похоже на токен. Пришли так: `/setjuristtoken 123456789:AA...`",
            parse_mode="Markdown")
        return
    _settings_set("jurist_bot_token", token)
    save_chat_id(chat_id)
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        _restart_jurist(d)
    except Exception as e:
        log.error(f"setjuristtoken restart: {e}")
        await ctx.bot.send_message(chat_id, f"Токен сохранён, но запуск дал сбой: {e}")
        return
    await ctx.bot.send_message(
        chat_id, "✅ Токен Юрист-бота сохранён, запускаю отдельного бота.\n"
                 "Открой нового бота в Telegram и нажми *Start* — он на связи.",
        parse_mode="Markdown")


async def cmd_setsalestoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Принять токен Продавец-бота, сохранить в БД (не в git) и поднять бота.
    Сообщение с токеном сразу удаляем из чата ради безопасности."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    token = (update.message.text or "").partition(" ")[2]
    token = "".join(token.split())
    try:
        await ctx.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass
    if not re.match(r'^\d{6,}:[A-Za-z0-9_-]{30,}$', token):
        await ctx.bot.send_message(
            chat_id, "Это не похоже на токен. Пришли так: `/setsalestoken 123456789:AA...`",
            parse_mode="Markdown")
        return
    _settings_set("sales_bot_token", token)
    save_chat_id(chat_id)
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        _restart_sales(d)
    except Exception as e:
        log.error(f"setsalestoken restart: {e}")
        await ctx.bot.send_message(chat_id, f"Токен сохранён, но запуск дал сбой: {e}")
        return
    await ctx.bot.send_message(
        chat_id, "✅ Токен Продавец-бота сохранён, запускаю отдельного бота.\n"
                 "Открой нового бота в Telegram и нажми *Start* — Продавец на связи. "
                 "Утренний дайджест продаж будет приходить туда в 07:00.",
        parse_mode="Markdown")


async def cmd_setdirectortoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Принять токен Директор-бота, сохранить в БД (не в git) и поднять бота.
    Сообщение с токеном сразу удаляем из чата ради безопасности."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    token = (update.message.text or "").partition(" ")[2]
    token = "".join(token.split())
    try:
        await ctx.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass
    if not re.match(r'^\d{6,}:[A-Za-z0-9_-]{30,}$', token):
        await ctx.bot.send_message(
            chat_id, "Это не похоже на токен. Пришли так: `/setdirectortoken 123456789:AA...`",
            parse_mode="Markdown")
        return
    _settings_set("director_bot_token", token)
    save_chat_id(chat_id)
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        _restart_director(d)
    except Exception as e:
        log.error(f"setdirectortoken restart: {e}")
        await ctx.bot.send_message(chat_id, f"Токен сохранён, но запуск дал сбой: {e}")
        return
    await ctx.bot.send_message(
        chat_id, "✅ Токен Директор-бота сохранён, запускаю отдельного бота.\n"
                 "Открой нового бота в Telegram и нажми *Start* — Директор на связи: "
                 "кидай ему задачу целиком, он раздаст поручения команде.",
        parse_mode="Markdown")


# Реквизиты счёта: поля, которые владелец задаёт командой. Секретные (iban/bic/
# steuernummer/ident_nr) НИКОГДА не в git — только в settings; в PDF без них плейсхолдер.
INVOICE_FIELDS = {
    "iban": "inv_iban", "bic": "inv_bic",
    "steuernummer": "inv_steuernummer", "stnr": "inv_steuernummer",
    "ident_nr": "inv_ident_nr", "identnr": "inv_ident_nr", "ident": "inv_ident_nr", "stid": "inv_ident_nr",
    "ust": "inv_ust_mode",
    "name": "inv_name", "title": "inv_title", "street": "inv_street",
    "phone": "inv_phone", "email": "inv_email", "city": "inv_city", "bank": "inv_bank",
}
_INVOICE_SECRET_KEYS = {"inv_iban", "inv_bic", "inv_steuernummer", "inv_ident_nr"}


async def cmd_setinvoicedata(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Задать реквизиты для счетов: /setinvoicedata <поле> <значение>.
    Поля: iban, bic, steuernummer, ident_nr | name, title, street, phone, email, city, bank.
    Секретные поля (iban/bic/steuernummer/ident_nr) хранятся только в БД, не в git;
    сообщение с ними сразу удаляется из чата."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    args = (update.message.text or "").partition(" ")[2].strip()

    # Пакетный формат: /setinvoicedata iban=DE.. bic=NASSDE55XXX steuernummer=.. stid=.. ust=kleinunternehmer
    if "=" in args:
        try:
            await ctx.bot.delete_message(chat_id, update.message.message_id)  # могут быть секреты
        except Exception:
            pass
        saved, unknown = [], []
        for pair in re.findall(r'(\w+)\s*=\s*("[^"]*"|\S+(?:\s+\S+)*?)(?=\s+\w+\s*=|$)', args):
            k = pair[0].lower().strip()
            v = pair[1].strip().strip('"')
            key = INVOICE_FIELDS.get(k)
            if not key or not v:
                unknown.append(k)
                continue
            _settings_set(key, v)
            saved.append(k if key in _INVOICE_SECRET_KEYS else f"{k}=«{v}»")
        msg = ("✅ Сохранено: " + ", ".join(saved) if saved else "Ничего не распознал.")
        if unknown:
            msg += f"\nНе распознаны: {', '.join(unknown)}."
        await ctx.bot.send_message(chat_id, msg)
        return

    field, _, value = args.partition(" ")
    field = field.lower().strip()
    value = value.strip()
    secret = INVOICE_FIELDS.get(field) in _INVOICE_SECRET_KEYS
    if secret:
        # секрет — стираем сообщение немедленно, чтобы не висело в истории чата
        try:
            await ctx.bot.delete_message(chat_id, update.message.message_id)
        except Exception:
            pass
    if field not in INVOICE_FIELDS or not value:
        await ctx.bot.send_message(
            chat_id,
            "Формат: `/setinvoicedata <поле> <значение>`\n"
            "Поля: `iban`, `bic`, `steuernummer`, `ident_nr` | "
            "`name`, `title`, `street`, `phone`, `email`, `city`, `bank`\n"
            "Напр.: `/setinvoicedata iban DE00 0000 0000 0000 0000 00`",
            parse_mode="Markdown")
        return
    _settings_set(INVOICE_FIELDS[field], value)
    if secret:
        await ctx.bot.send_message(
            chat_id, f"✅ Поле *{field}* сохранено ({len(value)} симв., значение скрыто).",
            parse_mode="Markdown")
    else:
        await ctx.bot.send_message(
            chat_id, f"✅ Поле *{field}* = «{value}» сохранено для счетов.",
            parse_mode="Markdown")


async def cmd_wipeinvoicestoday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Удалить ВСЕ счета, созданные сегодня: из архива (таблица invoices) и их PDF-файлы.
    Тестовые счета за день не должны висеть в контексте и завышать оборот. Только владелец."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    base = datetime.now().strftime("%d%m%y")          # номера сегодняшних счетов: ddmmyy[-N]
    today_dmy = datetime.now().strftime("%d.%m.%Y")
    with db() as conn:
        rows = conn.execute(
            "SELECT number, recipient, total FROM invoices "
            "WHERE number = ? OR number LIKE ? OR date = ?",
            (base, base + "-%", today_dmy)).fetchall()
    if not rows:
        await ctx.bot.send_message(chat_id, "Сегодняшних счетов в архиве нет — чистить нечего.")
        return
    # удаляем PDF-файлы (лежат в /tmp как Rechnung_<номер>.pdf)
    removed_files = 0
    for r in rows:
        num = r["number"] or ""
        safe = "".join(c for c in str(num) if c.isalnum() or c in "-_")
        for p in (os.path.join(tempfile.gettempdir(), f"Rechnung_{safe}.pdf"),):
            try:
                if safe and os.path.exists(p):
                    os.remove(p)
                    removed_files += 1
            except Exception as e:
                log.error(f"wipe invoice file {p}: {e}")
    # удаляем записи из архива
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM invoices WHERE number = ? OR number LIKE ? OR date = ?",
            (base, base + "-%", today_dmy))
        deleted = cur.rowcount
    listing = "\n".join(f"• {r['number']} · {(r['recipient'] or '')[:30]} · {r['total'] or 0:.0f}€" for r in rows)
    await ctx.bot.send_message(
        chat_id,
        f"🗑 Удалено из архива: *{deleted}* счёт(ов), PDF-файлов: {removed_files}.\n\n{listing}\n\n"
        "Оборот и контекст Юриста больше их не видят. Клиенты в памяти сохранены "
        "(если нужно забыть и клиента — скажи).",
        parse_mode="Markdown")


async def cmd_juriststatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Диагностика Юрист-бота: токен, файлы, процесс, хвост лога. При простое — пробует поднять."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    import subprocess as sp
    d = os.path.dirname(os.path.abspath(__file__))
    has_tok = bool(get_jurist_token())
    tok_src = ("env" if os.environ.get("JURIST_BOT_TOKEN")
               else ("БД" if _settings_get("jurist_bot_token") else "нет"))
    file_ok = os.path.exists(os.path.join(d, "jurist_bot.py"))
    kb_ok = os.path.exists(os.path.join(d, "legal_kb", "SKILL.md"))
    pg = sp.run("pgrep -f jurist_bot.py", shell=True, capture_output=True, text=True).stdout.strip()
    n_proc = len([x for x in pg.split("\n") if x.strip()])

    relaunched = False
    if has_tok and file_ok and n_proc == 0:
        try:
            _restart_jurist(d)
            relaunched = True
        except Exception as e:
            log.error(f"juriststatus relaunch: {e}")

    tail = ""
    try:
        if os.path.exists("/tmp/jurist.log"):
            with open("/tmp/jurist.log", "rb") as f:
                tail = f.read()[-4000:].decode("utf-8", "replace")
    except Exception as e:
        tail = f"(лог не прочитать: {e})"

    # Токен НИКОГДА не должен утечь в чат: в логах python-telegram-bot он светится
    # в URL вида bot<digits>:<secret>/getUpdates. Маскируем и его, и точное значение.
    tail = re.sub(r'bot(\d+):[A-Za-z0-9_-]{20,}', r'bot\1:***', tail)
    real_tok = get_jurist_token()
    if real_tok and len(real_tok) > 8:
        tail = tail.replace(real_tok, real_tok[:6] + "***")

    # Вытаскиваем последнюю строку-исключение — это и есть настоящая причина
    err_line = ""
    for line in reversed(tail.splitlines()):
        s = line.strip()
        if s and ("Error" in s or "Exception" in s or "Conflict" in s
                  or "Unauthorized" in s or "Timed" in s or s.startswith("telegram.")):
            err_line = s
            break

    msg = ("⚖️ *Статус Юрист-бота*\n"
           f"• токен: {'✅ есть' if has_tok else '❌ нет'} (источник: {tok_src})\n"
           f"• файл jurist_bot.py: {'✅' if file_ok else '❌ отсутствует'}\n"
           f"• база знаний legal_kb: {'✅' if kb_ok else '❌ нет'}\n"
           f"• процесс: {'✅ работает (' + str(n_proc) + ')' if n_proc else '❌ не запущен'}"
           + ("\n♻️ был простой — попробовал перезапустить" if relaunched else ""))
    if not has_tok:
        msg += "\n\n→ пришли токен: `/setjuristtoken ТОКЕН`"
    if err_line:
        msg += f"\n\n❗ *Похоже, ошибка:*\n`{err_line[:300]}`"
    if tail:
        msg += f"\n\nхвост лога:\n```\n{tail[-700:]}\n```"
    msg += "\n\n_Принудительно перезапустить:_ /juristrestart"
    await ctx.bot.send_message(chat_id, msg, parse_mode="Markdown")


async def cmd_juristrestart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Жёстко погасить и заново поднять Юрист-бота (после смены токена и т.п.)."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    if not get_jurist_token():
        await ctx.bot.send_message(chat_id, "Сначала пришли токен: /setjuristtoken ТОКЕН")
        return
    d = os.path.dirname(os.path.abspath(__file__))
    # чистим лог, чтобы /juriststatus показал свежую попытку
    try:
        open("/tmp/jurist.log", "w").close()
    except Exception:
        pass
    try:
        _restart_jurist(d)
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"Не вышло перезапустить: {e}")
        return
    await ctx.bot.send_message(
        chat_id, "♻️ Перезапустил Юриста. Через ~5 сек дай /juriststatus — посмотрим, поднялся ли.")


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🏓 {BOT_VERSION}")


async def cmd_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Присылает публичный IP сервера и прямую ссылку на дашборд."""
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            ip = r.read().decode().strip()
        await update.message.reply_text(
            f"🌐 Дашборд (жизнь):\nhttp://{ip}:8765\n\n"
            f"💼 Бизнес-пульт FARBAHOLIX:\nhttp://{ip}:8765/biz\n\n"
            f"Сохрани как PWA в Safari:\nПоделиться → На экран «Домой»")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Не удалось узнать IP: {e}")


# ─── Голос секретаря (TTS) ────────────────────────────────────────────────────

_VOICE_PREF = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".voice_pref")


def voice_enabled() -> bool:
    try:
        with open(_VOICE_PREF) as f:
            return f.read().strip() != "off"
    except Exception:
        return True  # по умолчанию отвечаем голосом на голос


def set_voice(on: bool):
    try:
        with open(_VOICE_PREF, "w") as f:
            f.write("on" if on else "off")
    except Exception:
        pass


async def speak_reply(update: Update, text: str):
    """Озвучивает ответ и шлёт его голосовым сообщением."""
    try:
        import tts
        path, is_voice = await asyncio.get_event_loop().run_in_executor(
            None, lambda: tts.synthesize(text))
        if not path:
            return
        with open(path, "rb") as f:
            if is_voice:
                await update.message.reply_voice(f)
            else:
                await update.message.reply_audio(f)
        try:
            os.unlink(path)
        except Exception:
            pass
    except Exception as e:
        log.error(f"TTS: {e}")


async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Вкл/выкл голосовые ответы: /voice [on|off]."""
    import tts
    arg = (ctx.args[0].lower() if ctx.args else "")
    if arg in ("on", "вкл", "1"):
        set_voice(True)
    elif arg in ("off", "выкл", "0"):
        set_voice(False)
    else:
        set_voice(not voice_enabled())
    state = "включён ✅" if voice_enabled() else "выключен ⏹"
    await update.message.reply_text(
        f"🔊 Голосовые ответы {state}\nГолос: {tts.active_backend()}\n\n"
        f"Шли голосовое — отвечу голосом. Не разговаривает вслух? Запусти /setupvoice.")


async def cmd_setupvoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ставит и прогревает голосовую модель прямо с сервера — Termius не нужен."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    import sys
    await ctx.bot.send_message(chat_id, "🎙 Готовлю голос (ставлю движки, первый раз ~1 мин)…")

    def work():
        # edge-tts — бесплатный нейроголос Microsoft (основной); omegaconf — для офлайн-Silero
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q",
                        "edge-tts", "omegaconf"], capture_output=True)
        import importlib
        import tts
        importlib.reload(tts)  # подхватить только что установленный edge-tts
        return tts.synthesize("Привет! Я секретарь Фридмана. Теперь я умею говорить вслух.")

    try:
        path, is_voice = await asyncio.get_event_loop().run_in_executor(None, work)
        set_voice(True)
        with open(path, "rb") as f:
            if is_voice:
                await ctx.bot.send_voice(chat_id, f)
            else:
                await ctx.bot.send_audio(chat_id, f)
        try:
            os.unlink(path)
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id, "✅ Голос готов. Шли голосовое — отвечу голосом.\n"
                     "/voice — включить/выключить озвучку.")
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Не вышло поднять голос: {e}")


# ─── Живой голосовой разговор (Gemini Live + PWA по HTTPS) ─────────────────────

_GEMINI_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gemini_key")
_VOICE_URL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".voice_url")
_CFD = os.path.expanduser("~/.local/bin/cloudflared")


async def cmd_settoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сохраняет GitHub Personal Access Token: /settoken ghp_..."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    args = ctx.args or []
    tok = args[0].strip() if args else ""
    if not tok or not tok.startswith("ghp_"):
        await update.message.reply_text(
            "Пришли токен так:\n/settoken ghp_xxxxxxxxxxxxxxxx\n\n"
            "Где взять:\ngithub.com → аватар → Settings → Developer settings "
            "→ Personal access tokens → Tokens (classic) → Generate new token (classic)\n"
            "Права: поставь галку repo → Generate token → скопируй.")
        return
    with open(_TOKEN_FILE, "w") as f:
        f.write(tok)
    try:
        await update.message.delete()  # убираем токен из чата
    except Exception:
        pass
    await ctx.bot.send_message(
        chat_id, "✅ GitHub токен сохранён — теперь /update не будет давать 403.")


async def cmd_setkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сохраняет ключ Gemini: /setkey <ключ>  (ключ AI Studio, бесплатный)."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    args = ctx.args or []
    key = args[-1].strip() if args else ""
    if not key or len(key) < 20:
        await update.message.reply_text(
            "Пришли ключ так: /setkey ВАШ_КЛЮЧ\n"
            "Бесплатный ключ — на aistudio.google.com → Get API key.")
        return
    with open(_GEMINI_KEY_FILE, "w") as f:
        f.write(key)
    try:
        await update.message.delete()  # убираем ключ из чата
    except Exception:
        pass
    await ctx.bot.send_message(chat_id, "🔑 Ключ Gemini сохранён. Теперь /setupvoicelive.")


def _voice_url():
    try:
        with open(_VOICE_URL_FILE) as f:
            return f.read().strip()
    except Exception:
        return ""


async def cmd_voiceapp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает адрес живого голосового приложения."""
    url = _voice_url()
    if url:
        await update.message.reply_text(
            f"🎙 Живой разговор:\n{url}\n\n"
            f"Открой в Safari → Поделиться → На экран «Домой».\n"
            f"Нет звука? Перезапусти /setupvoicelive.")
    else:
        await update.message.reply_text("Пока не поднято. Запусти /setupvoicelive.")


async def cmd_voicelog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает хвост логов голосового сервера и туннеля — для отладки."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    import socket as _socket

    def _port_open(port):
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        finally:
            s.close()

    parts = [f"порт 8766: {'слушает ✅' if _port_open(8766) else 'молчит ❌'}"]
    for label, path in [("voicelive", "/tmp/voicelive.log"), ("tunnel", "/tmp/cftunnel.log")]:
        try:
            with open(path) as f:
                tail = f.read()[-1000:].strip()
        except Exception:
            tail = "(нет файла)"
        parts.append(f"*{label}*:\n```\n{tail or '(пусто)'}\n```")
    msg = "\n\n".join(parts)
    try:
        await ctx.bot.send_message(chat_id, msg[:4000], parse_mode="Markdown")
    except Exception:
        await ctx.bot.send_message(chat_id, msg[:4000])


async def cmd_setupvoicelive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ставит зависимости, поднимает голосовой сервер и HTTPS-туннель, шлёт ссылку."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    if not os.path.exists(_GEMINI_KEY_FILE):
        await ctx.bot.send_message(chat_id, "Сначала пришли ключ: /setkey ВАШ_КЛЮЧ "
                                            "(бесплатный на aistudio.google.com).")
        return
    import sys
    import re as _re
    import socket as _socket
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    await ctx.bot.send_message(chat_id, "🛠 Готовлю живой голос: ставлю зависимости и туннель…")

    def _port_open(port: int) -> bool:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        finally:
            s.close()

    def work():
        # В venv нельзя ставить с --user (там user-site выключен) — иначе пакеты
        # «ставятся», но не импортируются и voicelive.py падает на старте.
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        pip_cmd = [sys.executable, "-m", "pip", "install", "-q",
                   "aiohttp", "edge-tts", "openai-whisper"]
        if not in_venv:
            pip_cmd.insert(4, "--user")
        pip = subprocess.run(pip_cmd, capture_output=True, text=True)
        pip_err = (pip.stderr or "").strip()

        # cloudflared — бесплатный HTTPS-туннель без домена и проброса портов
        if not os.path.exists(_CFD):
            os.makedirs(os.path.dirname(_CFD), exist_ok=True)
            urllib.request.urlretrieve(
                "https://github.com/cloudflare/cloudflared/releases/latest/download/"
                "cloudflared-linux-amd64", _CFD)
            os.chmod(_CFD, 0o755)
        # перезапуск процессов
        subprocess.run("pkill -9 -f voicelive.py; pkill -9 -f 'cloudflared.*8766'; true",
                       shell=True)
        import time as _t
        _t.sleep(1)
        # лог пишем заново, чтобы видеть свежий стек при падении
        open("/tmp/voicelive.log", "w").close()
        vlog = open("/tmp/voicelive.log", "ab")
        # -u: без буферизации, иначе лог пустой и падения не видно
        subprocess.Popen([sys.executable, "-u", "voicelive.py"], cwd=d,
                         stdout=vlog, stderr=vlog, start_new_session=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"})

        # ждём, пока сервер реально начнёт слушать порт 8766
        up = False
        for _ in range(15):
            _t.sleep(1)
            if _port_open(8766):
                up = True
                break
        if not up:
            tail = ""
            try:
                with open("/tmp/voicelive.log") as f:
                    tail = f.read()[-1500:]
            except Exception:
                pass
            return {"ok": False, "stage": "server", "log": tail, "pip_err": pip_err}

        clog_path = "/tmp/cftunnel.log"
        open(clog_path, "w").close()
        clog = open(clog_path, "ab")
        subprocess.Popen([_CFD, "tunnel", "--no-autoupdate", "--url",
                          "http://localhost:8766"], stdout=clog, stderr=clog,
                         start_new_session=True)
        url = ""
        for _ in range(30):
            _t.sleep(1)
            try:
                with open(clog_path) as f:
                    m = _re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", f.read())
                if m:
                    url = m.group(0)
                    break
            except Exception:
                pass
        if not url:
            return {"ok": False, "stage": "tunnel"}
        with open(_VOICE_URL_FILE, "w") as f:
            f.write(url)
        return {"ok": True, "url": url}

    try:
        res = await asyncio.get_event_loop().run_in_executor(None, work)
        if res.get("ok"):
            await ctx.bot.send_message(
                chat_id, f"✅ Готово!\n🎙 Живой разговор:\n{res['url']}\n\n"
                         f"Открой в Safari → Поделиться → На экран «Домой».\n"
                         f"Нажми «Поговорить» и общайся без кнопок.")
        elif res.get("stage") == "server":
            log_tail = (res.get("log") or "").strip() or "(пусто)"
            extra = f"\n\npip: {res['pip_err'][-300:]}" if res.get("pip_err") else ""
            await ctx.bot.send_message(
                chat_id, "⚠️ Голосовой сервер не поднялся (порт 8766 молчит). "
                         f"Лог:\n```\n{log_tail[-1200:]}\n```{extra}",
                parse_mode="Markdown")
        else:
            await ctx.bot.send_message(
                chat_id, "⚠️ Сервер поднялся, но туннель не вышел. "
                         "Повтори /setupvoicelive ещё раз.")
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Не вышло поднять живой голос: {e}")


async def cmd_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Самообновление из Telegram: скачать свежий код, перезапустить дашборд и себя.
    Больше не нужен Termius — пишешь /update боту, и всё."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return  # обновлять может только владелец
    d = os.path.dirname(os.path.abspath(__file__))
    await ctx.bot.send_message(chat_id, "🔄 Качаю свежий код с GitHub…")
    try:
        sha = _remote_sha()
        downloaded = _download_code(d, sha)
        try:
            with open(_SHA_FILE, "w") as f:
                f.write(sha)
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id, f"✅ Скачано ({sha[:7]}): " + ", ".join(downloaded) +
            "\n♻️ Перезапускаю дашборд и себя…")
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Не удалось обновить: {e}")
        return

    try:
        _restart_dashboard(d)
        _restart_dashboard_mac(d)
        await asyncio.sleep(1.5)
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Дашборд не стартовал: {e}")

    # перезапуск самого бота — заменяем процесс на свежий bot.py
    await ctx.bot.send_message(chat_id, "🚀 Готово! Поднимаюсь на новой версии. "
                                        "Через пару секунд напиши /brief для проверки.")
    _self_restart(d)
    os._exit(0)


async def watchdog_children(ctx: ContextTypes.DEFAULT_TYPE):
    """Сторож (каждые 5 минут): если процесс бота/дашборда умер — поднять и один
    раз в день уведомить владельца. Раньше упавший ночью бот лежал до следующего
    рестарта Секретаря — система «чинилась, когда владелец заметил»."""
    d = os.path.dirname(os.path.abspath(__file__))
    checks = (
        ("Юрист", "jurist_bot.py", _restart_jurist, get_jurist_token),
        ("Продавец", "sales_bot.py", _restart_sales, get_sales_token),
        ("Директор", "director_bot.py", _restart_director, get_director_token),
        ("Дашборд", "dashboard.py", _restart_dashboard, None),
    )
    for name, pat, restart, token_fn in checks:
        if token_fn and not token_fn():
            continue  # бот не сконфигурирован — следить не за чем
        try:
            r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                continue  # жив
        except Exception:
            continue
        log.error(f"watchdog: «{name}» ({pat}) не работает — поднимаю")
        try:
            restart(d)
        except Exception as e:
            log.error(f"watchdog restart {name}: {e}")
            continue
        if _claim_daily(f"watchdog:{pat}:{datetime.now().strftime('%Y-%m-%d')}"):
            msg = f"🛠 Сторож: «{name}» был неактивен — перезапустил."
            if not _send_via_director(msg):
                cid = get_chat_id()
                if cid:
                    try:
                        await ctx.bot.send_message(cid, msg)
                    except Exception:
                        pass


def _backup_db_sync() -> str:
    """Консистентная копия friedman.db (sqlite backup API — безопасно при
    параллельной записи) в backups/ с ротацией 7 дней. Возвращает путь копии."""
    d = os.path.dirname(os.path.abspath(__file__))
    bdir = os.path.join(d, "backups")
    os.makedirs(bdir, exist_ok=True)
    dest = os.path.join(bdir, f"friedman_{datetime.now().strftime('%Y-%m-%d')}.db")
    src = sqlite3.connect(DB, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    kept = sorted(f for f in os.listdir(bdir)
                  if f.startswith("friedman_") and f.endswith(".db"))
    for old in kept[:-7]:
        try:
            os.unlink(os.path.join(bdir, old))
        except Exception:
            pass
    return dest


def _weekly_backup_zip(db_copy: str) -> str:
    """Полный «сейф» недели: zip со свежей копией БД и ВСЕМИ PDF счетов из
    хранилища (в т.ч. весь текущий год). Ротация — 4 последних архива."""
    import zipfile
    d = os.path.dirname(os.path.abspath(__file__))
    bdir = os.path.join(d, "backups")
    os.makedirs(bdir, exist_ok=True)
    dest = os.path.join(bdir, f"farbaholix_{datetime.now().strftime('%Y-%m-%d')}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(db_copy, os.path.basename(db_copy))
        if os.path.isdir(INVOICES_PDF_DIR):
            for f in sorted(os.listdir(INVOICES_PDF_DIR)):
                if f.endswith(".pdf"):
                    z.write(os.path.join(INVOICES_PDF_DIR, f), "invoices_pdf/" + f)
    zips = sorted(f for f in os.listdir(bdir)
                  if f.startswith("farbaholix_") and f.endswith(".zip"))
    for old in zips[:-4]:
        try:
            os.unlink(os.path.join(bdir, old))
        except Exception:
            pass
    return dest


async def nightly_backup(ctx: ContextTypes.DEFAULT_TYPE):
    """Ежедневно 03:30 Berlin: бэкап БД с ротацией; по воскресеньям владельцу в
    Telegram уходит zip «база + все PDF счетов» — бесплатный оффсайт-«сейф в
    чате» на случай гибели сервера."""
    if not _claim_daily("db_backup:" + datetime.now().strftime("%Y-%m-%d")):
        return
    try:
        dest = await asyncio.to_thread(_backup_db_sync)
        log.info(f"бэкап БД: {dest}")
    except Exception as e:
        log.error(f"backup: {e}")
        return
    wd = (datetime.now(BERLIN) if BERLIN else datetime.now()).weekday()
    if wd == 6:  # воскресенье — полный «сейф»
        try:
            pack = await asyncio.to_thread(_weekly_backup_zip, dest)
        except Exception as e:
            log.error(f"backup zip: {e}")
            pack = dest  # деградация: хотя бы голая БД
        cid = get_chat_id()
        if cid:
            try:
                with open(pack, "rb") as f:
                    await ctx.bot.send_document(
                        cid, f, filename=os.path.basename(pack),
                        caption="🗄 Еженедельный бэкап: база + PDF всех счетов. Ничего "
                                "делать не нужно — просто пусть лежит в чате: это твой "
                                "сейф на случай сбоя сервера.")
            except Exception as e:
                log.error(f"backup send: {e}")


async def auto_update(ctx: ContextTypes.DEFAULT_TYPE):
    """Раз в ~90 сек проверяет GitHub: появился новый коммит — тянет и перезапускается.
    Так изменения долетают сами, без ручного /update."""
    d = os.path.dirname(os.path.abspath(__file__))
    try:
        sha = _remote_sha()
    except Exception:
        return  # сети нет — молча ждём следующего тика
    cur = None
    if os.path.exists(_SHA_FILE):
        try:
            with open(_SHA_FILE) as f:
                cur = f.read().strip()
        except Exception:
            cur = None
    if cur is None:
        # первый запуск — фиксируем базовую точку, без перезапуска
        try:
            with open(_SHA_FILE, "w") as f:
                f.write(sha)
        except Exception:
            pass
        return
    if sha == cur:
        return  # ничего нового
    # есть свежий коммит — обновляемся
    try:
        _download_code(d, sha)
        with open(_SHA_FILE, "w") as f:
            f.write(sha)
    except Exception as e:
        log.error(f"auto-update failed: {e}")
        # Битый/недоступный деплой: работаем на прежней версии, владельцу — один
        # пинг на каждый SHA (ретраи каждые 15 мин продолжаются молча)
        if _claim_daily("deploy_fail:" + sha[:7]):
            cid = get_chat_id()
            if cid:
                try:
                    await ctx.bot.send_message(
                        cid, f"⚠️ Деплой {sha[:7]} отбит: {str(e)[:200]}\n"
                             "Работаю на прежней версии, попробую снова через 15 минут.")
                except Exception:
                    pass
        return
    cid = get_chat_id()
    if cid:
        try:
            await ctx.bot.send_message(
                cid, f"🔄 Новая версия ({sha[:7]}) — обновляюсь автоматически…")
        except Exception:
            pass
    try:
        _restart_dashboard(d)
        _restart_dashboard_mac(d)
        await asyncio.sleep(1.5)
    except Exception:
        pass
    _self_restart(d)
    os._exit(0)


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ctx.job_queue.run_daily(
        morning_digest,
        time=time(8, 0),
        chat_id=chat_id,
        name=f"digest_{chat_id}"
    )
    await update.message.reply_text("✅ Буду присылать утренний дайджест в 08:00 каждый день!")


# ─── одноразовая ревизия данных 09.07.2026 ────────────────────────────────────
# Чистка тестовых карточек + импорт Trello-досок, долгов и Klarna по скриншотам
# владельца. Перед изменениями БД копируется в friedman_backup_import.db;
# откат — командой /rollback_import. Выполняется один раз (флаг в settings).

def run_data_import_20260709():
    if _settings_get("import_20260709"):
        return
    import shutil
    d = os.path.dirname(os.path.abspath(__file__))
    bak = os.path.join(d, "friedman_backup_import.db")
    if not os.path.exists(bak):
        shutil.copy2(DB, bak)

    with db() as conn:
        # 1) тестовые карточки: chaos + их события, канбан-мусор, дубль Book 3.0
        conn.execute("DELETE FROM chaos WHERE id IN (18,36,47,78,80,83,85,86)")
        # прошедшие события возвращаем на парковку (chaos остаётся), отпуск закрываем
        conn.execute("DELETE FROM events WHERE id IN (3,4,5,26,27,28,29,31,32,33,34,35,36,38,39)")
        conn.execute("UPDATE chaos SET done=1 WHERE id IN (76,77)")
        # Мируна: дедлайн 26.07 — переносим со вчерашнего на 24.07
        conn.execute("UPDATE events SET date='2026-07-24' WHERE id=41")
        conn.execute("DELETE FROM kanban_cards WHERE id IN (7,8,10,13,14,15,16,17,18,19,20,21)")
        conn.execute("DELETE FROM kanban_columns WHERE id IN (5,6,7,8,9,11,12,13)")
        # серии игры со слайдерами счастья — оставляем последний замер каждой серии
        conn.execute("DELETE FROM happiness_log WHERE (id BETWEEN 86 AND 102) "
                     "OR id IN (104,105,106,107,112,113,114,115,116)")

        # 2) баланс: карта 850, нал 0 (вводная владельца 09.07)
        for acc, target in (("card", 850.0), ("cash", 0.0)):
            cur = conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS s FROM finance WHERE account=?", (acc,)
            ).fetchone()["s"]
            delta = round(target - cur, 2)
            if abs(delta) >= 0.01:
                conn.execute(
                    "INSERT INTO finance (amount, comment, account) VALUES (?,?,?)",
                    (delta, "коррекция баланса (ревизия 09.07)", acc))

        # 3) долги. Несгораемые (давние) — kind=long; свежие в долларах — kind=current
        for name, total in [("Швея — 5 кг конфет", 10), ("Аренда студии", 180),
                            ("Лариса Грин", 700), ("Балу", 250), ("Дэнис", 3500),
                            ("Олег", 3000), ("Гаврик", 1300), ("Роман", 500),
                            ("Граффити СТО", 587)]:
            conn.execute("INSERT INTO debts (name, kind, total, paid, icon, note) "
                         "VALUES (?,?,?,0,?,?)",
                         (name, "long", total, "🤝", "несгораемый (Trello-таблица)"))
        for name, total in [("Кубэк", 1150), ("Маша", 150), ("Серёга плем", 1220),
                            ("Антон", 1000), ("ЗАеЦь", 316.80), ("Катя США", 100),
                            ("Дядя Лёва", 1500), ("Алексей Херборн", 250), ("Гаврик", 300)]:
            conn.execute("INSERT INTO debts (name, kind, total, paid, icon, note) "
                         "VALUES (?,?,?,0,?,?)",
                         (name + " · $", "current", total, "💵", "свежий, сумма в USD"))
        # Klarna: три активные рассрочки (суммы в €)
        for name, total, paid, monthly, due in [
                ("Klarna · Rex (#2026-H2199)", 305.75, 105.68, 52.84, "2026-07-27"),
                ("Klarna · план 12×116,54", 1163.51, 116.54, 116.54, "2026-07-22"),
                ("Klarna · мелкий план", 75.87, 0, 25.30, "2026-08-01")]:
            conn.execute("INSERT INTO debts (name, kind, total, paid, monthly, due_date, icon, note) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (name, "long", total, paid, monthly, due, "🛍",
                          "рассрочка Klarna, Sparkasse ····9122"))
        # ежемесячные платежи Klarna
        for title, amount, day in [("Klarna Rex", 52.84, 27),
                                   ("Klarna план", 116.54, 22),
                                   ("Klarna мелкий", 25.30, 1)]:
            conn.execute("INSERT INTO payments (title, amount, account, kind, recur, day, icon) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (title, amount, "card", "recurring", "monthly", day, "🛍"))
        conn.execute("INSERT INTO reminders (due_at, text) VALUES (?,?)",
                     ("2026-08-02 10:00",
                      "Klarna: проверить, прошёл ли перевыставленный платёж 25,30 € "
                      "(29.06 платёж провалился, перенесён на 01.08)"))

        # 4) проекты из Trello-доски «Проекты» (+3 из «Важно несрочно»)
        trello_projects = [
            ("ZOO", ["Звонок жене фотографа", "Визит в VGF (вместе с Willy Brandt Platz)"]),
            ("ПОЛИГРАФИЯ", ["Книга", "Визитки", "Стикеры"]),
            ("ЕЦБ", ["Печать обновлённой презентации", "Визит к секьюрити"]),
            ("ПОРТРЕТЫ ОУВЕР", ["Инвойс + контракт"]),
            ("SASIS", ["Эскизы"]),
            ("ЕНДЖ", ["Новый эскиз", "Телевизор"]),
            ("МИНИОПЕЛЬ ПАГИ", ["Эскиз"]),
            ("SANKT GEORGEN PARK", ["Фото склейка", "Видео", "Фото на сайт"]),
            ("HERZ", ["Новый эскиз"]),
            ("NEU ISENBURG", ["Дождаться ответа"]),
            ("ОСТХАФЕН", ["Монтагзгезельшафт"]),
            ("ВИЛЛИ БРАНДТ", ["Печать эскизов", "Визит в VGF"]),
            ("ДОМ ЗЁНГЕНА", ["Металл", "Весь дом"]),
            ("PORSCHE", ["Визит"]),
            ("FSV", ["Фото с моста", "Эскизы фаншопов", "Видео с дрона",
                     "По бокам машинкой+валиком 50см", "Лого pad bank arena слева под очки"]),
            ("SIEMENS", ["Контакт Таниэля — связаться", "Посчитать трафик людей"]),
            ("HAIRDRESSER", ["Напомнить Изабэль"]),
            ("CANSATIVA", ["Напомнить о себе осенью"]),
            ("АЙНТРАХТ АНИМЕ КОМНАТА", ["Зимой"]),
            ("BBBANK ARENA", []),
            ("SALVADORE KORRIDORE", []), ("OLDSMOBILE", []), ("LOVEFAMILYPARK", []),
            ("МИКОЛАЇВ ВІДПОЧИВАЄ", []), ("ВОКЗАЛ", []), ("МОСТ", []),
            ("SOUTH BAGS УКРАИНА", [
                "Завершить договор, подписать, отправить другу",
                "Аудит ТМЦ", "Найти формы отчётов, отправить Швее для заполнения",
                "Подбор поставщиков — по 2 на каждый элемент",
                "Рекалькуляция себестоимости", "Инвестпрезентация"]),
            ("МАРКЕТИНГ", [
                "Linkedin — ревизия", "Подстричься", "Обновить книгу (х3 + Вере)",
                "Стенд высокий узкий (6 подпунктов в Trello)", "Банер на loxam",
                "Холсты на мольбертах", "Стол для флёмаркта", "Сине-чёрный BMX с лого",
                "Упоминание среди партнёров", "Логотипы на фасаде",
                "Лого на униформе — футболка х3 и кепка", "Съёмки дроном",
                "Баушильд", "Таблички на ленту оградительную", "Стефан — интервью"]),
            ("ТВОРЧЕСТВО", [
                "Наксос: порисовать граффити шрифт/нешрифт по скетчу",
                "Подарки каллиграфия", "Тэг Slavik can on", "FlippaFlipp logo"]),
        ]
        for pname, psteps in trello_projects:
            cur = conn.execute("INSERT INTO projects (name, area) VALUES (?, 'work')", (pname,))
            pid = cur.lastrowid
            for i, st in enumerate(psteps):
                conn.execute("INSERT INTO steps (project_id, text, done, position) "
                             "VALUES (?,?,0,?)", (pid, st, i))

        # 5) вводные на парковку. «Важно несрочно» → квадрант «запланируй» (7/3)
        base = conn.execute("SELECT COALESCE(MAX(position),0) AS m FROM chaos").fetchone()["m"] + 1
        important = [
            "Письмо Раму в ФШМ — 15 мин",
            "Терморегулятор и герюсте — фото и письмо Роланду — 10 мин",
            "Эскиз Оли", "Память в телефоне и в маке — 2 часа",
            "Название вместо Farbaholix — 1 час",
            "Перевод документов — поиск переводчика — 15 мин",
            "Получить корел и фотошоп", "Письмо в финанцамт — 15 мин",
            "ЕКС себе — 1 час", "Письмо в компас — 15 мин",
            "ЕЦБ Банк эскизы — 3 часа", "Наклейка «нет рекламы» — 10 минут",
            "Paint rests sketch"]
        for i, txt in enumerate(important):
            comment = None
            if txt.startswith("Перевод документов"):
                comment = ("Поиск: свидетельство о рождении — 3 экз. (2×Украина: моё и Маши, "
                           "1×Беларусь: папы); свидетельство о браке СССР (папа-мама); "
                           "военный билет СССР папы. Всего 5 документов.")
            conn.execute("INSERT INTO chaos (text, area, priority, importance, urgency, position, comment) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (txt, "work", "mid", 7, 3, base + i, comment))
        # «Календарь → За ноутом/столом/мобилкой» — задачи за компьютером, без оценки
        base += len(important)
        laptop = [
            "Оправить сообщения (3 подпункта в Trello)", "EBay (1 подпункт в Trello)",
            "Дни рождения (4 подпункта в Trello)", "Спортзалы research",
            "Datacenters карта", "Дата центры", "Концепт линкдин-канала фарбаголикс",
            "Carhartt: деньги + шмотки", "Форма еврейская", "Видео Höll",
            "SGP — обновление эскизов + печать", "Новое приложение ar",
            "Обновить таблицу нетворкинг, включив в неё др.", "Цифровая уборка",
            "Презентации", "Adidas", "Лодки", "Скетч Kiki", "Лого Creactivation",
            "Очистка Farbaholix"]
        for i, txt in enumerate(laptop):
            conn.execute("INSERT INTO chaos (text, area, priority, position) "
                         "VALUES (?,?,?,?)", (txt, "work", "mid", base + i))

        # 6) событие из Trello-колонки «25–26 июля»
        conn.execute("INSERT INTO events (text, date, time, comment) VALUES (?,?,?,?)",
                     ("Марио сцена", "2026-07-25", "", "25–26 июля (из Trello)"))

        conn.execute("INSERT INTO settings (key, value) VALUES ('data_rev','1') "
                     "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")

    _settings_set("import_20260709", "done")
    log.info("ревизия+импорт 09.07 выполнены (бэкап: friedman_backup_import.db)")


def seed_strategic_goals():
    """Одноразовый сид стратегических целей для блока «Мостик» (предложение
    ассистента 09.07 — владелец правит/удаляет прямо в дашборде)."""
    if _settings_get("goals_seed_20260709"):
        return
    with db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(goals)").fetchall()]
        if "progress" not in cols:
            conn.execute("ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0")
        if "target" not in cols:
            conn.execute("ALTER TABLE goals ADD COLUMN target TEXT")
        for text, target, progress in [
                ("Выйти из долгов: закрыть свежие $ и Klarna", "до июн 2027", 10),
                ("Налоговый порядок: декларация 2025 сдана, НДС-2026 разрулен", "до 31 июл 2026", 20),
                ("FARBAHOLIX: 3 якорных клиента и стабильный поток заказов", "до дек 2026", 40),
                ("Издать Книгу 3.0", "до дек 2026", 90),
                ("Построить студию и записать первый трек", "до мар 2027", 5),
                ("Вступить в KSK — снизить страховку", "до окт 2026", 0),
                ("South Bags Украина: запуск продаж", "до ноя 2026", 30)]:
            conn.execute("INSERT INTO goals (text, period, progress, target) VALUES (?,?,?,?)",
                         (text, "strategic", progress, target))
        conn.execute("INSERT INTO settings (key, value) VALUES ('data_rev','1') "
                     "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
    _settings_set("goals_seed_20260709", "done")
    log.info("стратегические цели засеяны")


async def cmd_rollback_import(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Откат ревизии 09.07: вернуть БД из бэкапа и перезапустить всё."""
    chat_id = update.effective_chat.id
    owner = get_chat_id()
    if owner and chat_id != owner:
        return
    import shutil
    d = os.path.dirname(os.path.abspath(__file__))
    bak = os.path.join(d, "friedman_backup_import.db")
    if not os.path.exists(bak):
        await ctx.bot.send_message(chat_id, "⚠️ Бэкап не найден — откатывать нечего.")
        return
    shutil.copy2(bak, DB)
    # ставим флаг в восстановленной БД, чтобы импорт не повторился при рестарте
    _settings_set("import_20260709", "rolled_back")
    await ctx.bot.send_message(chat_id, "↩️ БД восстановлена из бэкапа. Перезапускаюсь…")
    _restart_dashboard(d)
    _restart_dashboard_mac(d)
    _self_restart(d)
    os._exit(0)


# ─── main ─────────────────────────────────────────────────────────────────────

BOT_VERSION = "09.07b"  # видимая метка сборки бота


def _deployed_sha_short():
    """Короткий SHA задеплоенного кода — по нему видно, что реально стоит свежая сборка."""
    try:
        with open(_SHA_FILE) as f:
            return f.read().strip()[:7]
    except Exception:
        return "?"


async def _on_start(app):
    """При запуске бот сам пишет владельцу — так видно, что деплой сработал."""
    try:
        cid = get_chat_id()
        if cid:
            await app.bot.send_message(
                cid,
                f"🚀 Секретарь обновлён и запущен.\n"
                f"Версия: {BOT_VERSION} · сборка {_deployed_sha_short()}\n\n"
                f"Авто-деплой включён: новые изменения подхватываю сам за ~1.5 мин.\n\n"
                f"Команды:\n"
                f"• /ip — ссылка на дашборд\n"
                f"• /brief — сводка сейчас\n"
                f"• /update — обновить всё вручную\n"
                f"• /update_mac — обновить только Mac-дашборд",
            )
    except Exception as e:
        log.error(f"startup notify failed: {e}")


def main():
    if not TOKEN:
        log.error("BOT_TOKEN не задан в .env")
        return

    _kill_other_secretaries()  # вычистить дубли-поллеры от прошлых нечистых рестартов
    init_db()
    try:
        run_data_import_20260709()  # одноразовая ревизия+импорт (флаг в settings)
    except Exception as e:
        log.error(f"data import 09.07: {e}")
    try:
        seed_strategic_goals()
    except Exception as e:
        log.error(f"goals seed: {e}")
    try:
        ensure_legal_kb()  # подтянуть базу знаний Юриста, если её ещё нет на диске
    except Exception as e:
        log.error(f"ensure_legal_kb: {e}")
    try:
        ensure_strategy_kb()  # база знаний стратегического совета
        ensure_sales_kb()  # база знаний Продавца (закрытие сделок)
        ensure_invoices_seed()  # однократно залить исторические счета в архив аналитики
    except Exception as e:
        log.error(f"ensure_strategy_kb: {e}")
    app = Application.builder().token(TOKEN).post_init(_on_start).build()

    # Команды бота сведены к минимуму — только /ip, /brief, /update, /update_mac.
    # /start оставлен как точка входа Telegram (инфраструктура, не фича-команда).
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("ip", cmd_ip))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("update_mac", cmd_update_mac))
    app.add_handler(CommandHandler("rollback_import", cmd_rollback_import))
    app.add_handler(CommandHandler("setjuristtoken", cmd_setjuristtoken))
    app.add_handler(CommandHandler("setsalestoken", cmd_setsalestoken))
    app.add_handler(CommandHandler("setdirectortoken", cmd_setdirectortoken))
    app.add_handler(CommandHandler("setinvoicedata", cmd_setinvoicedata))
    app.add_handler(CommandHandler("wipeinvoicestoday", cmd_wipeinvoicestoday))
    app.add_handler(CommandHandler("juriststatus", cmd_juriststatus))
    app.add_handler(CommandHandler("juristrestart", cmd_juristrestart))

    app.add_handler(CallbackQueryHandler(callback, pattern="^(done:|del:|rezone:|setzone:|list:|bridge:)"))
    app.add_handler(CallbackQueryHandler(extra_callback, pattern="^(newproj|back:|goals_period:|proj:)"))
    app.add_handler(CallbackQueryHandler(doc_callback, pattern=r'^\{"a":\s*"(doc_|img_|klarna_)'))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc_file))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    jq = app.job_queue
    jq.run_repeating(check_reminders, interval=60, first=10)
    jq.run_repeating(auto_update, interval=900, first=60)  # авто-деплой: раз в 15 мин (4 req/h)
    jq.run_repeating(watchdog_children, interval=300, first=120)  # сторож упавших процессов
    backup_t = time(3, 30, tzinfo=BERLIN) if BERLIN else time(3, 30)
    jq.run_daily(nightly_backup, time=backup_t)  # бэкап БД: ротация 7 дн, вс — файл владельцу
    brief_t = time(7, 0, tzinfo=BERLIN) if BERLIN else time(7, 0)
    bridge_t = time(19, 0, tzinfo=BERLIN) if BERLIN else time(19, 0)
    jq.run_daily(morning_focus, time=brief_t)
    jq.run_daily(sunday_bridge, time=bridge_t, days=(6,))

    # Юрист — отдельный бот (jurist_bot.py); поднимаем его, если задан токен
    try:
        _restart_jurist(os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        log.error(f"start jurist: {e}")

    # Продавец — отдельный бот (sales_bot.py); поднимаем его, если задан токен
    try:
        _restart_sales(os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        log.error(f"start sales: {e}")

    # Директор — отдельный бот (director_bot.py); поднимаем его, если задан токен
    try:
        _restart_director(os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        log.error(f"start director: {e}")

    log.info("Секретарь запущен 🗂")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
