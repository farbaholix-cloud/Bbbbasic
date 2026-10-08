"""Пульт Inspire: веб-дашборд с доступом по IP.

    python dashboard.py      # → http://<IP-сервера>:8080/?key=<DASH_KEY>

Защита (обе включаются в .env):
  DASH_ALLOWED_IPS — белый список IP/подсетей (например 85.12.34.56,10.0.0.0/24). Чужой IP получит 403.
  DASH_KEY         — ключ в ссылке; один раз открыл ссылку с ?key=… — дальше браузер помнит cookie 90 дней.
"""
import hmac
import ipaddress
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
from config import (BOT_TOKEN, BOT_USERNAME, CURRENCY, DASH_ALLOWED_IPS, DASH_HOST, DASH_KEY, DASH_PORT, HERE)

TEMPLATE = os.path.join(HERE, "web", "index.html")
NETS = [ipaddress.ip_network(x, strict=False) for x in DASH_ALLOWED_IPS]


def page(data_json=None):
    """Шаблон + обёртка документа. data_json → статичное демо (без сервера)."""
    body = open(TEMPLATE, encoding="utf-8").read()
    if data_json:
        body = body.replace("/*__DATA__*/", "window.INSPIRE_DATA=" + data_json.replace("</", "<\\/") + ";")
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<link rel="manifest" href="data:application/json,{&quot;name&quot;:&quot;Inspire&quot;,&quot;display&quot;:&quot;standalone&quot;}">'
            '</head><body>' + body + "</body></html>")


def build_data(today=None):
    today = today or date.today()
    t = today.isoformat()
    d30 = (today - timedelta(days=30)).isoformat()
    y0 = (today - timedelta(days=365)).isoformat()
    dancers = db.rows("""SELECT d.id, d.name, d.group_name, d.style, d.level, d.birthday, d.joined_on, d.status,
                           d.monthly_fee, d.tg_id IS NOT NULL AS tg, d.tg_username, d.invite_code, d.phone,
                           (SELECT AVG(a.present)*100 FROM attendance a JOIN rehearsals r ON r.id=a.rehearsal_id
                              WHERE a.dancer_id=d.id AND r.date>=? AND r.date<=?) AS att,
                           (SELECT SUM(fee) FROM assignments s JOIN projects p ON p.id=s.project_id
                              WHERE s.dancer_id=d.id AND s.status='confirmed' AND p.status='выполнен' AND p.date>=?) AS fees_year
                         FROM dancers d ORDER BY d.name""", (d30, t, y0))
    for x in dancers:
        x["tg"] = bool(x["tg"])
    att_m = db.rows("""SELECT substr(r.date,1,7) AS month, AVG(a.present)*100 AS pct FROM attendance a
                       JOIN rehearsals r ON r.id=a.rehearsal_id WHERE r.date<=? GROUP BY month ORDER BY month""", (t,))
    return {
        "today": t, "currency": CURRENCY, "bot_username": BOT_USERNAME,
        "dancers": dancers,
        "clients": db.rows("SELECT id,name,company,kind,phone,email,source,created_on FROM clients"),
        "projects": db.rows("""SELECT p.id,p.title,p.client_id,p.kind,p.date,p.venue,p.status,p.budget,p.dancers_needed,
                                 (SELECT COUNT(*) FROM assignments a WHERE a.project_id=p.id AND a.status IN ('yes','confirmed')) AS ready,
                                 (SELECT COUNT(*) FROM files f WHERE f.project_id=p.id) AS files
                               FROM projects p"""),
        "tx": db.rows("SELECT id,date,amount,direction,category,project_id,client_id,method,note FROM transactions"),
        "comms": db.rows("SELECT id,client_id,project_id,date,channel,direction,summary,next_step,next_date FROM communications"),
        "messages": db.rows("SELECT id,dancer_id,date,direction,text,kind,is_read FROM messages ORDER BY date DESC LIMIT 1500"),
        "attendance_monthly": att_m[-12:],
    }


# ── Telegram из дашборда (ответы и рассылки) ─────────────────────────────────
def tg_send(chat_id, text, poll=None):
    if not BOT_TOKEN or not chat_id:
        return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if poll == "rsvp":
        payload["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": "✅ Буду", "callback_data": "rsvp:yes"}, {"text": "❌ Не буду", "callback_data": "rsvp:no"},
            {"text": "🤔 Пока не знаю", "callback_data": "rsvp:maybe"}]]})
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                 data=urllib.parse.urlencode(payload).encode())
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:  # танцор мог заблокировать бота — не роняем рассылку
        print("tg_send", chat_id, e)
        return False


