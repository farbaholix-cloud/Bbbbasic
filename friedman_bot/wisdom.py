import os
import json
import time
import random
import subprocess
from datetime import datetime

# Запасная коллекция — только реальные цитаты реальных людей (с авторством)
WISDOM = [
    "План — ничто, планирование — всё. — Дуайт Эйзенхауэр",
    "Дисциплина — мост между целями и достижениями. — Джим Рон",
    "Делай что должен, и будь что будет. — Марк Аврелий",
    "Препятствие на пути становится путём. — Марк Аврелий",
    "Лучший способ предсказать будущее — создать его. — Питер Друкер",
    "То, что измеряется, — управляется. — Питер Друкер",
    "Дорогу осилит идущий. — Луций Анней Сенека",
    "Кто хочет — ищет возможности, кто не хочет — ищет причины. — Сократ",
    "Успех — это сумма небольших усилий, повторяющихся изо дня в день. — Роберт Кольер",
    "Начни с того, что необходимо, потом сделай возможное. — Франциск Ассизский",
    "Качество — это не действие, это привычка. — Аристотель",
    "Мы то, что мы постоянно делаем. — Аристотель",
    "Гений — это один процент вдохновения и девяносто девять процентов пота. — Томас Эдисон",
    "Я не терпел поражений. Я нашёл десять тысяч способов, которые не работают. — Томас Эдисон",
    "Если хочешь идти быстро — иди один, хочешь идти далеко — идите вместе. — африканская пословица",
    "Великие дела совершаются не силой, а упорством. — Сэмюэл Джонсон",
]

_BASE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_BASE, ".wisdom_cache.json")
_TOKEN_FILE = os.path.join(_BASE, ".claude_token")
_CLAUDE = os.path.expanduser("~/.local/bin/claude")

_PROMPT = (
    "Приведи ОДНУ реальную цитату реального известного человека (философа, писателя, "
    "учёного, предпринимателя, художника) на русском — о планировании, дисциплине, "
    "целеустремлённости, фокусе, труде или творчестве. До 20 слов. "
    "ВАЖНО: цитата и автор должны быть подлинными — НЕ выдумывай и НЕ приписывай. "
    "Если не уверен в авторстве — выбери другую, в которой уверен. "
    "Формат строго: «фраза. — Имя Автора». Без вступлений, кавычек и пояснений."
)


def _hour_key() -> str:
    n = datetime.now()
    return f"{n.year}-{n.timetuple().tm_yday}-{n.hour}"


def _generate() -> str:
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "")
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            tok = f.read().strip()
        if tok:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    r = subprocess.run(
        [_CLAUDE, "-p", _PROMPT, "--model", "haiku", "--tools", ""],
        capture_output=True, text=True, timeout=60, env=env,
    )
    text = (r.stdout or "").strip().strip(chr(34)).strip()
    if text and not text.lower().startswith("error") and len(text) < 300:
        return text
    raise RuntimeError("generation failed")


def today_wisdom() -> str:
    key = _hour_key()
    # читаем кэш
    try:
        with open(_CACHE) as f:
            cached = json.load(f)
        if cached.get("key") == key and cached.get("text"):
            return cached["text"]
    except Exception:
        pass
    # генерируем свежую
    try:
        text = _generate()
        with open(_CACHE, "w") as f:
            json.dump({"key": key, "text": text}, f, ensure_ascii=False)
        return text
    except Exception:
        # запасной вариант — из статичного списка, ротация по часу
        n = datetime.now()
        return WISDOM[(n.timetuple().tm_yday * 24 + n.hour) % len(WISDOM)]
