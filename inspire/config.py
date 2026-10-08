"""Настройки Inspire. Всё берётся из inspire/.env (см. .env.example)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

DB_PATH = os.environ.get("INSPIRE_DB", os.path.join(HERE, "inspire.db"))
STORAGE = os.environ.get("INSPIRE_STORAGE", os.path.join(HERE, "storage"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Telegram ID руководителя(ей) через запятую — им доступны админ-команды и ежедневная сводка
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
BOT_USERNAME = os.environ.get("BOT_USERNAME", "inspire_dance_bot")

DASH_HOST = os.environ.get("DASH_HOST", "0.0.0.0")
DASH_PORT = int(os.environ.get("DASH_PORT", "8080"))
# Белый список IP/подсетей. Пусто = пускать всех, у кого есть ключ доступа.
DASH_ALLOWED_IPS = [x.strip() for x in os.environ.get("DASH_ALLOWED_IPS", "").split(",") if x.strip()]
# Ключ доступа: http://IP:8080/?key=... — один раз, дальше живёт cookie
DASH_KEY = os.environ.get("DASH_KEY", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://127.0.0.1:{DASH_PORT}")

TIMEZONE = os.environ.get("TIMEZONE", "Europe/Berlin")
DAILY_AT = os.environ.get("DAILY_AT", "08:00")
CURRENCY = os.environ.get("CURRENCY", "€")
COLLECTIVE = os.environ.get("COLLECTIVE", "Inspire")