def now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def handle_post(path, b):
    if path == "/api/tx":
        if b.get("direction") not in ("in", "out") or float(b.get("amount") or 0) <= 0:
            raise ValueError("Укажите тип и сумму больше нуля")
        i = db.execute("INSERT INTO transactions(date,amount,direction,category,project_id,client_id,method,note,created_by)"
                       " VALUES(?,?,?,?,?,?,?,?,'дашборд')",
                       (b["date"], float(b["amount"]), b["direction"], b.get("category"), b.get("project_id"),
                        b.get("client_id"), b.get("method"), b.get("note")))
        return {"ok": True, "id": i}
    if path == "/api/project":
        i = db.execute("INSERT INTO projects(title,client_id,date,venue,status,budget,dancers_needed,created_on)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (b["title"], b.get("client_id"), b["date"], b.get("venue"), b.get("status", "лид"),
                        float(b.get("budget") or 0), int(b.get("dancers_needed") or 0), date.today().isoformat()))
        return {"ok": True, "id": i}
    if path == "/api/client":
        i = db.execute("INSERT INTO clients(name,company,kind,phone,email,source,created_on) VALUES(?,?,?,?,?,?,?)",
                       (b["name"], b.get("company"), b.get("kind"), b.get("phone"), b.get("email"), b.get("source"),
                        date.today().isoformat()))
        return {"ok": True, "id": i}
    if path == "/api/comm":
        i = db.execute("INSERT INTO communications(client_id,date,channel,direction,summary,next_step,next_date)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (b["client_id"], b.get("date") or date.today().isoformat(), b.get("channel"), b.get("direction"),
                        b["summary"], b.get("next_step"), b.get("next_date")))
        return {"ok": True, "id": i}
    if path == "/api/dancer":
        code = db.new_invite_code()
        i = db.execute("INSERT INTO dancers(name,group_name,style,phone,birthday,monthly_fee,joined_on,invite_code)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (b["name"], b.get("group_name"), b.get("style"), b.get("phone"), b.get("birthday"),
                        float(b.get("monthly_fee") or 0), date.today().isoformat(), code))
        return {"ok": True, "id": i, "invite_code": code}
    if path == "/api/reply":
        d = db.one("SELECT tg_id FROM dancers WHERE id=?", (b["dancer_id"],))
        sent = tg_send(d and d["tg_id"], f"💬 <b>Руководитель:</b>\n{b['text']}")
        i = db.execute("INSERT INTO messages(dancer_id,date,direction,text,is_read) VALUES(?,?,'out',?,1)",
                       (b["dancer_id"], now_str(), b["text"]))
        return {"ok": True, "id": i, "sent": sent}
    if path == "/api/read":
        db.execute("UPDATE messages SET is_read=1 WHERE dancer_id=? AND direction='in'", (b["dancer_id"],))
        return {"ok": True}
    if path == "/api/broadcast":
        q = "SELECT tg_id FROM dancers WHERE status='active' AND tg_id IS NOT NULL"
        args = ()
        if b.get("to") and b["to"] != "all":
            q += " AND group_name=?"
            args = (b["to"],)
        n = sum(tg_send(r["tg_id"], f"📣 {b['text']}", b.get("poll")) for r in db.rows(q, args))
        i = db.execute("INSERT INTO messages(dancer_id,date,direction,text,kind,is_read) VALUES(NULL,?,'broadcast',?,'broadcast',1)",
                       (now_str(), b["text"]))
        return {"ok": True, "id": i, "sent": n}
    raise KeyError(path)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def client_ip(self):
        return self.client_address[0]

    def allowed(self):
        if NETS:
            try:
                ip = ipaddress.ip_address(self.client_ip())
            except ValueError:
                return False
            if not any(ip in n for n in NETS):
                return False
        if DASH_KEY:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cookie = self.headers.get("Cookie", "")
            ck = dict(x.strip().split("=", 1) for x in cookie.split(";") if "=" in x).get("inspire_key", "")
            return hmac.compare_digest(ck, DASH_KEY) or hmac.compare_digest(q.get("key", [""])[0], DASH_KEY)
        return True

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed():
            return self.send(403, f"Доступ закрыт для {self.client_ip()}. Попросите руководителя добавить ваш IP "
                                  f"или открыть ссылку с ключом.", "text/plain; charset=utf-8")
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            extra = {"Set-Cookie": f"inspire_key={DASH_KEY}; Max-Age=7776000; HttpOnly; SameSite=Strict; Path=/"} if DASH_KEY else None
            return self.send(200, page(), "text/html; charset=utf-8", extra)
        if path == "/api/data":
            return self.send(200, json.dumps(build_data(), ensure_ascii=False))
        if path == "/summary.jpg":
            import summary
            return self.send(200, open(summary.render_jpeg(), "rb").read(), "image/jpeg")
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.allowed():
            return self.send(403, '{"error":"forbidden"}')
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self.send(200, json.dumps(handle_post(path, body), ensure_ascii=False))
        except KeyError:
            self.send(404, '{"error":"not found"}')
        except Exception as e:
            self.send(400, str(e), "text/plain; charset=utf-8")


def main():
    db.init()
    print(f"Inspire пульт: http://{DASH_HOST}:{DASH_PORT}/" + (f"?key={DASH_KEY}" if DASH_KEY else ""))
    print("Белый список IP:", ", ".join(DASH_ALLOWED_IPS) or "не задан (вход только по ключу)")
    ThreadingHTTPServer((DASH_HOST, DASH_PORT), H).serve_forever()


if __name__ == "__main__":
    main()
