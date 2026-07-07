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
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
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
6в. СЧЕТА (RECHNUNG): «выстави счёт», «сделай инвойс», «Rechnung для X на сумму Y за работу Z» -> action invoice. Извлеки: recipient (получатель: название + адрес, каждая часть с новой строки через \n), items (позиции: desc — описание работы НА НЕМЕЦКОМ профессионально с правильными умляутами ä ö ü ß, напр. «Künstlerische Gestaltung der Fassade ...», price — сумма в евро числом), salutation (обращение если знаешь: «Frau Kluegling» / «Herr Schmidt»), customer_no (если назван). Если не хватает получателя или суммы — спроси одним вопросом, не выдумывай.
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
 {"type": "invoice", "recipient": "Café Sa'Sis\nAdlerstraße 1\n65812 Bad Soden", "items": [{"desc": "Künstlerische Gestaltung der Fassade", "price": 800}], "salutation": "Frau Klügling", "customer_no": ""},
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
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--model", "haiku",
             "--max-turns", "6"],
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
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
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--append-system-prompt", sys_prompt,
             "--model", "haiku",
             "--max-turns", "8",
             "--tools", ""],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        raw = result.stdout.strip()
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

LAWYER_PROMPT = """Ты — «Юрист», личный налогово-правовой консультант Вячеслава (Slavik): украинец в Германии со статусом §24 AufenthG (временная защита), работает как художник-фрилансер (Freiberufler Künstler, бренд FARBAHOLIX), Kleinunternehmer §19 UStG, gesetzlich krankenversichert, в KSK пока не состоит.

ТВОЯ БАЗА ЗНАНИЙ — каталог файлов: {kb}
Там SKILL.md (карта тем) и references/*.md: Freiberufler vs Gewerbe, Kleinunternehmer, ELSTER/EÜR/Steuererklärung, KSK, IHK/Handwerk, Sozialversicherung, письма в инстанции. ВСЕГДА сначала прочитай нужный reference-файл инструментом Read, прежде чем отвечать по теме. Не выдумывай факты, которых там нет.

Контекст §24: украинец на временной защите имеет право на самозанятость (selbständige Erwerbstätigkeit), доступ к gesetzliche Krankenversicherung, может получать Bürgergeld через Jobcenter — доход от самозанятости влияет на эти выплаты (учитывается как Einkommen). Правила §24 и пороги меняются — для актуальных цифр делай web_search, не угадывай.

ТВОИ ЗАДАЧИ:
1. Анализ финансов: тебе дан баланс, счета (Rechnungen) с оборотом по годам, долги, расходы. Оцени налогово-правовую картину, предупреди о рисках: превышение порога Kleinunternehmer (оборот), переквалификация Freiberufler→Gewerbe, обязанность Künstlersozialabgabe как Verwerter при выплатах другим художникам сверх Bagatellgrenze.
2. Сроки: напоминай о подаче деклараций (ESt + Anlage EÜR + Anlage S, обычно к 31 июля) и ежегодных обновлениях. Если просят — поставь напоминание (action remind).
3. Инвойсы: если есть данные для счёта — предложи action invoice (recipient, items на немецком, сумма).
4. Письма/заявления: по reference letters.md составь готовый текст письма на немецком (Finanzamt, KSK, Krankenkasse, Handwerkskammer, Jobcenter) прямо в reply.
5. ELSTER: помоги понять, какие формы (Anlage S, Anlage EÜR), как заполнять, какие поля — пошагово.
6. Статус: рекомендуй изменения (вступление в KSK ради экономии ~50% на страховке, переход на Regelbesteuerung, регистрация Gewerbe/GmbH) — но как ОРИЕНТИР; финальное решение и расчёт — со Steuerberater.

ЖЁСТКИЕ ПРАВИЛА:
- НИКОГДА не вписывай в текст/письма/документы реальные IBAN, BIC, Steuernummer, персональный Steuer-Identifikationsnummer. Если форма требует — оставь плейсхолдер вида [Steuernummer].
- Ты не заменяешь Steuerberater: по решениям с налоговыми последствиями давай механику и пороги, но прямо говори, что финал подтверждает бухгалтер.
- Отвечай по-русски, тепло и конкретно. Тексты писем — на немецком, профессионально, с ä ö ü ß.

Сегодня: {today}.

ВСЕГДА отвечай строго в JSON:
{"reply": "ответ человеку (может содержать текст письма на немецком)", "actions": [
 {"type": "remind", "when": "2026-07-20 09:00", "text": "подать Einkommensteuererklärung"},
 {"type": "invoice", "recipient": "Galerie X\\nStraße 1\\n60311 Frankfurt", "items": [{"desc": "Künstlerische Wandgestaltung", "price": 1200}], "salutation": "", "customer_no": ""},
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
        invoices = conn.execute(
            "SELECT number, COALESCE(date, created_at) AS d, recipient, total, description "
            "FROM invoices ORDER BY d DESC, id DESC LIMIT 25").fetchall()
        debts = conn.execute(
            "SELECT name, kind, total, paid, due_date, monthly FROM debts ORDER BY kind, due_date").fetchall()
        payments = conn.execute(
            "SELECT title, amount, kind, recur, day FROM payments WHERE active=1 ORDER BY kind, day").fetchall()
        history = conn.execute(
            "SELECT role, text FROM messages WHERE text LIKE '⚖%' OR role='lawyer' ORDER BY id DESC LIMIT 8").fetchall()

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

    if history:
        lines.append("\nПОСЛЕДНИЙ ДИАЛОГ С ЮРИСТОМ:")
        for h in reversed(history):
            who = "Человек" if h["role"] == "user" else "Юрист"
            lines.append(f"{who}: {h['text'][:200]}")

    return "\n".join(lines)


def ask_lawyer_sync(user_text: str) -> dict:
    context = get_legal_context()
    prompt = f"{context}\n\nВОПРОС/ЗАПРОС К ЮРИСТУ:\n{user_text}"
    sys_prompt = (LAWYER_PROMPT
                  .replace("{kb}", LEGAL_KB_DIR)
                  .replace("{today}", datetime.now().strftime("%Y-%m-%d %H:%M, %A")))
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--append-system-prompt", sys_prompt,
             "--allowedTools", "Read,WebSearch,WebFetch",
             "--model", "sonnet",
             "--max-turns", "14"],
            capture_output=True, text=True, timeout=240,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        raw = result.stdout.strip()
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
    remember("user", "⚖️ " + user_text)
    wait = await update.message.reply_text("⚖️ Юрист изучает вопрос и сверяется с базой…")

    resp = await asyncio.get_event_loop().run_in_executor(None, lambda: ask_lawyer_sync(user_text))
    reply = resp.get("reply", "") or "Не смог сформулировать ответ — попробуй переформулировать вопрос."
    actions = resp.get("actions", [])
    applied = apply_actions(actions)

    remember("lawyer", "⚖️ " + reply[:400])

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
                if recipient and items:
                    path, total, number = generate_invoice(
                        recipient=recipient, items=items,
                        salutation=a.get("salutation"),
                        customer_no=a.get("customer_no", ""),
                        number=next_invoice_number(),
                    )
                    desc = "; ".join(it.get("desc", "") for it in items)
                    with db() as conn:
                        conn.execute(
                            "INSERT INTO invoices (number, date, recipient, customer_no, description, total, source) "
                            "VALUES (?,?,?,?,?,?, 'bot')",
                            (number, datetime.now().strftime("%d.%m.%Y"),
                             recipient.split(chr(10))[0], a.get("customer_no", ""), desc, total))
                    results.append(("invoice", 0, f"Rechnung {number} · {total:.2f}€", path, ""))
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
        except Exception as e:
            log.error(f"action error: {e}")
    return results


def remember(role: str, text: str):
    with db() as conn:
        conn.execute("INSERT INTO messages (role, text) VALUES (?,?)", (role, text))
        conn.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 50)")


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


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

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
    if re.search(r"(выстав|сдела|выпиш|оформ|подготов)\w*\s+(сч[ёе]т|инвойс|rechnung)", text, re.IGNORECASE) \
       or re.search(r"(сч[ёе]т|инвойс|rechnung)\b.{0,40}(на |для )", text, re.IGNORECASE):
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
                r = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--tools", ""],
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
                )
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


async def create_invoice_from_text(update: Update, text: str):
    await update.message.reply_text("🧾 Готовлю счёт...")

    def extract():
        prompt = (
            "Из сообщения извлеки данные для немецкого счёта (Rechnung). Сообщение: «" + text + "».\n"
            "Описание работы сформулируй НА НЕМЕЦКОМ профессионально, с умляутами ä ö ü ß "
            "(напр. «Künstlerische Gestaltung der Fassade»).\n"
            "Ответь строго JSON без иного текста: {\"recipient\": \"получатель: название и адрес, "
            "каждая часть с новой строки \\n\", \"items\": [{\"desc\": \"работа по-немецки\", "
            "\"price\": 1200}], \"salutation\": \"Frau Müller или Herr Schmidt если известно, иначе пусто\", "
            "\"customer_no\": \"\"}. Если получатель или сумма не названы — верни {\"need\": \"чего не хватает\"}."
        )
        try:
            result = subprocess.run(
                [CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--tools", ""],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
            )
            raw = result.stdout.strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s >= 0 and e > s:
                return jsonlib.loads(raw[s:e+1])
        except Exception as ex:
            log.error(f"invoice extract: {ex}")
        return None

    data = await asyncio.get_event_loop().run_in_executor(None, extract)

    if not data or data.get("need") or not data.get("recipient") or not data.get("items"):
        miss = (data or {}).get("need", "получателя (название, адрес) и сумму")
        await update.message.reply_text(
            f"Чтобы выставить счёт, не хватает: {miss}.\nНапиши, например: "
            "_«счёт Galerie Hertz, Bahnhofstraße 12, 60311 Frankfurt, роспись фасада 1200€»_",
            parse_mode="Markdown")
        return

    from invoice import generate_invoice
    try:
        path, total, number = generate_invoice(
            recipient=data["recipient"], items=data["items"],
            salutation=data.get("salutation") or None,
            customer_no=data.get("customer_no", ""),
            number=next_invoice_number(),
        )
    except Exception as ex:
        log.error(f"invoice gen: {ex}")
        await update.message.reply_text("Не получилось собрать PDF 😔 Проверь данные и попробуй ещё раз.")
        return

    desc = "; ".join(it.get("desc", "") for it in data["items"])
    with db() as conn:
        conn.execute(
            "INSERT INTO invoices (number, date, recipient, customer_no, description, total, source) "
            "VALUES (?,?,?,?,?,?, 'bot')",
            (number, datetime.now().strftime("%d.%m.%Y"),
             data["recipient"].split(chr(10))[0], data.get("customer_no", ""), desc, total))

    remember("user", "счёт: " + text)
    remember("assistant", f"выставлен счёт Rechnung {number} на {total:.2f}€")

    await update.message.reply_text(
        f"🧾 Готово! *Rechnung {number}* на *{total:.2f}€*\nПолучатель: {data['recipient'].split(chr(10))[0]}",
        parse_mode="Markdown")
    try:
        with open(path, "rb") as doc:
            await update.message.reply_document(doc, filename=path.split("/")[-1])
    except Exception as ex:
        log.error(f"invoice send: {ex}")


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
            result = subprocess.run(
                [CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--max-turns", "8", "--tools", ""],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
            )
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
    result = subprocess.run(
        [CLAUDE_BIN, "-p", DOC_PROMPT.format(path=path),
         "--allowedTools", "Read",
         "--model", "sonnet",
         "--max-turns", "5"],
        capture_output=True, text=True, timeout=160,
        env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
    )
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
        result = subprocess.run(
            [CLAUDE_BIN, "-p", CLASSIFY_PROMPT.format(path=path),
             "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "3"],
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
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
    result = subprocess.run(
        [CLAUDE_BIN, "-p", PLANNING_EXTRACT_PROMPT.format(path=path),
         "--allowedTools", "Read", "--model", "haiku", "--max-turns", "3"],
        capture_output=True, text=True, timeout=90,
        env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
    )
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
    result = subprocess.run(
        [CLAUDE_BIN, "-p", KLARNA_PROMPT.format(path=path),
         "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "5"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
    )
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
            result = subprocess.run(
                [CLAUDE_BIN, "-p", WALL_PROMPT.format(path=path),
                 "--allowedTools", "Read", "--model", "sonnet", "--max-turns", "10"],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
            )
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
        try:
            await ctx.bot.send_message(chat_id, f"⏰ Напоминание: *{r['text']}*", parse_mode="Markdown")
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
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--model", "haiku", "--max-turns", "6"],
            capture_output=True, text=True, timeout=110,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        raw = result.stdout.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"culture: {ex}")
    # Фоллбэк без интернета: хотя бы хип-хоп факт из знаний модели
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", "haiku", "--max-turns", "1", "--tools", ""],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        raw = result.stdout.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return jsonlib.loads(raw[s:e + 1])
    except Exception as ex:
        log.error(f"culture fallback: {ex}")
    return {}


async def morning_focus(ctx: ContextTypes.DEFAULT_TYPE, verbose: bool = False):
    chat_id = get_chat_id()
    if not chat_id:
        return
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
        "brief_projs": [(p["name"], int(p["done"]/p["total"]*100) if p["total"] else 0)
                        for p in brief_projs],
        "brief_events": [(e["text"], e["date"], e["time"] or "") for e in brief_events],
        "happiness": happiness,
    }
    img_path = os.path.join(os.path.dirname(__file__), "brief_today.jpg")
    try:
        from brief_render import render_brief_jpeg
        await asyncio.to_thread(render_brief_jpeg, brief_data, img_path)
        with open(img_path, "rb") as f:
            await ctx.bot.send_photo(chat_id, f, caption="☀️ Сводка на сегодня")
        if hap_reminder:
            await ctx.bot.send_message(chat_id, hap_reminder, parse_mode="Markdown")
        return
    except Exception as e:
        log.error(f"morning image failed, fallback to text: {e}")
        if verbose:
            await ctx.bot.send_message(
                chat_id,
                "ℹ️ Постер-картинка не собралась — шлю текстом.\n"
                f"Причина: {type(e).__name__}: {str(e)[:300]}\n\n"
                "Чтобы включить картинку, напиши /setupbrief")

    try:
        await ctx.bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
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


def get_jurist_token() -> str:
    """Токен Юрист-бота: сначала окружение, затем настройка в БД (никогда не в git).
    Чистим любые пробелы/переводы строк — токен их не содержит, а автокоррекция в Telegram
    иногда вставляет пробел внутрь (из-за чего Telegram отвергает токен как невалидный)."""
    raw = os.environ.get("JURIST_BOT_TOKEN") or _settings_get("jurist_bot_token") or ""
    return "".join(raw.split())


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
            try:
                await ctx.bot.send_message(
                    chat_id,
                    f"⚖️ *Юрист напоминает*\n\n📅 *{label}* — срок {dl.strftime('%d.%m.%Y')} ({when}).\n\n{note}",
                    parse_mode="Markdown")
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
UPDATE_FILES = ["bot.py", "jurist_bot.py", "dashboard.py", "brief_render.py", "wisdom.py", "tts.py", "voicelive.py",
                "legal_kb/SKILL.md",
                "legal_kb/references/freiberufler-status.md",
                "legal_kb/references/kleinunternehmer.md",
                "legal_kb/references/elster-steuer.md",
                "legal_kb/references/ksk.md",
                "legal_kb/references/ihk-handwerk.md",
                "legal_kb/references/sozialversicherung.md",
                "legal_kb/references/letters.md"]
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
    """Скачать файлы по неизменяемому SHA — такие URL CDN никогда не отдаёт устаревшими."""
    import urllib.request
    downloaded = []
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
        dest = os.path.join(d, f)
        os.makedirs(os.path.dirname(dest), exist_ok=True)  # подпапки (legal_kb/…) создаём при необходимости
        with open(dest, "wb") as out:
            out.write(data)
        downloaded.append(f)
    return downloaded


def ensure_legal_kb():
    """Самолечение Юриста: если файлы legal_kb или сам jurist_bot.py отсутствуют (первый
    запуск новой версии до того, как авто-деплой подтянет подпапку/файл) — тянем с ветки."""
    import urllib.request
    d = os.path.dirname(os.path.abspath(__file__))
    need = ["jurist_bot.py"] + [x for x in UPDATE_FILES if x.startswith("legal_kb/")]
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


def _restart_dashboard(d):
    """Перезапуск дашборда — освобождаем порт 8765 и поднимаем свежий процесс."""
    import sys
    subprocess.run("pkill -9 -f dashboard.py; fuser -k 8765/tcp 2>/dev/null; true",
                   shell=True)
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
            f"🌐 Дашборд:\nhttp://{ip}:8765\n\nСохрани как PWA в Safari:\n"
            f"Поделиться → На экран «Домой»")
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
        await asyncio.sleep(1.5)
    except Exception as e:
        await ctx.bot.send_message(chat_id, f"⚠️ Дашборд не стартовал: {e}")

    # перезапуск самого бота — заменяем процесс на свежий bot.py
    await ctx.bot.send_message(chat_id, "🚀 Готово! Поднимаюсь на новой версии. "
                                        "Через пару секунд напиши /brief для проверки.")
    _self_restart(d)
    os._exit(0)


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


# ─── main ─────────────────────────────────────────────────────────────────────

BOT_VERSION = "16.06 · 21:30"  # видимая метка сборки бота


async def _on_start(app):
    """При запуске бот сам пишет владельцу — так видно, что деплой сработал."""
    try:
        cid = get_chat_id()
        if cid:
            await app.bot.send_message(
                cid,
                f"🚀 Секретарь обновлён и запущен.\n"
                f"Версия: {BOT_VERSION}\n\n"
                f"Авто-деплой включён: новые изменения подхватываю сам за ~1.5 мин.\n\n"
                f"Команды:\n"
                f"• /ip — ссылка на дашборд\n"
                f"• /brief — сводка сейчас\n"
                f"• /update — обновить вручную прямо сейчас",
            )
    except Exception as e:
        log.error(f"startup notify failed: {e}")


def main():
    if not TOKEN:
        log.error("BOT_TOKEN не задан в .env")
        return

    init_db()
    try:
        ensure_legal_kb()  # подтянуть базу знаний Юриста, если её ещё нет на диске
    except Exception as e:
        log.error(f"ensure_legal_kb: {e}")
    app = Application.builder().token(TOKEN).post_init(_on_start).build()

    # Команды бота сведены к минимуму — только /ip, /brief, /update.
    # /start оставлен как точка входа Telegram (инфраструктура, не фича-команда).
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("ip", cmd_ip))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("setjuristtoken", cmd_setjuristtoken))
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
    brief_t = time(7, 0, tzinfo=BERLIN) if BERLIN else time(7, 0)
    bridge_t = time(19, 0, tzinfo=BERLIN) if BERLIN else time(19, 0)
    jq.run_daily(morning_focus, time=brief_t)
    jq.run_daily(sunday_bridge, time=bridge_t, days=(6,))

    # Юрист — отдельный бот (jurist_bot.py); поднимаем его, если задан токен
    try:
        _restart_jurist(os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        log.error(f"start jurist: {e}")

    log.info("Секретарь запущен 🗂")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
