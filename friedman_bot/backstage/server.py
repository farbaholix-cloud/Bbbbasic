"""
Backstage — шлюз агентства: веб-панель клиентов (дашборд + чат с командой ИИ-агентов),
админка владельца и API. Работает по IP-адресу сервера, без домена. Снаружи
панель открывается через дашборд Фридмана — http://<IP>:8765/bs/… (его порт уже
открыт, dashboard.py проксирует /bs сюда); сам сервер слушает порт 8800:

    http://<IP>:8800/            вход по коду клиента
    http://<IP>:8800/c/<код>?k=<ключ>   персональная ссылка клиента (ставит cookie)
    http://<IP>:8800/app         дашборд и чат клиента
    http://<IP>:8800/guide       инструкция для клиента
    http://<IP>:8800/admin       админка владельца (ключ BACKSTAGE_ADMIN_KEY)

Стек — как у дашборда Фридмана: стандартный ThreadingHTTPServer + SQLite,
без веб-фреймворков. Долгие ответы Claude идут фоновыми задачами: браузер
получает id задачи и опрашивает /api/job/<id>, поэтому мобильный браузер,
свернувший вкладку, не обрывает анализ на полпути.
"""
import os
import re
import ssl
import json
import time
import uuid
import base64
import logging
import threading
import urllib.parse
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import store  # noqa: E402  (после .env — путь к базе может прийти оттуда)
import i18n  # noqa: E402
import plans  # noqa: E402
import proactive  # noqa: E402
import docs  # noqa: E402
import security  # noqa: E402
import secret  # noqa: E402
from i18n import t as T  # noqa: E402
import brain  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backstage")

HOST = os.environ.get("BACKSTAGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("BACKSTAGE_PORT", "8800"))
ADMIN_KEY = os.environ.get("BACKSTAGE_ADMIN_KEY", "")
TLS_CERT = os.environ.get("BACKSTAGE_TLS_CERT", "")
TLS_KEY = os.environ.get("BACKSTAGE_TLS_KEY", "")
STATIC = os.path.join(HERE, "static")
MAX_BODY = 30 * 1024 * 1024  # вложения (PDF договора, фото стены) приходят base64 в JSON
VERSION = "0.1"

PAGES = {"/": "join.html", "/join": "join.html", "/login": "login.html", "/app": "app.html", "/guide": "guide.html", "/admin": "admin.html",
         "/survey": "survey.html", "/workspace": "workspace.html"}
SIGNUP_DAILY = int(os.environ.get("BACKSTAGE_SIGNUP_DAILY", "30"))   # новых аккаунтов в сутки на всех
SIGNUP_PER_IP = int(os.environ.get("BACKSTAGE_SIGNUP_PER_IP", "3"))   # с одного адреса в сутки
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".webmanifest": "application/manifest+json"}

# ─── Фоновые задачи (ответы команды) ─────────────────────────────────────────

JOBS = {}
_running = {}  # client_id → job_id: один ответ за раз на клиента, чтобы не жечь бюджет дублями
_jobs_lock = threading.Lock()


def start_job(client_id, agent, text, attachments, deep, display=None, on_done=None):
    with _jobs_lock:
        busy = _running.get(client_id)
        if busy and JOBS.get(busy, {}).get("status") == "running":
            return None
        jid = uuid.uuid4().hex[:12]
        JOBS[jid] = {"status": "running", "client_id": client_id, "agent": agent, "started": time.time()}
        _running[client_id] = jid

    def work():
        try:
            res = brain.chat(client_id, agent, text, attachments=attachments, deep=deep, display=display)
            if on_done:
                res = on_done(res) or res
            JOBS[jid].update(status="done", result=res)
        except brain.BudgetExceeded as e:
            JOBS[jid].update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 — любую ошибку показываем клиенту, а не роняем поток
            log.exception("chat job failed")
            JOBS[jid].update(status="error", error=T(store.get_client(client_id)["lang"], "team_error", e=e))
        finally:
            # старые задачи чистим, чтобы словарь не рос бесконечно
            cutoff = time.time() - 3600
            for k in [k for k, v in JOBS.items() if v.get("started", 0) < cutoff and v["status"] != "running"]:
                JOBS.pop(k, None)

    threading.Thread(target=work, daemon=True).start()
    return jid


# ─── Защита входа от перебора ────────────────────────────────────────────────

_fails = {}


def too_many_fails(ip, slug=None):
    """10 ошибок с адреса за 10 минут или 6 ошибок по одному имени за 15 минут —
    пауза. Второе важно: пин короткий, и перебирать его можно с разных адресов."""
    now = time.time()
    lst = [t for t in _fails.get(ip, []) if now - t < 600]
    _fails[ip] = lst
    if len(lst) >= 10:
        return True
    if slug:
        sl = [t for t in _fails.get("slug:" + slug, []) if now - t < 900]
        _fails["slug:" + slug] = sl
        return len(sl) >= 6
    return False


def note_fail(ip, slug=None):
    _fails.setdefault(ip, []).append(time.time())
    if slug:
        _fails.setdefault("slug:" + slug, []).append(time.time())


WEAK_PINS = {"1234", "12345", "123456", "1234567", "12345678", "4321", "0123", "1212", "2580", "6969", "1122"}
RESERVED = {"admin", "api", "app", "join", "guide", "static", "canon", "demo", "root", "backstage", "test", "maya", "survey", "workspace", "doc"}


