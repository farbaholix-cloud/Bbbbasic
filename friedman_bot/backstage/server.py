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
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import store  # noqa: E402  (после .env — путь к базе может прийти оттуда)
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

PAGES = {"/": "join.html", "/join": "join.html", "/login": "login.html", "/app": "app.html", "/guide": "guide.html", "/admin": "admin.html"}
SIGNUP_DAILY = int(os.environ.get("BACKSTAGE_SIGNUP_DAILY", "30"))   # новых аккаунтов в сутки на всех
SIGNUP_PER_IP = int(os.environ.get("BACKSTAGE_SIGNUP_PER_IP", "3"))   # с одного адреса в сутки
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".webmanifest": "application/manifest+json"}

# ─── Фоновые задачи (ответы команды) ─────────────────────────────────────────

JOBS = {}
_running = {}  # client_id → job_id: один ответ за раз на клиента, чтобы не жечь бюджет дублями
_jobs_lock = threading.Lock()


def start_job(client_id, agent, text, attachments, deep, display=None):
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
            JOBS[jid].update(status="done", result=res)
        except brain.BudgetExceeded as e:
            JOBS[jid].update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 — любую ошибку показываем клиенту, а не роняем поток
            log.exception("chat job failed")
            JOBS[jid].update(status="error", error=f"Ошибка команды: {e}")
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
RESERVED = {"admin", "api", "app", "join", "guide", "static", "canon", "demo", "root", "backstage", "test", "maya"}


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
        secure = "; Secure" if TLS_CERT else ""
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
            raise ValueError("слишком большой запрос (лимит 30 МБ)")
        raw = self.rfile.read(n) if n else b""
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
                    return self._send(429, "Слишком много попыток, подожди 10 минут.", "text/plain; charset=utf-8")
                c = store.client_by_key(m.group(1), (q.get("k") or [""])[0])
                if not c:
                    note_fail(ip)
                    return self._redirect("/login?bad=1")
                tok = store.new_session(c["id"])
                return self._redirect("/app", {"Set-Cookie": self._cookie_header("bs_session", tok)})
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
            if path.startswith("/api/"):
                cid = self._client_id()
                if not cid:
                    return self._err(401, "нужен вход")
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
                    return self._err(401, "нужен вход")
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
        if too_many_fails(ip):
            return self._err(429, "Слишком много попыток, подожди 10 минут.")
        slug = str(body.get("slug", "")).strip().lower()
        if too_many_fails(ip, slug):
            return self._err(429, "Слишком много попыток для этого имени, подожди 15 минут.")
        c = store.client_by_key(slug, str(body.get("key", "")).strip())
        if not c:
            note_fail(ip, slug)
            return self._err(401, "Неверное имя или пин-код")
        tok = store.new_session(c["id"])
        return self._json({"ok": True}, headers={"Set-Cookie": self._cookie_header("bs_session", tok)})

    def signup(self, body):
        """Саморегистрация: бесплатно, с защитой от ботов и от выжигания подписки."""
        ip = self._ip()
        if store.meta_get("signup_open", "1") != "1":
            return self._err(403, "Регистрация сейчас закрыта. Напиши агентству — пришлют приглашение.")
        if str(body.get("website", "")).strip():          # ловушка: поле невидимо для людей
            return self._err(400, "Не получилось, попробуй ещё раз.")
        if not ticket_ok(body.get("ticket")):
            return self._err(400, "Форма устарела или заполнена слишком быстро — обнови страницу.")
        ip_hash = store.hash_key("ip:" + ip)[:16]
        if store.signups_since(24, ip_hash) >= SIGNUP_PER_IP:
            return self._err(429, "С этого устройства сегодня уже регистрировались. Попробуй завтра.")
        if store.signups_since(24) >= SIGNUP_DAILY:
            return self._err(429, "Сегодня места для новых участников закончились — загляни завтра.")
        name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()[:40]
        slug = str(body.get("slug", "")).strip().lower()
        pin = str(body.get("pin", "")).strip()
        craft = str(body.get("craft", "other"))
        craft = craft if craft in brain.CRAFTS else "other"
        about = str(body.get("about", "")).strip()[:1500]
        goal = str(body.get("goal", "")).strip()[:800]
        city = str(body.get("city", "")).strip()[:60]
        links = str(body.get("links", "")).strip()[:300]
        if len(name) < 2:
            raise ValueError("Как тебя зовут? Хотя бы два символа.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,24}", slug) or slug in RESERVED:
            raise ValueError("Имя для входа: 3–25 латинских букв, цифр или дефисов.")
        if not re.fullmatch(r"\d{4,8}", pin) or weak_pin(pin):
            raise ValueError("Пин-код: 4–8 цифр, и не такой простой, как 1234 или 1111.")
        if not body.get("agree"):
            raise ValueError("Нужно согласие на хранение данных.")
        if store.slug_taken(slug):
            raise ValueError("Это имя уже занято — попробуй другое.")
        crafts = brain.CRAFTS
        profile = "\n".join(x for x in [
            f"{name}{', ' + city if city else ''} — {crafts[craft]}.",
            about and f"О себе: {about}", goal and f"Цель на 12 месяцев: {goal}", links and f"Ссылки: {links}"] if x)
        cid, _ = store.create_client(slug, name, profile, budget=0, key=pin, source="signup", craft=craft)
        store.note_signup(ip_hash)
        store.add_message(cid, "maya", "assistant", welcome_text(name, craft, goal))
        tok = store.new_session(cid)
        log.info("signup: %s (%s)", slug, craft)
        # Первый разбор стартует сразу: человек заполнил анкету — и уже видит, как
        # команда работает над ним, а не сталкивается с пустым чатом.
        jid = start_job(cid, "maya", brain.POTENTIAL_PROMPT + "\n\nОбо мне (из анкеты):\n" + profile, [], True,
                        display="🎬 Майя, посмотри мою анкету и сделай первый разбор")
        return self._json({"ok": True, "job": jid}, headers={"Set-Cookie": self._cookie_header("bs_session", tok)})

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
        if path == "/api/me":
            return self._json({
                "name": c["name"], "slug": c["slug"], "profile": c["profile"], "lang": c["lang"],
                "budget": c["monthly_budget"], "spent": round(store.spent_this_month(cid), 4),
                "model_chat": (c["model_chat"] or brain.MODEL_CHAT) if brain.backend() == "api" else f"{brain.CLI_MODEL_CHAT} (подписка)",
                "model_deep": (c["model_deep"] or brain.MODEL_DEEP) if brain.backend() == "api" else f"{brain.CLI_MODEL_DEEP} (подписка)",
                "telegram": bool(c["tg_token"]), "share_insights": c["share_insights"],
                "backend": brain.backend(), "demo": False, "fresh": c.get("source") == "signup",
                "agents": brain.AGENTS, "version": VERSION})
        if path == "/api/widgets":
            ws = store.list_widgets(cid)
            for w in ws:  # системный KPI «Бюджет ИИ» считается сервером
                if w["config"].get("system") == "budget":
                    if brain.backend() == "cli":  # по подписке денег нет — показываем, сколько работала команда
                        n = sum(r["n"] for r in store.usage_summary(cid, days=31))
                        w.update(title="Работа команды", config={**w["config"], "unit": ""})
                        w["data"] = {"value": n, "delta": "запросов за 31 день · по подписке"}
                    else:
                        w["data"] = {"value": round(store.spent_this_month(cid), 2),
                                     "delta": f"из ${c['monthly_budget']:.0f}"}
            return self._json(ws)
        if path == "/api/messages":
            agent = (q.get("agent") or ["maya"])[0]
            return self._json(store.history(cid, agent, limit=100))
        m = re.fullmatch(r"/api/job/([a-f0-9]{12})", path)
        if m:
            j = JOBS.get(m.group(1))
            if not j or j["client_id"] != cid:
                return self._err(404, "задача не найдена")
            return self._json({k: v for k, v in j.items() if k != "client_id"})
        if path == "/api/insights":
            return self._json(store.insights_for(cid, limit=200))
        if path == "/api/usage":
            return self._json(store.usage_summary(cid))
        return self._err(404, "not found")

    def client_post(self, cid, path, body):
        if path == "/api/chat":
            text = str(body.get("text", "")).strip()
            deep = bool(body.get("deep"))
            if body.get("potential"):
                text = brain.POTENTIAL_PROMPT + ("\n\nО себе: " + text if text else "")
                deep = True
            if not text:
                raise ValueError("пустое сообщение")
            atts = []
            for a in (body.get("attachments") or [])[:5]:
                mt = str(a.get("media_type", ""))
                data = str(a.get("data", ""))
                if mt.startswith("text/") or mt in ("application/json", "text/csv"):
                    atts.append({"name": a.get("name", "файл"), "media_type": "text/plain",
                                 "text": base64.b64decode(data).decode("utf-8", "replace")})
                elif mt.startswith("image/") or mt == "application/pdf":
                    atts.append({"name": a.get("name", "файл"), "media_type": mt, "data": data})
            jid = start_job(cid, str(body.get("agent") or "maya"), text, atts, deep)
            if not jid:
                return self._err(409, "Команда ещё отвечает на прошлое сообщение")
            return self._json({"job": jid})
        if path == "/api/messages/clear":
            store.clear_history(cid, str(body.get("agent") or "maya"))
            return self._json({"ok": True})
        if path == "/api/widgets":
            wid = store.add_widget(cid, body.get("kind", "note"), body.get("title") or "Новый виджет",
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
        if path == "/api/profile":
            fields = {k: body[k] for k in ("profile", "lang", "share_insights") if k in body}
            store.update_client(cid, **fields)
            return self._json({"ok": True})
        if path == "/api/telegram":
            tok = str(body.get("token", "")).strip()
            if tok and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", tok):
                raise ValueError("Это не похоже на токен бота от @BotFather")
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
        if path == "/api/admin/config":
            return self._json({"signup_open": store.meta_get("signup_open", "1") == "1",
                               "signups_24h": store.signups_since(24), "signup_daily": SIGNUP_DAILY,"model_chat": brain.MODEL_CHAT, "model_deep": brain.MODEL_DEEP,
                               "effort_chat": brain.EFFORT_CHAT, "effort_deep": brain.EFFORT_DEEP,
                               "prices": brain.PRICES, "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                               "version": VERSION})
        return self._err(404, "not found")

    def admin_post(self, path, body):
        if path == "/api/admin/signup":
            store.meta_set("signup_open", "1" if body.get("open") else "0")
            return self._json({"ok": True})
        if path == "/api/admin/clients":
            slug = str(body.get("slug", "")).strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{2,40}", slug):
                raise ValueError("код клиента: латиница, цифры и дефис, 2–40 символов")
            cid, key = store.create_client(slug, body.get("name") or slug, body.get("profile", ""),
                                           float(body.get("budget") or 20), body.get("lang", "ru"))
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


def welcome_text(name, craft, goal):
    first = name.split()[0]
    hints = {
        "animation": "Например: «найди фестивали анимации и питчинги с дедлайнами на ближайшие полгода» или «помоги посчитать цену за минуту анимации».",
        "illustration": "Например: «где искать заказы на детские книги» или «сколько брать за обложку».",
        "music": "Например: «составь план релиза на месяц» или «найди open calls для музыкантов».",
        "dance": "Например: «найди конкурсы и кастинги на ближайшие месяцы» или «помоги с ценой за постановку номера».",
        "theatre": "Например: «найди фестивали и гранты для независимого театра».",
        "film": "Например: «найди фестивали короткого метра с дедлайнами» или «помоги с бюджетом съёмки».",
        "painting": "Например: «где выставиться в этом году» или «как оценить мои картины».",
        "design": "Например: «помоги с прайсом» или «где искать клиентов».",
        "fashion": "Например: «найди показы и маркеты для молодых дизайнеров».",
        "writing": "Например: «найди конкурсы и издательства для моей рукописи».",
        "mural": "Например: «найди конкурсы на муралы рядом со мной» или «посчитай цену стены 40 м²».",
        "photo": "Например: «где продавать фото» или «помоги с прайсом на съёмку».",
    }.get(craft, "Например: «найди гранты и конкурсы для меня» или «помоги составить прайс».")
    goal_line = f"\n\nТвою цель я записала: «{goal[:160]}». Будем двигаться к ней по шагам." if goal else ""
    return (f"Привет, {first}! Я Майя, твоя продюсерка 🎬\n\n"
            "Теперь у тебя есть команда: Рубен ищет возможности, Ганна пишет заявки, Конрад читает договоры, "
            "Ноа и Тарік продвигают, Ірис планирует контент, Бен считает деньги. Пиши мне — я раздам задачи и сведу ответ."
            f"{goal_line}\n\nЯ уже позвала их на первый разбор твоей анкеты: поищем для тебя возможности в интернете "
            "и наметим первые шаги. Это займёт несколько минут.\n\n"
            "Всё, что мы находим и решаем, само складывается в показатели на вкладке «Дашборд» — "
            f"туда можно просто заглядывать. А работа идёт здесь, в разговоре. {hints}")


def main():
    store.init()
    store.retire_demo()
    if not ADMIN_KEY:
        log.warning("BACKSTAGE_ADMIN_KEY не задан — админка закрыта")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY не задан — команда работает по подписке через claude CLI")
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
