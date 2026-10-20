"""
Шифрование секретов клиентов в базе (пароль почты для отправки писем).

Ключ — BACKSTAGE_SECRET в backstage/.env, НЕ в базе: воскресный «сейф» и
ночные копии базы уходят владельцу в Telegram, и пароли клиентов в них должны
оставаться нечитаемыми. Схема на stdlib: поток ключа SHA-256 в режиме счётчика
+ HMAC-SHA256 поверх шифротекста (encrypt-then-MAC), у каждой записи свой nonce.
"""

import base64
import hashlib
import hmac
import os
import secrets

_HERE = os.path.dirname(os.path.abspath(__file__))


def _key():
    k = os.environ.get("BACKSTAGE_SECRET", "")
    if not k:
        # первый запуск: генерируем и дописываем в .env (только для владельца файла)
        k = secrets.token_hex(32)
        path = os.path.join(_HERE, ".env")
        with open(path, "a") as f:
            f.write(f"\nBACKSTAGE_SECRET={k}\n")
        os.chmod(path, 0o600)
        os.environ["BACKSTAGE_SECRET"] = k
    return k.encode()


def _stream(key, nonce, n):
    out, ctr = b"", 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + ctr.to_bytes(8, "big")).digest()
        ctr += 1
    return out[:n]


def encrypt(plain: str) -> str:
    k = _key()
    ke, km = hashlib.sha256(b"enc" + k).digest(), hashlib.sha256(b"mac" + k).digest()
    nonce = secrets.token_bytes(16)
    data = plain.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(ke, nonce, len(data))))
    mac = hmac.new(km, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + ct + mac).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    k = _key()
    ke, km = hashlib.sha256(b"enc" + k).digest(), hashlib.sha256(b"mac" + k).digest()
    raw = base64.b64decode(token)
    nonce, ct, mac = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(mac, hmac.new(km, nonce + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("secret: wrong key or damaged data")
    return bytes(a ^ b for a, b in zip(ct, _stream(ke, nonce, len(ct)))).decode()