def weak_pin(pin):
    return (pin in WEAK_PINS or len(set(pin)) == 1
            or pin in "0123456789012345" or pin in "9876543210987654")


def _ticket_key():
    k = store.meta_get("signup_key")
    if not k:
        k = __import__("secrets").token_hex(16)
        store.meta_set("signup_key", k)
    return k


def make_ticket():
    import hmac, hashlib
    ts = str(int(time.time()))
    return ts + "." + hmac.new(_ticket_key().encode(), ts.encode(), hashlib.sha256).hexdigest()[:24]


def ticket_ok(t):
    """Билет выдаётся при открытии формы. Регистрация раньше чем через 6 секунд
    (так быстро заполняют только боты) или позже чем через 3 часа — отказ."""
    import hmac, hashlib
    try:
        ts, sig = str(t).split(".", 1)
        good = hmac.new(_ticket_key().encode(), ts.encode(), hashlib.sha256).hexdigest()[:24]
        age = time.time() - int(ts)
        return hmac.compare_digest(sig, good) and 6 <= age <= 3 * 3600
    except Exception:
        return False


# ─── HTTP ────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "Backstage/" + VERSION

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    # — ответы —
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=None):
        self._send(code, obj, headers=headers)

    def _err(self, code, msg):
        self._json({"error": msg}, code)

    def _lang(self, body=None, cid=None):
        """Язык ответа: из запроса, из профиля клиента, из cookie выбора языка; иначе английский."""
        if body and body.get("lang"):
            return i18n.norm(body["lang"])
        if cid:
            c = store.get_client(cid)
            if c:
                return i18n.norm(c["lang"])
        if self._cookies().get("bs_lang"):
            return i18n.norm(self._cookies()["bs_lang"])
        return i18n.DEFAULT

    def _prefix(self):
        # За прокси дашборда (порт 8765, путь /bs) редиректы должны вести на /bs/…
        p = self.headers.get("X-Forwarded-Prefix", "")
        return p if p == "/bs" else ""

    def _redirect(self, to, headers=None):
        self.send_response(302)
        self.send_header("Location", self._prefix() + to)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookie_header(self, name, value, max_age=store.SESSION_DAYS * 86400):
        # Secure — и при своём сертификате, и за HTTPS-прокси (Caddy, nginx, Cloudflare)
        https = TLS_CERT or self.headers.get("X-Forwarded-Proto", "").lower() == "https"
        secure = "; Secure" if https else ""
        return f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def _static(self, fname):
        path = os.path.normpath(os.path.join(STATIC, fname))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._err(404, "not found")
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(path)[1], "application/octet-stream"))

    # — запрос —
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError(T(self._lang(), "too_big"))
        raw = self.rfile.read(n) if n else b""
        self._raw = raw  # вебхуку Stripe нужна подпись по сырому телу
        return json.loads(raw or b"{}")

    def _ip(self):
        """За прокси дашборда (127.0.0.1) — адрес из X-Forwarded-For, иначе прямой."""
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1") and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return ip

    def _cookies(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return {k: v.value for k, v in c.items()}

    def _client_id(self):
        cid = store.session_client(self._cookies().get("bs_session", ""))
        return cid if cid else None  # 0 (админ) клиентом не считается

    def _is_admin(self):
        return store.session_client(self._cookies().get("bs_admin", "")) == 0

    # — маршруты —
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        try:
            if path in PAGES:
                return self._static(PAGES[path])
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            m = re.fullmatch(r"/c/([a-z0-9-]{2,40})", path)
            if m:  # персональная ссылка клиента: /c/<код>?k=<ключ>
                ip = self._ip()
                if too_many_fails(ip):
                    return self._send(429, T(self._lang(), "too_many"), "text/plain; charset=utf-8")
                c = store.client_by_key(m.group(1), (q.get("k") or [""])[0])
                if not c:
                    note_fail(ip)
                    return self._redirect("/login?bad=1")
                tok = store.new_session(c["id"])
                return self._redirect("/app", {"Set-Cookie": self._cookie_header("bs_session", tok)})
            if path == "/api/donate":  # реквизиты «поддержать проект» — публичные, без входа
                d = json.loads(store.meta_get("donate", "") or "{}")
                return self._json({k: d.get(k, "") for k in ("paypal", "holder", "iban", "bic", "bank")})
            if path == "/api/signup/status":
                return self._json({"open": store.meta_get("signup_open", "1") == "1", "ticket": make_ticket()})
            if path == "/api/signup/check":  # свободно ли имя — подсказка прямо в форме
                slug = (q.get("slug") or [""])[0].strip().lower()
                ok = bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{2,24}", slug)) and slug not in RESERVED and not store.slug_taken(slug)
                return self._json({"free": ok})
            if path.startswith("/api/admin/"):
                if not self._is_admin():
                    return self._err(401, "нужен вход владельца")
                return self.admin_get(path, q)
            m = re.fullmatch(r"/doc/(\d+)(\.docx)?", path)
            if m:  # готовый документ: страница для чтения/печати или .docx
                cid = self._client_id()
                if not cid:
                    return self._redirect("/login")
                d = store.get_doc(cid, int(m.group(1)))
                if not d:
                    return self._err(404, "not found")
                fname = re.sub(r"[^\w.-]+", "_", d["title"])[:60] or "document"
                if m.group(2):
                    return self._send(200, docs.to_docx(d["body"]),
                                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                      {"Content-Disposition": f'attachment; filename="{fname}.docx"'})
                L = i18n.norm(store.get_client(cid)["lang"])
                labels = {"en": ("← Workspace", "Download DOCX", "Print / save as PDF"),
                          "de": ("← Arbeitsmappe", "DOCX herunterladen", "Drucken / als PDF speichern"),
                          "ua": ("← Робоча тека", "Завантажити DOCX", "Друк / зберегти як PDF")}[L]
                return self._send(200, docs.to_html(d["title"], d["body"], {"back": labels[0], "download": labels[1],
                                  "print": labels[2], "docx": f"{d['id']}.docx"}), "text/html; charset=utf-8")
            if path.startswith("/api/"):
                cid = self._client_id()
                if not cid:
                    return self._err(401, T(self._lang(), "need_login"))
                return self.client_get(cid, path, q)
            return self._err(404, "not found")
        except Exception as e:  # noqa: BLE001
            log.exception("GET %s", path)
            return self._err(500, str(e))

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._body()
        except Exception as e:  # noqa: BLE001
            return self._err(400, str(e))
        try:
            if path == "/api/login":
                return self.login(body)
            if path == "/api/admin/login":
                return self.admin_login(body)
            if path == "/api/signup":
                return self.signup(body)
            if path == "/api/stripe/webhook":
                return self.stripe_webhook()
            if path == "/api/restart":
                cid = self._client_id()
                if not cid:
                    return self._err(401, T(self._lang(body), "need_login"))
                return self.restart(cid, body)
            if path == "/api/logout":
                for name in ("bs_session", "bs_admin"):
                    store.drop_session(self._cookies().get(name, ""))
                return self._json({"ok": True}, headers={"Set-Cookie": self._cookie_header("bs_session", "", 0)})
            if path.startswith("/api/admin/"):
                if not self._is_admin():
                    return self._err(401, "нужен вход владельца")
                return self.admin_post(path, body)
            if path.startswith("/api/"):
                cid = self._client_id()
                if not cid:
                    return self._err(401, T(self._lang(), "need_login"))
                return self.client_post(cid, path, body)
            return self._err(404, "not found")
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("POST %s", path)
            return self._err(500, str(e))

    # — вход —
    def login(self, body):
        ip = self._ip()
        L = self._lang(body)
        if too_many_fails(ip):
            return self._err(429, T(L, "too_many"))
        slug = str(body.get("slug", "")).strip().lower()
        if too_many_fails(ip, slug):
            return self._err(429, T(L, "too_many_slug"))
        c = store.client_by_key(slug, str(body.get("key", "")).strip())
        if not c:
            note_fail(ip, slug)
            return self._err(401, T(L, "bad_login"))
        tok = store.new_session(c["id"])
        return self._json({"ok": True, "lang": i18n.norm(c["lang"])},
                          headers={"Set-Cookie": self._cookie_header("bs_session", tok)})

    def signup(self, body):
        """Саморегистрация: бесплатно, с защитой от ботов и от выжигания подписки."""
        ip = self._ip()
        L = self._lang(body)
        if store.meta_get("signup_open", "1") != "1":
            return self._err(403, T(L, "signup_closed"))
        if str(body.get("website", "")).strip():          # ловушка: поле невидимо для людей
            return self._err(400, T(L, "try_again"))
        if not ticket_ok(body.get("ticket")):
            return self._err(400, T(L, "form_stale"))
        ip_hash = store.hash_key("ip:" + ip)[:16]
        if store.signups_since(24, ip_hash) >= SIGNUP_PER_IP:
            return self._err(429, T(L, "device_limit"))
        if store.signups_since(24) >= SIGNUP_DAILY:
            return self._err(429, T(L, "daily_full"))
        name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()[:40]
        slug = str(body.get("slug", "")).strip().lower()
        pin = str(body.get("pin", "")).strip()
        picked = pick_crafts(body)
        craft = picked[0]
        goal = str(body.get("goal", "")).strip()[:800]
        if len(name) < 2:
            raise ValueError(T(L, "name_short"))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,24}", slug) or slug in RESERVED:
            raise ValueError(T(L, "slug_bad"))
        if not re.fullmatch(r"\d{4,8}", pin) or weak_pin(pin):
            raise ValueError(T(L, "pin_bad"))
        if not body.get("agree"):
            raise ValueError(T(L, "need_agree"))
        if store.slug_taken(slug):
            raise ValueError(T(L, "slug_taken"))
        profile = build_profile(L, name, picked, body)
        cid, _ = store.create_client(slug, name, profile, budget=0, lang=L, key=pin, source="signup",
                                     craft=",".join(picked))
        store.note_signup(ip_hash)
        store.add_message(cid, "maya", "assistant", i18n.welcome(L, name, craft, goal))
        tok = store.new_session(cid)
        log.info("signup: %s (%s, %s)", slug, ",".join(picked), L)
        # Первый разбор стартует сразу: человек заполнил анкету — и уже видит, как
        # команда работает над ним, а не сталкивается с пустым чатом.
        jid = first_review(cid, L, profile)
        return self._json({"ok": True, "job": jid}, headers={"Set-Cookie": self._cookie_header("bs_session", tok)})

    def restart(self, cid, body):
        """«Начать с нуля» для уже зарегистрированного: та же короткая анкета, без логина и PIN."""
        L = i18n.norm(body.get("lang"))
        if not body.get("confirm"):
            raise ValueError(T(L, "try_again"))
        key = f"restarts:{cid}"
        recent = [x for x in (store.meta_get(key, "") or "").split(",") if x and time.time() - float(x) < 86400]
        if len(recent) >= RESTARTS_PER_DAY:
            return self._err(429, T(L, "restart_limit", n=RESTARTS_PER_DAY))
        busy = _running.get(cid)
        if busy and JOBS.get(busy, {}).get("status") == "running":
            return self._err(409, T(L, "busy"))
        name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()[:40]
        if len(name) < 2:
            raise ValueError(T(L, "name_short"))
        picked = pick_crafts(body)
        profile = build_profile(L, name, picked, body)
        store.restart_client(cid, name, profile, ",".join(picked), L)
        store.meta_set(key, ",".join(recent + [str(time.time())]))
        store.add_message(cid, "maya", "assistant", i18n.welcome(L, name, picked[0], str(body.get("goal", "")).strip()[:800]))
        log.info("restart: client %s (%s, %s)", cid, ",".join(picked), L)
        return self._json({"ok": True, "job": first_review(cid, L, profile)})

    def stripe_webhook(self):
        """Оплата через Stripe Payment Links. Ссылка в приложении несёт client_reference_id
        «код__тариф»; после оплаты включаем тариф на месяц, каждое продление — ещё на месяц.
        Подпись проверяем секретом вебхука (Stripe → Developers → Webhooks)."""
        import hmac, hashlib
        secret = store.meta_get("stripe_webhook_secret", "")
        sig = dict(x.split("=", 1) for x in self.headers.get("Stripe-Signature", "").split(",") if "=" in x)
        if not secret or "t" not in sig:
            return self._err(400, "no signature")
        good = hmac.new(secret.encode(), sig["t"].encode() + b"." + self._raw, hashlib.sha256).hexdigest()
        sigs = [v for k, v in (x.split("=", 1) for x in self.headers["Stripe-Signature"].split(",") if "=" in x) if k == "v1"]
        if not any(hmac.compare_digest(good, v) for v in sigs) or abs(time.time() - int(sig["t"])) > 600:
            return self._err(400, "bad signature")
        ev = json.loads(self._raw)
        obj = (ev.get("data") or {}).get("object") or {}
        if ev.get("type") == "checkout.session.completed":
            slug, _, plan = str(obj.get("client_reference_id") or "").partition("__")
            c = store.client_by_slug(slug) if slug else None
            if c and plan in plans.PAID:
                until = plans.activate(c["id"], plan)
                if obj.get("customer"):
                    store.update_client(c["id"], stripe_customer=obj["customer"])
                log.info("stripe: %s → %s до %s", slug, plan, until)
        elif ev.get("type") == "invoice.paid" and obj.get("customer"):
            c = store.client_by_customer(obj["customer"])
            if c and c.get("plan") in plans.PAID:
                log.info("stripe: продление %s → %s", c["slug"], plans.activate(c["id"], c["plan"]))
        return self._json({"received": True})

    def mail_settings(self, cid, L, body):
        """Подключить почту клиента (SMTP). Перед сохранением — пробный вход, чтобы ошибка
        была видна сразу, а не при первом письме. Пароль хранится зашифрованным."""
        if body.get("delete"):
            store.update_client(cid, mail="")
            return self._json({"ok": True})
        cfg = {k: str(body.get(k) or "").strip() for k in ("host", "port", "security", "user", "password", "from_name", "from_addr")}
        if not cfg["password"]:  # пароль не меняли — берём сохранённый
            cfg["password"] = mail_config(store.get_client(cid)).get("password", "")
        cfg["from_addr"] = cfg["from_addr"] or cfg["user"]
        if not (cfg["host"] and cfg["user"] and cfg["password"] and re.fullmatch(r"[^@\s]+@[^@\s]+", cfg["from_addr"])):
            raise ValueError(T(L, "mail_incomplete"))
        try:
            with smtp_connect(cfg):
                pass
        except Exception as e:  # noqa: BLE001
            return self._err(400, T(L, "mail_login_failed", e=str(e)[:160]))
        store.update_client(cid, mail=secret.encrypt(json.dumps(cfg)))
        return self._json({"ok": True})

    def outbox_action(self, cid, L, eid, action, body):
        e = store.get_email(cid, eid)
        if not e:
            return self._err(404, "not found")
        if e["status"] != "draft":
            return self._json(e)
        edits = {k: str(body[k])[:20000] for k in ("to_addr", "subject", "body") if k in body}
        if edits:
            store.update_email(cid, eid, **edits)
            e.update(edits)
        if action == "/discard":
            store.update_email(cid, eid, status="discarded")
            return self._json({"ok": True})
        if action != "/send":
            return self._json(store.get_email(cid, eid))
        to = [a.strip() for a in re.split(r"[,;]", e["to_addr"]) if a.strip()]
        if not to or len(to) > 3 or not all(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", a, re.I) for a in to):
            raise ValueError(T(L, "mail_bad_to"))
        if store.emails_sent_today(cid) >= MAIL_PER_DAY:
            return self._err(429, T(L, "mail_limit", n=MAIL_PER_DAY))
        cfg = mail_config(store.get_client(cid))
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not cfg or body.get("manual"):
            # почта не подключена — письмо откроется в почтовом приложении клиента
            store.update_email(cid, eid, status="manual", sent_at=now)
            q = urllib.parse.urlencode({"subject": e["subject"], "body": e["body"]}, quote_via=urllib.parse.quote)
            return self._json({"ok": True, "mailto": f"mailto:{','.join(to)}?{q}"})
        from email.message import EmailMessage
        from email.utils import formataddr, make_msgid
        msg = EmailMessage()
        msg["From"] = formataddr((cfg.get("from_name") or "", cfg["from_addr"]))
        msg["To"] = ", ".join(to)
        msg["Subject"] = e["subject"]
        msg["Message-ID"] = make_msgid(domain=cfg["from_addr"].split("@")[-1])
        msg.set_content(e["body"])
        try:
            with smtp_connect(cfg) as s:
                s.send_message(msg)
        except Exception as ex:  # noqa: BLE001
            store.update_email(cid, eid, status="draft", error=str(ex)[:300])
            return self._err(502, T(L, "mail_send_failed", e=str(ex)[:160]))
        store.update_email(cid, eid, status="sent", sent_at=now, error="")
        log.info("mail: client %s → %s", cid, ", ".join(to))
        return self._json({"ok": True, "sent": True})

    def create_doc(self, cid, L, body):
        """Документ по брифу: Ганна (заявки, письма, тексты) или Бен (предложения, сметы).
        Материалы из сейфа идут вложениями; готовый текст сохраняется как документ (DOCX/PDF),
        а в чат — короткая записка со ссылкой, без простыни."""
        kind = body.get("kind") if body.get("kind") in i18n.DOC_KINDS["en"] else "application"
        agent = "ben" if kind in ("offer", "estimate") else "hanna"
        brief = str(body.get("brief", "")).strip()[:3000]
        doc_lang = i18n.LANG_NAME[i18n.norm(body.get("doc_lang") or L)]
        app = next((a for a in store.list_apps(cid) if a["id"] == int(body.get("app_id") or 0)), None)
        if app:
            brief = f"{app['title']} ({app['org']}) {app['url']} deadline {app['deadline']}\n{brief}"
        atts = []
        for fid in (body.get("file_ids") or [])[:4]:
            f = store.get_file(cid, int(fid))
            if not f:
                continue
            if f["text"]:
                atts.append({"name": f["name"], "media_type": "text/plain", "text": f["text"][:15000]})
            elif (f["mime"].startswith("image/") or f["mime"] == "application/pdf") and f["size"] < 5 * 1024 * 1024:
                with open(f["path"], "rb") as fh:
                    atts.append({"name": f["name"], "media_type": f["mime"], "data": base64.b64encode(fh.read()).decode()})
        label = i18n.DOC_KINDS[L][kind]
        task = (f"Prepare a ready-to-send document: {i18n.DOC_KINDS['en'][kind]}.\nBrief: {brief or '(none — use the profile)'}\n"
                "Use the attached materials, the profile and the detailed questionnaire. Never invent facts, numbers or "
                "references: where something is missing, write [TO FILL: what]. "
                f"The document itself must be in {doc_lang}. Reply format: one or two sentences for the client "
                "(in the client's language), then the complete document between a line <<<DOC and a line DOC>>>, "
                "starting with a '# Title' line. Do not change the dashboard.")

        def done(res):
            m = re.search(r"<<<DOC\s*(.*?)\s*DOC>>>", res.get("text") or "", re.S)
            if not m:
                return res
            body_md = m.group(1).strip()
            tm = re.match(r"#\s+(.+)", body_md)
            title = (tm.group(1).strip() if tm else label)[:200]
            did = store.add_doc(cid, title, kind, body_md, app["id"] if app else 0)
            if app and app["status"] == "idea":
                store.save_app(cid, {"id": app["id"], "status": "preparing"})
            note = (res["text"][:m.start()] + res["text"][m.end():]).strip()
            text = (note + "\n\n" if note else "") + T(L, "doc_ready", title=title)
            store.replace_last_answer(cid, agent, text, {"doc_id": did})
            return {**res, "text": text, "doc_id": did}

        jid = start_job(cid, agent, task, atts, bool(body.get("strong")),
                        display=T(L, "doc_request", kind=label, brief=brief[:300]), on_done=done)
        if not jid:
            return self._err(409, T(L, "busy"))
        return self._json({"job": jid, "agent": agent})

    def admin_login(self, body):
        ip = self._ip()
        if too_many_fails(ip):
            return self._err(429, "Слишком много попыток, подожди 10 минут.")
        if not ADMIN_KEY or not __import__("secrets").compare_digest(str(body.get("key", "")), ADMIN_KEY):
            note_fail(ip)
            return self._err(401, "Неверный ключ владельца")
        tok = store.new_session(0)
        return self._json({"ok": True}, headers={"Set-Cookie": self._cookie_header("bs_admin", tok)})

    # — API клиента —
    def client_get(self, cid, path, q):
        c = store.get_client(cid)
        L = i18n.norm(c["lang"])
        if path == "/api/me":
            sub = T(L, "subscription")
            return self._json({
                "name": c["name"], "slug": c["slug"], "profile": c["profile"], "lang": L,
                "budget": c["monthly_budget"], "spent": round(store.spent_this_month(cid), 4),
                "model_chat": (c["model_chat"] or brain.MODEL_CHAT) if brain.backend() == "api" else f"{brain.CLI_MODEL_CHAT} ({sub})",
                "model_deep": (c["model_deep"] or brain.MODEL_DEEP) if brain.backend() == "api" else f"{brain.CLI_MODEL_DEEP} ({sub})",
                "telegram": bool(c["tg_token"]), "share_insights": c["share_insights"],
                "backend": brain.backend(), "demo": False, "fresh": c.get("source") == "signup",
                "agents": i18n.agents(L, brain.AGENTS), "version": VERSION,
                "survey_done": bool(_survey(c).get("done")),
                "plan": plans.status(c), "offers": plans.offers(c), "prefs": proactive.prefs(c),
                "mail": mail_public(c)})
        if path == "/api/survey":
            sv = _survey(c)
            return self._json({"answers": sv.get("answers") or {}, "done": bool(sv.get("done")), "lang": L,
                               "crafts": [x for x in (c.get("craft") or "").split(",") if x]})
        if path == "/api/widgets":
            ws = store.list_widgets(cid)
            for w in ws:  # системный KPI «Бюджет ИИ» считается сервером
                if w["config"].get("system") == "budget":
                    if brain.backend() == "cli":  # по подписке денег нет — показываем, сколько работала команда
                        n = sum(r["n"] for r in store.usage_summary(cid, days=31))
                        w.update(title=T(L, "team_work"), config={**w["config"], "unit": ""})
                        w["data"] = {"value": n, "delta": T(L, "team_work_delta")}
                    else:
                        w["data"] = {"value": round(store.spent_this_month(cid), 2),
                                     "delta": T(L, "budget_of", b=f"{c['monthly_budget']:.0f}")}
            return self._json(ws)
        if path == "/api/messages":
            agent = (q.get("agent") or ["maya"])[0]
            return self._json(store.history(cid, agent, limit=100))
        m = re.fullmatch(r"/api/job/([a-f0-9]{12})", path)
        if m:
            j = JOBS.get(m.group(1))
            if not j or j["client_id"] != cid:
                return self._err(404, T(L, "job_missing"))
            return self._json({k: v for k, v in j.items() if k != "client_id"})
        if path == "/api/insights":
            return self._json(store.insights_for(cid, limit=200))
        if path == "/api/files":
            return self._json({"files": store.list_files(cid), "used": store.files_size(cid), "limit": VAULT_LIMIT})
        m = re.fullmatch(r"/api/files/(\d+)/raw", path)
        if m:
            f = store.get_file(cid, int(m.group(1)))
            if not f or not os.path.exists(f["path"]):
                return self._err(404, "not found")
            safe = re.sub(r"[^\w.-]+", "_", f["name"])  # вне f-строки: обратный слэш в выражении — ошибка до Python 3.12
            with open(f["path"], "rb") as fh:
                return self._send(200, fh.read(), f["mime"] or "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{safe}"'})
        if path == "/api/docs":
            return self._json(store.list_docs(cid))
        if path == "/api/apps":
            return self._json(store.list_apps(cid))
        if path == "/api/outbox":
            return self._json({"emails": store.list_outbox(cid), "mail": mail_public(c)})
        if path == "/api/radar":
            w = next((w for w in store.list_widgets(cid) if w["kind"] == "list" and w["config"].get("radar")), None)
            return self._json([i for i in (w["data"].get("items") if w else []) or [] if not i.get("done")])
        if path == "/api/usage":
            return self._json(store.usage_summary(cid))
        return self._err(404, "not found")

    def client_post(self, cid, path, body):
        L = i18n.norm(store.get_client(cid)["lang"])
        if path == "/api/chat":
            text = str(body.get("text", "")).strip()
            deep = bool(body.get("deep"))
            display = None
            if body.get("potential"):
                display = T(L, "potential") + (": " + text if text else "")
                text = brain.POTENTIAL_PROMPT + ("\n\nAbout me: " + text if text else "")
                deep = True
            if not text:
                raise ValueError(T(L, "empty_msg"))
            atts = []
            for a in (body.get("attachments") or [])[:5]:
                mt = str(a.get("media_type", ""))
                data = str(a.get("data", ""))
                if mt.startswith("text/") or mt in ("application/json", "text/csv"):
                    atts.append({"name": a.get("name", T(L, "file")), "media_type": "text/plain",
                                 "text": base64.b64decode(data).decode("utf-8", "replace")})
                elif mt.startswith("image/") or mt == "application/pdf":
                    atts.append({"name": a.get("name", T(L, "file")), "media_type": mt, "data": data})
            jid = start_job(cid, str(body.get("agent") or "maya"), text, atts, deep, display=display)
            if not jid:
                return self._err(409, T(L, "busy"))
            return self._json({"job": jid})
        if path == "/api/files":
            raw = base64.b64decode(str(body.get("data", "")))
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError(T(L, "too_big_file"))
            if store.files_size(cid) + len(raw) > VAULT_LIMIT:
                raise ValueError(T(L, "vault_full", n=VAULT_LIMIT // 1024 // 1024))
            name = str(body.get("name") or "file")[:160]
            mime = str(body.get("media_type") or "")[:100]
            kind = body.get("kind") if body.get("kind") in FILE_KINDS else "other"
            fid = store.add_file(cid, name, kind, mime, raw, docs.extract_text(name, mime, raw))
            return self._json({"id": fid})
        m = re.fullmatch(r"/api/(files|docs|apps)/(\d+)/delete", path)
        if m:
            {"files": store.delete_file, "docs": store.delete_doc, "apps": store.delete_app}[m.group(1)](cid, int(m.group(2)))
            return self._json({"ok": True})
        if path == "/api/apps":
            return self._json({"id": store.save_app(cid, body)})
        m = re.fullmatch(r"/api/outbox/(\d+)(/send|/discard)?", path)
        if m:
            return self.outbox_action(cid, L, int(m.group(1)), m.group(2), body)
        if path == "/api/mail":
            return self.mail_settings(cid, L, body)
        if path == "/api/docs/create":
            return self.create_doc(cid, L, body)
        if path == "/api/messages/clear":
            store.clear_history(cid, str(body.get("agent") or "maya"))
            return self._json({"ok": True})
        if path == "/api/widgets":
            wid = store.add_widget(cid, body.get("kind", "note"), body.get("title") or T(L, "new_widget"),
                                   body.get("config"), body.get("data"), body.get("size", "m"))
            return self._json(store.get_widget(cid, wid))
        if path == "/api/widgets/reorder":
            store.reorder_widgets(cid, body.get("ids") or [])
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/widgets/(\d+)(/delete)?", path)
        if m:
            wid = int(m.group(1))
            if m.group(2):
                store.delete_widget(cid, wid)
                return self._json({"ok": True})
            return self._json(store.update_widget(cid, wid, body.get("title"), body.get("config"),
                                                  body.get("data"), body.get("size")))
        if path == "/api/survey":
            answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
            if len(json.dumps(answers, ensure_ascii=False)) > 60000:
                raise ValueError("too large")
            store.set_survey(cid, answers, str(body.get("summary", ""))[:4000], bool(body.get("done")))
            return self._json({"ok": True})
        if path == "/api/profile":
            fields = {k: body[k] for k in ("profile", "lang", "share_insights") if k in body}
            if isinstance(body.get("prefs"), dict):
                fields["prefs"] = json.dumps({k: bool(body["prefs"].get(k)) for k in ("radar", "reminders")})
            if "lang" in fields:
                fields["lang"] = i18n.norm(fields["lang"])
                for w in store.list_widgets(cid):
                    upd = i18n.relabel(L, fields["lang"], w)
                    if upd:
                        store.update_widget(cid, w["id"], *upd, None)
            store.update_client(cid, **fields)
            return self._json({"ok": True})
        if path == "/api/telegram":
            tok = str(body.get("token", "")).strip()
            if tok and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", tok):
                raise ValueError(T(L, "bad_tg"))
            store.update_client(cid, tg_token=tok, tg_chat_id="")
            return self._json({"ok": True, "connected": bool(tok)})
        m = re.fullmatch(r"/api/insights/(\d+)/delete", path)
        if m:
            store.delete_insight(int(m.group(1)), client_id=cid)
            return self._json({"ok": True})
        return self._err(404, "not found")

    # — API владельца —
    def admin_get(self, path, q):
        if path == "/api/admin/clients":
            return self._json(store.list_clients())
        if path == "/api/admin/insights":
            return self._json(store.all_insights())
        if path == "/api/admin/usage":
            return self._json(store.usage_summary(None, days=int((q.get("days") or ["31"])[0])))
        if path == "/api/admin/security":
            rows = []
            for c in store.list_clients():
                rep = security.last_report(c)
                if rep.get("site"):
                    rows.append({"client": c["name"], "site": rep["site"], "date": rep.get("date"),
                                 "findings": [i18n.sec_line("ua", f) for f in rep.get("findings", [])]})
            return self._json({"platform": security.platform_audit(), "clients": rows})
        if path == "/api/admin/radar":
            return self._json({"recent": store.recent_opportunities(60), "due": proactive.clusters_due(),
                               "last_day": store.meta_get("proactive_day", "")})
        if path == "/api/admin/config":
            return self._json({"signup_open": store.meta_get("signup_open", "1") == "1",
                               "signups_24h": store.signups_since(24), "signup_daily": SIGNUP_DAILY,"model_chat": brain.MODEL_CHAT, "model_deep": brain.MODEL_DEEP,
                               "effort_chat": brain.EFFORT_CHAT, "effort_deep": brain.EFFORT_DEEP,
                               "prices": brain.PRICES, "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                               "version": VERSION, "plans": plans.get_plans(), "payments_on": plans.payments_on(),
                               "caps": plans.caps(), "tokens_today": store.tokens_today(None),
                               "usd_today": round(store.usd_today(), 2), "backend": brain.backend(),
                               "public_url": store.meta_get("public_url", ""),
                               "stripe_secret_set": bool(store.meta_get("stripe_webhook_secret", ""))})
        return self._err(404, "not found")

    def admin_post(self, path, body):
        if path == "/api/admin/donate":
            d = {k: str(body.get(k) or "").strip()[:200] for k in ("paypal", "holder", "iban", "bic", "bank")}
            if d["paypal"] and not d["paypal"].startswith("https://"):
                d["paypal"] = "https://" + d["paypal"].lstrip("/")
            store.meta_set("donate", json.dumps(d, ensure_ascii=False))
            return self._json({"ok": True})
        if path == "/api/admin/radar/run":
            threading.Thread(target=proactive.daily, kwargs={"force": True}, daemon=True).start()
            return self._json({"ok": True})
        if path == "/api/admin/plans":
            cur = plans.get_plans()
            new = body.get("plans") if isinstance(body.get("plans"), dict) else {}
            keep = {k: {f: v[f] for f in ("name", "price", "link", "days", "chat_daily", "deep_daily", "tokens_daily",
                                         "usd_month") if f in v}
                    for k, v in new.items() if k in cur and isinstance(v, dict)}
            store.meta_set("plans", json.dumps(keep, ensure_ascii=False))
            if isinstance(body.get("caps"), dict):
                store.meta_set("caps", json.dumps({k: float(v) for k, v in body["caps"].items()
                                                   if k in plans.DEFAULT_CAPS and float(v) > 0}))
            if body.get("stripe_secret"):
                store.meta_set("stripe_webhook_secret", str(body["stripe_secret"]).strip())
            return self._json({"ok": True})
        if path == "/api/admin/signup":
            store.meta_set("signup_open", "1" if body.get("open") else "0")
            return self._json({"ok": True})
        if path == "/api/admin/clients":
            slug = str(body.get("slug", "")).strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{2,40}", slug):
                raise ValueError("код клиента: латиница, цифры и дефис, 2–40 символов")
            cid, key = store.create_client(slug, body.get("name") or slug, body.get("profile", ""),
                                           float(body.get("budget") or 20), i18n.norm(body.get("lang", "en")))
            return self._json({"id": cid, "slug": slug, "key": key, "link": f"c/{slug}?k={key}"})
        m = re.fullmatch(r"/api/admin/clients/(\d+)(/reset_key)?", path)
        if m:
            cid = int(m.group(1))
            c = store.get_client(cid)
            if not c:
                return self._err(404, "нет клиента")
            if m.group(2):
                key = store.reset_key(cid)
                return self._json({"key": key, "link": f"c/{c['slug']}?k={key}"})
            store.update_client(cid, **{k: v for k, v in body.items() if k != "tg_token"})
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/admin/insights/(\d+)(/delete)?", path)
        if m:
            iid = int(m.group(1))
            if m.group(2):
                store.delete_insight(iid)
            else:
                store.set_insight_shared(iid, int(bool(body.get("shared"))), body.get("title"), body.get("body"))
            return self._json({"ok": True})
        return self._err(404, "not found")


RESTARTS_PER_DAY = 3
MAIL_PER_DAY = int(os.environ.get("BACKSTAGE_MAIL_PER_DAY", "20"))


def mail_config(c):
    try:
        return json.loads(secret.decrypt(c.get("mail") or "")) if c.get("mail") else {}
    except Exception:
        return {}


def mail_public(c):
    cfg = mail_config(c)
    return {"configured": bool(cfg), "from_addr": cfg.get("from_addr", ""), "from_name": cfg.get("from_name", ""),
            "host": cfg.get("host", ""), "port": cfg.get("port", ""), "security": cfg.get("security", ""),
            "user": cfg.get("user", "")}


def smtp_connect(cfg):
    import smtplib
    port = int(cfg.get("port") or 465)
    if (cfg.get("security") or ("ssl" if port == 465 else "starttls")) == "ssl":
        s = smtplib.SMTP_SSL(cfg["host"], port, timeout=20, context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(cfg["host"], port, timeout=20)
        s.starttls(context=ssl.create_default_context())
    s.login(cfg["user"], cfg["password"])
    return s
VAULT_LIMIT = int(os.environ.get("BACKSTAGE_VAULT_MB", "150")) * 1024 * 1024
FILE_KINDS = ("cv", "portfolio", "statement", "bio", "press", "photo", "video", "other")


def pick_crafts(body):
    """Можно выбрать несколько областей: первая задаёт доску и подсказки, все идут в профиль."""
    raw = body.get("crafts") or [body.get("craft", "other")]
    picked = list(dict.fromkeys(str(c) for c in (raw if isinstance(raw, list) else [raw]) if str(c) in brain.CRAFTS))[:6]
    if len(picked) > 1 and "other" in picked:
        picked.remove("other")
    return picked or ["other"]


def build_profile(L, name, picked, body):
    about = str(body.get("about", "")).strip()[:1500]
    goal = str(body.get("goal", "")).strip()[:800]
    city = str(body.get("city", "")).strip()[:60]
    links = str(body.get("links", "")).strip()[:300]
    crafts = i18n.CRAFTS[L]
    return "\n".join(x for x in [
        f"{name}{', ' + city if city else ''} — {', '.join(crafts[c] for c in picked)}.",
        about and f"{T(L, 'about')}: {about}", goal and f"{T(L, 'goal')}: {goal}",
        links and f"{T(L, 'links')}: {links}"] if x)


def first_review(cid, L, profile):
    return start_job(cid, "maya", brain.POTENTIAL_PROMPT + "\n\nAbout me (from the questionnaire):\n" + profile,
                     [], True, display=T(L, "first_review"))


def _survey(c):
    try:
        return json.loads(c.get("survey") or "{}")
    except Exception:
        return {}


def main():
    store.init()
    store.retire_demo()
    if not ADMIN_KEY:
        log.warning("BACKSTAGE_ADMIN_KEY не задан — админка закрыта")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY не задан — команда работает по подписке через claude CLI")
    proactive.start()  # радар возможностей, подборки и напоминания — фоном, раз в день
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    scheme = "http"
    if TLS_CERT and TLS_KEY:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        scheme = "https"
    log.info("Backstage %s: %s://%s:%s", VERSION, scheme, HOST, PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
