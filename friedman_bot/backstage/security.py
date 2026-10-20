"""
Чак — защитник: регулярные проверки безопасности.

  • check_site — ПАССИВНАЯ проверка сайта клиента (только то, что видит любой
    посетитель): HTTPS и срок сертификата, перенаправление с http, заголовки
    безопасности, раскрытые версии сервера/CMS, SPF и DMARC домена. Никакого
    сканирования портов, перебора и атак — только собственный сайт клиента из профиля.
  • platform_audit — самопроверка Backstage для владельца (админка).
"""

import json
import os
import re
import socket
import ssl
import stat
import time
import urllib.parse
import urllib.request
from datetime import datetime

import store

UA = "Mozilla/5.0 (compatible; BackstageSecurityCheck/1.0; passive)"
SOCIAL = ("instagram.", "facebook.", "behance.", "youtube.", "youtu.be", "tiktok.", "linkedin.", "soundcloud.",
          "spotify.", "vimeo.", "x.com", "twitter.", "t.me", "pinterest.", "artstation.", "bandcamp.", "linktr.ee")


def client_site(c):
    """Собственный сайт клиента: первая ссылка в профиле, которая не соцсеть."""
    for u in re.findall(r"https?://[^\s,;)]+|(?<![@\w])(?:www\.)?[a-z0-9-]+\.[a-z]{2,}(?:/[^\s,;)]*)?", c.get("profile") or "", re.I):
        if not any(s in u.lower() for s in SOCIAL) and "." in u:
            return u if u.startswith("http") else "https://" + u
    return ""


