"""Куда уходит сигнал: Telegram (телефон) и, по желанию, звук в комнате.

Токен берём из того же .env, что и friedman_bot, — второй бот заводить не надо.
Нужны две переменные:

    BOT_TOKEN=123456:AA...        # уже есть у бота Фридмана
    BEDBUG_CHAT_ID=12345678       # твой личный chat_id (у @userinfobot)

Без BEDBUG_CHAT_ID сторож всё равно работает: пишет в журнал и складывает
улики в папку, просто молча. Это нормальный режим на первую ночь настройки.
"""
import os
import mimetypes
import subprocess
import urllib.request
import uuid

_BASE = os.path.dirname(os.path.abspath(__file__))
_API = "https://api.telegram.org/bot{token}/{method}"


def _load_env() -> None:
    """Читаем .env рядом со сторожем, а если его нет — у friedman_bot."""
    for path in (os.path.join(_BASE, ".env"),
                 os.path.join(os.path.dirname(_BASE), "friedman_bot", ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("BEDBUG_CHAT_ID", "").strip()


def configured() -> bool:
    return bool(TOKEN and CHAT_ID)


# ── Telegram ──────────────────────────────────────────────────────────────────

def _multipart(fields: dict, file_field: str = "", file_path: str = "") -> tuple:
    """Собираем multipart/form-data вручную — чтобы не тащить лишних зависимостей."""
    boundary = "----bedbug" + uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                 f"{value}\r\n").encode("utf-8")
    if file_path:
        name = os.path.basename(file_path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(file_path, "rb") as fh:
            blob = fh.read()
        body += (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="{file_field}"; filename="{name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def _call(method: str, fields: dict, file_field: str = "", file_path: str = "") -> bool:
    if not configured():
        return False
    body, ctype = _multipart(fields, file_field, file_path)
    req = urllib.request.Request(
        _API.format(token=TOKEN, method=method), data=body,
        headers={"Content-Type": ctype},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as exc:                      # ночью сеть отваливается — не падаем
        print(f"[alert] Telegram не ответил: {exc}")
        return False


def send_text(text: str) -> bool:
    return _call("sendMessage", {"chat_id": CHAT_ID, "text": text})


def send_photo(path: str, caption: str = "") -> bool:
    return _call("sendPhoto", {"chat_id": CHAT_ID, "caption": caption[:1000]},
                 "photo", path)


def send_video(path: str, caption: str = "") -> bool:
    return _call("sendVideo", {"chat_id": CHAT_ID, "caption": caption[:1000]},
                 "video", path)


# ── звук в комнате ────────────────────────────────────────────────────────────

def beep() -> None:
    """Пищим тем, что есть в системе. Молча пропускаем, если нечем."""
    for cmd in (["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                ["aplay", "-q", "/usr/share/sounds/alsa/Front_Center.wav"],
                ["afplay", "/System/Library/Sounds/Sosumi.aiff"]):
        try:
            subprocess.run(cmd, check=True, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue
    print("\a", end="", flush=True)
