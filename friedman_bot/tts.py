"""Озвучка ответов секретаря (text-to-speech).

Движок выбирается автоматически по доступным ключам/настройкам — от самого
качественного к бесплатному запасному. Так система не зависит от ноутбука:
по умолчанию работает Silero прямо на сервере, без ключей и без интернета
(после первой загрузки модели).

Приоритет:
  1. LAPTOP_TTS_URL      — твой ноутбук в сети (XTTS/своя модель), если поднят
  2. ELEVENLABS_API_KEY  — ElevenLabs, самый живой голос
  3. OPENAI_API_KEY      — OpenAI TTS, очень натуральный
  4. Silero (по умолчанию)— бесплатно, на сервере, без ключей
"""
import os
import re
import json
import tempfile
import subprocess
import urllib.request

_BASE = os.path.dirname(os.path.abspath(__file__))

# ── параметры голоса (можно переопределить в .env) ──────────────────────────
SILERO_SPEAKER = os.getenv("SILERO_SPEAKER", "baya")        # baya/xenia/kseniya/aidar/eugene
OPENAI_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")        # nova/shimmer/alloy/...
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Sarah, multilingual
ELEVEN_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
LAPTOP_TTS_URL = os.getenv("LAPTOP_TTS_URL", "").strip()

_silero_model = None


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def clean_for_speech(text: str, limit: int = 900) -> str:
    """Готовим текст к озвучке: убираем markdown, эмодзи и служебные значки."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)          # блоки кода
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"[*_#>~|]", "", t)                          # markdown-символы
    t = re.sub(r"https?://\S+", "ссылка", t)               # ссылки не читаем
    # выкидываем эмодзи и прочие символы вне основных алфавитов
    t = re.sub(r"[^\w\s.,!?;:%№\"'()\-—…А-Яа-яЁё]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        t = cut.rsplit(".", 1)[0] + "." if "." in cut else cut
    return t


# ── конвертация в OGG/Opus (формат голосовых Telegram) ──────────────────────
def _to_ogg(src_path: str, src_fmt: str):
    """Возвращает (path, is_voice). is_voice=True → можно слать как голосовое."""
    if src_fmt == "ogg":
        return src_path, True
    out = src_path.rsplit(".", 1)[0] + ".ogg"
    try:
        subprocess.run([_ffmpeg(), "-y", "-i", src_path,
                        "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1", out],
                       check=True, capture_output=True)
        return out, True
    except Exception:
        # libopus недоступен — отдаём исходник как обычное аудио
        return src_path, False


# ── движки ───────────────────────────────────────────────────────────────────
def _silero(text: str):
    global _silero_model
    import torch
    import numpy as np
    import wave
    if _silero_model is None:
        torch.set_num_threads(max(1, (os.cpu_count() or 2)))
        _silero_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models", model="silero_tts",
            language="ru", speaker="v4_ru", trust_repo=True)
        _silero_model.to("cpu")
    audio = _silero_model.apply_tts(text=text, speaker=SILERO_SPEAKER, sample_rate=48000)
    pcm = (audio.numpy() * 32767).astype("<i2")
    fd, wav_path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(pcm.tobytes())
    return wav_path, "wav"


def _openai(text: str):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    body = json.dumps({"model": OPENAI_TTS_MODEL, "voice": OPENAI_VOICE,
                       "input": text, "response_format": "opus"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    fd, p = tempfile.mkstemp(suffix=".ogg"); os.close(fd)
    with open(p, "wb") as f:
        f.write(data)
    return p, "ogg"


def _elevenlabs(text: str):
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    body = json.dumps({"text": text, "model_id": ELEVEN_MODEL,
                       "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    fd, p = tempfile.mkstemp(suffix=".mp3"); os.close(fd)
    with open(p, "wb") as f:
        f.write(data)
    return p, "mp3"


def _laptop(text: str):
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(LAPTOP_TTS_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
    suffix = ".ogg" if "ogg" in ctype or "opus" in ctype else \
             ".mp3" if "mpeg" in ctype or "mp3" in ctype else ".wav"
    fd, p = tempfile.mkstemp(suffix=suffix); os.close(fd)
    with open(p, "wb") as f:
        f.write(data)
    return p, suffix.lstrip(".")


def active_backend() -> str:
    if LAPTOP_TTS_URL:
        return "laptop"
    if os.getenv("ELEVENLABS_API_KEY", "").strip():
        return "elevenlabs"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    return "silero"


def synthesize(text: str):
    """Озвучивает текст. Возвращает (path, is_voice) или (None, False).

    is_voice=True  → слать через reply_voice (OGG/Opus, голосовое сообщение)
    is_voice=False → слать через reply_audio (обычное аудио)
    """
    spoken = clean_for_speech(text)
    if not spoken:
        return None, False
    order = []
    if LAPTOP_TTS_URL:
        order.append(_laptop)
    if os.getenv("ELEVENLABS_API_KEY", "").strip():
        order.append(_elevenlabs)
    if os.getenv("OPENAI_API_KEY", "").strip():
        order.append(_openai)
    order.append(_silero)  # бесплатный запасной — всегда в конце
    last_err = None
    for engine in order:
        try:
            path, fmt = engine(spoken)
            return _to_ogg(path, fmt)
        except Exception as e:  # движок недоступен — пробуем следующий
            last_err = e
            continue
    raise RuntimeError(f"все TTS-движки недоступны: {last_err}")