def _dns_txt(name):
    """TXT-записи через DNS-over-HTTPS (stdlib не умеет TXT)."""
    try:
        req = urllib.request.Request(f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(name)}&type=TXT",
                                     headers={"accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return [a.get("data", "").strip('"') for a in data.get("Answer", []) or []]
    except Exception:
        return None


def public_host(host):
    """Сайт из профиля клиента — только публичный адрес: проверка не должна заглядывать внутрь сервера."""
    try:
        import ipaddress
        infos = socket.getaddrinfo(host, None)
        return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except (OSError, ValueError, UnicodeError):
        return False


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_host(urllib.parse.urlparse(newurl).hostname or ""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_site(url):
    """Список находок: [{"sev": "critical|important|later", "code": ..., "detail": ...}]."""
    host = urllib.parse.urlparse(url).hostname or ""
    if not host or not public_host(host):
        return []
    out = []
    add = lambda sev, code, detail="": out.append({"sev": sev, "code": code, "detail": detail})
    # сертификат
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert = s.getpeercert()
        days = int((ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) // 86400)
        if days < 0:
            add("critical", "cert_expired")
        elif days < 14:
            add("important", "cert_soon", str(days))
    except ssl.SSLCertVerificationError:
        add("critical", "cert_invalid")
    except Exception:
        add("critical", "no_https")
    # http → https
    try:
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        op = urllib.request.build_opener(NoRedir)
        try:
            r = op.open(urllib.request.Request(f"http://{host}/", headers={"User-Agent": UA}), timeout=8)
            if r.status == 200:
                add("important", "no_redirect")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308) and not str(e.headers.get("Location", "")).startswith("https://"):
                add("important", "no_redirect")
    except Exception:
        pass
    # заголовки и раскрытые версии
    try:
        req = urllib.request.Request(f"https://{host}/", headers={"User-Agent": UA})
        with urllib.request.build_opener(_PublicRedirects).open(req, timeout=10) as r:
            h = {k.lower(): v for k, v in r.headers.items()}
            body = r.read(200_000).decode("utf-8", "replace")
        if "strict-transport-security" not in h:
            add("later", "no_hsts")
        if "x-frame-options" not in h and "frame-ancestors" not in h.get("content-security-policy", ""):
            add("later", "no_frame")
        if "x-content-type-options" not in h:
            add("later", "no_nosniff")
        srv = h.get("server", "") + " " + h.get("x-powered-by", "")
        if re.search(r"\d+\.\d+", srv):
            add("later", "version_header", srv.strip()[:60])
        gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', body, re.I)
        if gen and re.search(r"\d", gen.group(1)):
            add("important", "cms_version", gen.group(1)[:60])
    except Exception:
        pass
    # почта домена: подделка отправителя
    dom = host[4:] if host.startswith("www.") else host
    txt = _dns_txt(dom)
    if txt is not None and not any(t.lower().startswith("v=spf1") for t in txt):
        add("important", "no_spf")
    dm = _dns_txt("_dmarc." + dom)
    if dm is not None and not any(t.lower().startswith("v=dmarc1") for t in dm):
        add("important", "no_dmarc")
    return out


def run_client(c, force=False):
    """Проверить сайт клиента (не чаще раза в неделю). Возвращает (сайт, находки, новые ли)."""
    site = client_site(c)
    if not site:
        return "", [], False
    key = f"sec:{c['id']}"
    try:
        last = json.loads(store.meta_get(key, "") or "{}")
    except Exception:
        last = {}
    if not force and last.get("site") == site and time.time() - last.get("ts", 0) < 6.5 * 86400:
        return site, last.get("findings", []), False
    findings = check_site(site)
    sig = sorted(f["code"] for f in findings)
    changed = sig != sorted(f["code"] for f in last.get("findings", [])) or last.get("site") != site
    store.meta_set(key, json.dumps({"site": site, "ts": time.time(), "date": datetime.now().strftime("%Y-%m-%d"),
                                    "findings": findings}, ensure_ascii=False))
    return site, findings, changed


def last_report(c):
    try:
        return json.loads(store.meta_get(f"sec:{c['id']}", "") or "{}")
    except Exception:
        return {}


# ─── самопроверка платформы (для владельца) ──────────────────────────────────

def platform_audit():
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    add = lambda sev, text: out.append({"sev": sev, "text": text})
    pub = store.meta_get("public_url", "") or ""
    if not (pub.startswith("https://") or os.environ.get("BACKSTAGE_TLS_CERT")):
        add("critical", "Панель открыта по HTTP: имена, PIN-коды и данные клиентов идут по сети без шифрования. Нужен HTTPS (домен + сертификат или туннель).")
    key = os.environ.get("BACKSTAGE_ADMIN_KEY", "")
    if not key:
        add("important", "Ключ админки не задан — админка закрыта (это безопасно, но ей нельзя пользоваться).")
    elif len(key) < 20:
        add("critical", "Ключ админки короче 20 символов — его можно подобрать. Сгенерируй длинный.")
    for name in (".env", "backstage.db"):
        p = os.path.join(here, name)
        if os.path.exists(p) and os.stat(p).st_mode & (stat.S_IROTH | stat.S_IWOTH):
            add("important", f"Файл {name} читается другими пользователями сервера. Исправить: chmod 600 {name}")
    if store.meta_get("signup_open", "1") == "1" and int(os.environ.get("BACKSTAGE_SIGNUP_DAILY", "30")) > 100:
        add("important", "Открытая регистрация с лимитом больше 100 в сутки — риск наплыва ботов.")
    if not store.meta_get("stripe_webhook_secret", "") and any(
            (v or {}).get("link") for v in json.loads(store.meta_get("plans", "") or "{}").values()):
        add("important", "Ссылки оплаты есть, а секрета вебхука Stripe нет — оплату придётся подтверждать вручную.")
    bdir = os.path.join(os.path.dirname(here), "backups")
    try:
        newest = max((os.path.getmtime(os.path.join(bdir, f)) for f in os.listdir(bdir) if f.startswith("backstage_")), default=0)
    except OSError:
        newest = 0
    if newest and time.time() - newest > 2 * 86400:
        add("important", "Последний бэкап базы клиентов старше двух суток — проверь, работает ли Секретарь.")
    if not newest:
        add("later", "Бэкапов базы Backstage ещё нет (появятся после ближайшего ночного прогона Секретаря).")
    try:
        with store.db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM clients WHERE source='signup' AND created >= datetime('now','-1 day')").fetchone()[0]
        if n >= 25:
            add("important", f"За сутки {n} новых регистраций — проверь, не боты ли (админка → Клиенты).")
    except Exception:
        pass
    if not out:
        add("ok", "Серьёзных проблем не найдено.")
    return out
