"""FARBAHOLIX — бизнес-пульт (отдельный дашборд, порт 8770).

Основной дашборд (dashboard.py, :8765) — про жизнь; этот — про бизнес:
  • Воронка сделок — kanban 🔵 Лид → 🟡 Согласовано → 🟠 Счёт → ✅ Оплачено.
    Сделки = проекты Секретаря (таблица projects, поля expected_income/
    income_status/income_date) — любая правка здесь мгновенно видна во вкладке
    «Проекты» приложения и наоборот. «Оплачено» пишет приход в finance —
    та же семантика, что api_proj_income в dashboard.py.
  • Лиды — доска лидогенерации ВЫШЕ воронки денег (SALES_BOT_SPEC.md, Фаза 2):
    📥 Новый → 📞 Контакт → ✅ Квалифицирован → 📄 Оферта → конвертация в сделку.
    Железное правило activity-based selling: у каждого живого лида — следующее
    касание с датой; просрочка — красным, без next action — жёлтая рамка.
  • Деньги — бизнес-финансы: баланс, обороты по годам (invoice_archive),
    порог §19 (25k€ прошлый год / 100k€ текущий), месяцы, топ-клиенты,
    незакрытые счета.

Замок — тот же жест «обведи точку», сессия и rev-протокол как в dashboard.py.
"""
import json
import math
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, date
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DB = os.path.join(os.path.dirname(__file__), "friedman.db")
PORT = 8770
VERSION = "1.0"

STAGE_W = {"lead": 0.5, "agreed": 0.8, "invoiced": 0.95}


@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_tables():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            channel TEXT DEFAULT 'other',
            city TEXT, object_type TEXT,
            budget_est REAL DEFAULT 0,
            stage TEXT DEFAULT 'new',
            next_action TEXT, next_action_date TEXT,
            touches INTEGER DEFAULT 0,
            notes TEXT, lost_reason TEXT,
            project_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def get_session_token():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM settings WHERE key='bizdash_token'").fetchone()
        if row and row["value"]:
            return row["value"]
        tok = secrets.token_urlsafe(24)
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('bizdash_token', ?)", (tok,))
        return tok


ensure_tables()
SESSION_TOKEN = get_session_token()
IDLE_TIMEOUT = 900
_last_seen = 0.0


def is_circle(points):
    """Замкнутый штрих с ровным радиусом и почти полным оборотом → круг."""
    try:
        pts = [(float(p[0]), float(p[1])) for p in points]
    except Exception:
        return False
    if len(pts) < 20:
        return False
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    rs = [math.hypot(x - cx, y - cy) for x, y in pts]
    rmean = sum(rs) / len(rs)
    if rmean < 25:
        return False
    spread = (sum((r - rmean) ** 2 for r in rs) / len(rs)) ** 0.5
    if spread / rmean > 0.35:
        return False
    if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > rmean:
        return False
    ang, prev = 0.0, math.atan2(pts[0][1] - cy, pts[0][0] - cx)
    for x, y in pts[1:]:
        a = math.atan2(y - cy, x - cx)
        d = a - prev
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        ang += d
        prev = a
    return abs(ang) > 4.6  # ≥ ~265°


def bump_rev():
    """Общий счётчик data_rev — основное приложение подхватит правки воронки сразу."""
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('data_rev','1') "
                     "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")


# ── снимок данных ────────────────────────────────────────────────────────────
def get_data():
    """Снимок данных. Каждая секция — в своём try: отсутствие одной таблицы
    (свежий деплой, старая БД) не должно ронять остальные разделы пульта."""
    today = date.today().isoformat()
    out = {"rev": 0, "today": today,
           "funnel": {"deals": [], "paid": [], "total": 0, "weighted": 0},
           "projects": [], "leads": {"items": [], "lost": []},
           "money": {"balance": 0, "card": 0, "cash": 0, "years": [], "months": [0] * 12,
                     "cur_year": date.today().year, "cur_gross": 0, "prev_gross": 0,
                     "clients": []}}
    with db() as conn:
        try:
            r = conn.execute("SELECT value FROM settings WHERE key='data_rev'").fetchone()
            out["rev"] = int(r["value"]) if r and r["value"] else 0
        except Exception:
            pass

        try:
            pr_cols = [c[1] for c in conn.execute("PRAGMA table_info(projects)").fetchall()]
            if "expected_income" in pr_cols:
                total = weighted = 0.0
                for r in conn.execute(
                        "SELECT id,name,area,expected_income,income_date,income_status "
                        "FROM projects WHERE COALESCE(archived,0)=0 AND COALESCE(expected_income,0)>0 "
                        "ORDER BY CASE COALESCE(income_status,'lead') WHEN 'invoiced' THEN 0 "
                        "WHEN 'agreed' THEN 1 ELSE 2 END, expected_income DESC"):
                    st = r["income_status"] or "lead"
                    amt = r["expected_income"] or 0
                    total += amt
                    weighted += amt * STAGE_W.get(st, 0.5)
                    out["funnel"]["deals"].append({
                        "id": r["id"], "name": r["name"], "area": r["area"],
                        "amount": amt, "date": r["income_date"], "status": st,
                        "overdue": bool(r["income_date"] and r["income_date"] < today)})
                out["funnel"]["total"] = round(total)
                out["funnel"]["weighted"] = round(weighted)
                for r in conn.execute(
                        "SELECT id,name FROM projects WHERE COALESCE(archived,0)=0 "
                        "AND COALESCE(expected_income,0)=0 ORDER BY position, id"):
                    out["projects"].append({"id": r["id"], "name": r["name"]})
        except Exception as e:
            out["error"] = f"funnel: {str(e)[:120]}"

        try:
            for r in conn.execute(
                    "SELECT amount, comment, substr(created_at,1,10) d FROM finance "
                    "WHERE comment LIKE 'оплата проекта:%' AND date(created_at) >= date('now','-90 day') "
                    "ORDER BY created_at DESC LIMIT 30"):
                out["funnel"]["paid"].append({
                    "name": (r["comment"] or "")[16:].strip(), "amount": r["amount"], "date": r["d"]})
        except Exception:
            pass

        try:
            for r in conn.execute(
                    "SELECT * FROM leads WHERE stage IN ('new','contacted','qualified','offer') "
                    "ORDER BY CASE WHEN next_action_date IS NULL THEN 1 ELSE 0 END, "
                    "next_action_date, id DESC"):
                out["leads"]["items"].append({
                    "id": r["id"], "name": r["name"], "channel": r["channel"] or "other",
                    "city": r["city"], "otype": r["object_type"],
                    "budget": r["budget_est"] or 0, "stage": r["stage"],
                    "na": r["next_action"], "nad": r["next_action_date"],
                    "touches": r["touches"] or 0, "notes": r["notes"],
                    "overdue": bool(r["next_action_date"] and r["next_action_date"] < today),
                    "due_today": bool(r["next_action_date"] and r["next_action_date"] <= today)})
            for r in conn.execute(
                    "SELECT name, lost_reason, substr(updated_at,1,10) d FROM leads "
                    "WHERE stage='lost' ORDER BY id DESC LIMIT 15"):
                out["leads"]["lost"].append({"name": r["name"], "reason": r["lost_reason"], "date": r["d"]})
        except Exception as e:
            out["error"] = f"leads: {str(e)[:120]}"

        m = out["money"]
        try:
            bal = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM finance").fetchone()["s"]
            card = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM finance "
                                "WHERE COALESCE(account,'card')='card'").fetchone()["s"]
            m["balance"] = round(bal, 2)
            m["card"] = round(card, 2)
            m["cash"] = round(bal - card, 2)
        except Exception:
            pass
        try:
            m["years"] = [{"year": r["year"], "gross": round(r["s"]), "n": r["n"]}
                          for r in conn.execute(
                              "SELECT year, SUM(COALESCE(gross,0)) s, COUNT(*) n FROM invoice_archive "
                              "WHERE year IS NOT NULL GROUP BY year ORDER BY year")]
            cur_y = m["cur_year"]
            months = [0.0] * 12
            for r in conn.execute(
                    "SELECT strftime('%m', inv_date) mo, SUM(COALESCE(gross,0)) s FROM invoice_archive "
                    "WHERE year=? AND inv_date IS NOT NULL GROUP BY mo", (cur_y,)):
                try:
                    months[int(r["mo"]) - 1] = round(r["s"])
                except (TypeError, ValueError):
                    pass
            m["months"] = months
            m["cur_gross"] = round(sum(months))
            prev = next((y for y in m["years"] if y["year"] == cur_y - 1), None)
            m["prev_gross"] = prev["gross"] if prev else 0
            m["clients"] = [{"name": r["client_name"], "total": round(r["s"]), "n": r["n"]}
                            for r in conn.execute(
                                "SELECT client_name, SUM(COALESCE(gross,0)) s, COUNT(*) n "
                                "FROM invoice_archive WHERE COALESCE(client_name,'')!='' "
                                "GROUP BY client_name ORDER BY s DESC LIMIT 8")]
        except Exception:
            pass
    return out


# ── API: воронка (пишет в projects — синхронно с приложением Секретаря) ──────
def api_deal_add(p):
    name = (p.get("name") or "").strip()
    amount = max(0.0, float(p.get("amount") or 0))
    pid = p.get("project_id")
    with db() as conn:
        if pid:  # привязать сделку к существующему проекту Секретаря
            conn.execute("UPDATE projects SET expected_income=?, income_date=?, "
                         "income_status='lead' WHERE id=?",
                         (amount, (p.get("date") or "").strip() or None, pid))
            return {"ok": True}
        if not name:
            return {"ok": False}
        pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 p FROM projects").fetchone()["p"]
        conn.execute("INSERT INTO projects (name, area, position, expected_income, income_date, income_status) "
                     "VALUES (?,?,?,?,?,'lead')",
                     (name, "work", pos, amount, (p.get("date") or "").strip() or None))
    return {"ok": True}


def api_deal_stage(p):
    """Смена стадии; 'paid' конвертирует сумму в приход finance и обнуляет ожидание —
    в точности как api_proj_income основного дашборда."""
    pid = p["id"]
    status = p.get("status") if p.get("status") in ("lead", "agreed", "invoiced", "paid") else "lead"
    with db() as conn:
        if status == "paid":
            row = conn.execute("SELECT name, expected_income FROM projects WHERE id=?", (pid,)).fetchone()
            amt = float(p.get("amount") if p.get("amount") is not None
                        else (row["expected_income"] if row else 0)) or 0
            if amt > 0:
                acc = p.get("account") if p.get("account") in ("cash", "card") else "card"
                conn.execute("INSERT INTO finance (amount, comment, account) VALUES (?,?,?)",
                             (amt, f"оплата проекта: {row['name'] if row else 'проект'}", acc))
            conn.execute("UPDATE projects SET expected_income=0, income_status='paid' WHERE id=?", (pid,))
        else:
            conn.execute("UPDATE projects SET income_status=? WHERE id=?", (status, pid))
    return {"ok": True}


def api_deal_update(p):
    sets, vals = [], []
    if "amount" in p:
        sets.append("expected_income=?"); vals.append(max(0.0, float(p.get("amount") or 0)))
    if "date" in p:
        sets.append("income_date=?"); vals.append((p.get("date") or "").strip() or None)
    if not sets:
        return {"ok": False}
    with db() as conn:
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", (*vals, p["id"]))
    return {"ok": True}


# ── API: лиды ────────────────────────────────────────────────────────────────
_LEAD_FIELDS = {"name": "name", "channel": "channel", "city": "city",
                "otype": "object_type", "budget": "budget_est", "notes": "notes",
                "na": "next_action", "nad": "next_action_date", "stage": "stage"}


def api_lead_add(p):
    name = (p.get("name") or "").strip()
    if not name:
        return {"ok": False}
    with db() as conn:
        conn.execute("INSERT INTO leads (name, channel, budget_est, next_action, next_action_date, notes) "
                     "VALUES (?,?,?,?,?,?)",
                     (name, (p.get("channel") or "other"), float(p.get("budget") or 0),
                      (p.get("na") or "").strip() or None,
                      (p.get("nad") or "").strip() or None,
                      (p.get("notes") or "").strip() or None))
    return {"ok": True}


def api_lead_update(p):
    sets, vals = [], []
    for k, col in _LEAD_FIELDS.items():
        if k in p:
            v = p.get(k)
            if k == "budget":
                v = float(v or 0)
            elif isinstance(v, str):
                v = v.strip() or None
            sets.append(f"{col}=?"); vals.append(v)
    if not sets:
        return {"ok": False}
    sets.append("updated_at=CURRENT_TIMESTAMP")
    with db() as conn:
        conn.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=?", (*vals, p["id"]))
    return {"ok": True}


def api_lead_touch(p):
    """Касание сделано: счётчик +1 и СРАЗУ назначается следующее (правило доски)."""
    with db() as conn:
        conn.execute("UPDATE leads SET touches=COALESCE(touches,0)+1, next_action=?, "
                     "next_action_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     ((p.get("na") or "").strip() or None,
                      (p.get("nad") or "").strip() or None, p["id"]))
    return {"ok": True}


def api_lead_convert(p):
    """Лид выигран → создаём проект-сделку (появится во вкладке «Проекты» Секретаря)."""
    with db() as conn:
        r = conn.execute("SELECT name, budget_est FROM leads WHERE id=?", (p["id"],)).fetchone()
        if not r:
            return {"ok": False}
        amount = max(0.0, float(p.get("amount") if p.get("amount") is not None else (r["budget_est"] or 0)))
        pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 p FROM projects").fetchone()["p"]
        cur = conn.execute(
            "INSERT INTO projects (name, area, position, expected_income, income_date, income_status) "
            "VALUES (?,?,?,?,?,'lead')",
            (r["name"], "work", pos, amount, (p.get("date") or "").strip() or None))
        conn.execute("UPDATE leads SET stage='won', project_id=?, updated_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", (cur.lastrowid, p["id"]))
    return {"ok": True}


def api_lead_lost(p):
    with db() as conn:
        conn.execute("UPDATE leads SET stage='lost', lost_reason=?, updated_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", ((p.get("reason") or "").strip() or None, p["id"]))
    return {"ok": True}


def api_lead_delete(p):
    with db() as conn:
        conn.execute("DELETE FROM leads WHERE id=?", (p["id"],))
    return {"ok": True}


def _set_session(payload):
    if is_circle((payload or {}).get("points") or []):
        return {"ok": True}
    return {"ok": False}


# ── экран-замок (жест «обведи точку», как в основном дашборде) ───────────────
LOCK_PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>•</title>
<style>
html,body{margin:0;height:100%;background:#000;overflow:hidden;touch-action:none;-webkit-user-select:none;user-select:none}
#dot{position:fixed;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;background:#ffd07a;
  box-shadow:0 0 22px 6px rgba(255,208,122,.4);animation:pulse 2.6s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1);opacity:.8}50%{transform:scale(1.5);opacity:1}}
#cv{position:fixed;inset:0;z-index:2}
#hint{position:fixed;left:0;right:0;bottom:calc(40px + env(safe-area-inset-bottom));text-align:center;
  color:rgba(255,255,255,.18);font-family:-apple-system,sans-serif;font-size:13px;letter-spacing:.5px}
#flash{position:fixed;inset:0;background:#ffd07a;opacity:0;z-index:5;pointer-events:none;transition:opacity .45s}
</style></head><body>
<div id="dot"></div><canvas id="cv"></canvas><div id="hint">обведи точку</div><div id="flash"></div>
<script>
const cv=document.getElementById('cv'),cx=cv.getContext('2d');
function fit(){cv.width=innerWidth*devicePixelRatio;cv.height=innerHeight*devicePixelRatio;
cx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);cx.lineWidth=7;cx.lineCap='round';
cx.strokeStyle='rgba(255,208,122,.85)';cx.shadowColor='rgba(255,208,122,.5)';cx.shadowBlur=12}
fit();addEventListener('resize',fit);
let pts=[],on=false,busy=false;
function xy(e){const t=(e.touches&&e.touches[0])?e.touches[0]:e;return[t.clientX,t.clientY]}
function down(e){if(busy)return;on=true;pts=[xy(e)];cx.clearRect(0,0,innerWidth,innerHeight);
cx.beginPath();cx.moveTo(...pts[0]);e.preventDefault()}
function move(e){if(!on)return;const p=xy(e);pts.push(p);cx.lineTo(...p);cx.stroke();e.preventDefault()}
async function up(){if(!on)return;on=false;if(pts.length<15){fade();return}
busy=true;try{const r=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({points:pts})});const j=await r.json();
if(j.ok){document.getElementById('flash').style.opacity='1';setTimeout(()=>location.reload(),480);return}
}catch(_){}busy=false;fade()}
function fade(){cv.style.transition='opacity .5s';cv.style.opacity='0';
setTimeout(()=>{cx.clearRect(0,0,innerWidth,innerHeight);cv.style.transition='';cv.style.opacity='1'},520)}
addEventListener('mousedown',down);addEventListener('mousemove',move);addEventListener('mouseup',up);
addEventListener('touchstart',down,{passive:false});addEventListener('touchmove',move,{passive:false});
addEventListener('touchend',up);
</script></body></html>"""


# ── страница пульта ──────────────────────────────────────────────────────────
PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>FARBAHOLIX</title>
<style>
:root{--bg:#0b0e14;--card:#151a24;--card2:#1b2130;--tx:#e8edf7;--dim:#8b93a7;--gold:#ffd07a;
--lead:#5b9dff;--agreed:#ffd07a;--invoiced:#ff9f43;--paid:#52e08a;--red:#ff6b7d;--line:#232a3a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--tx);
font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif;overscroll-behavior-y:none}
body{padding-bottom:calc(76px + env(safe-area-inset-bottom))}
header{position:sticky;top:0;z-index:20;background:rgba(11,14,20,.86);backdrop-filter:blur(14px);
padding:calc(10px + env(safe-area-inset-top)) 16px 10px;border-bottom:1px solid var(--line);
display:flex;align-items:baseline;gap:10px}
header b{font-size:17px;letter-spacing:2.5px}
header .biz{color:var(--gold);font-size:10px;font-weight:800;letter-spacing:2px;
border:1px solid rgba(255,208,122,.35);border-radius:6px;padding:2px 6px}
header .v{margin-left:auto;font-size:9px;color:var(--dim);opacity:.5}
.wrap{padding:12px}
.stat{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 12px;flex:1;min-width:100px}
.chip .l{font-size:10px;color:var(--dim);letter-spacing:.4px}
.chip .n{font-size:17px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums}
.board{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;-webkit-overflow-scrolling:touch;
scroll-snap-type:x mandatory}
.col{min-width:236px;max-width:236px;scroll-snap-align:start;background:var(--card);
border:1px solid var(--line);border-radius:14px;padding:10px}
.col h3{margin:0 0 8px;font-size:12px;display:flex;align-items:baseline;gap:6px}
.col h3 .sum{margin-left:auto;font-size:11px;color:var(--dim);font-weight:600}
.cardx{background:var(--card2);border-radius:11px;padding:9px 10px;margin-bottom:8px;border-left:3px solid var(--dim);
cursor:pointer;user-select:none;-webkit-user-select:none}
.cardx .nm{font-size:13.5px;font-weight:700;line-height:1.25}
.cardx .meta{display:flex;gap:8px;margin-top:5px;font-size:11px;color:var(--dim);flex-wrap:wrap;align-items:center}
.cardx .amt{font-weight:800;color:var(--tx);font-variant-numeric:tabular-nums}
.cardx.warn{border:1px solid rgba(255,208,122,.5);border-left-width:3px}
.od{color:var(--red);font-weight:700}
.badge{font-size:10px;border-radius:5px;padding:1px 5px;background:rgba(255,255,255,.07)}
.today{background:linear-gradient(135deg,rgba(255,208,122,.12),rgba(255,159,67,.06));
border:1px solid rgba(255,208,122,.3);border-radius:14px;padding:11px 12px;margin-bottom:12px}
.today h4{margin:0 0 7px;font-size:12px;color:var(--gold);letter-spacing:.5px}
.today .it{display:flex;gap:8px;padding:5px 0;font-size:13px;align-items:baseline;cursor:pointer}
.today .it .d{color:var(--dim);font-size:11px;margin-left:auto;white-space:nowrap}
.addbtn{width:100%;background:var(--card);border:1px dashed #33405a;color:var(--dim);border-radius:12px;
padding:11px;font-size:13px;font-weight:600;margin:2px 0 12px;cursor:pointer}
.form{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:12px;display:none}
.form.open{display:block}
.form input,.form select{width:100%;background:var(--card2);border:1px solid var(--line);border-radius:9px;
color:var(--tx);padding:9px 10px;font-size:14px;margin-bottom:8px;-webkit-appearance:none;appearance:none}
.form .row2{display:flex;gap:8px}.form .row2>*{flex:1}
.btn{background:var(--gold);color:#1a1405;border:none;border-radius:9px;padding:10px 14px;
font-size:13.5px;font-weight:800;cursor:pointer}
.btn.sec{background:var(--card2);color:var(--dim);border:1px solid var(--line)}
.sect{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:12px}
.sect h4{margin:0 0 10px;font-size:12px;color:var(--dim);letter-spacing:.6px}
.bars{display:flex;align-items:flex-end;gap:8px;height:110px}
.bars .b{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;min-width:0}
.bars .bar{width:100%;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,#5b9dff,#3a6fd8);min-height:3px}
.bars .yl{font-size:9.5px;color:var(--dim)}.bars .vl{font-size:9.5px;font-weight:700;white-space:nowrap}
.prog{height:9px;border-radius:5px;background:var(--card2);overflow:hidden;margin:6px 0 3px}
.prog i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#52e08a,#ffd07a)}
.prog.hot i{background:linear-gradient(90deg,#ffd07a,#ff6b7d)}
.rowl{display:flex;gap:8px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px;align-items:baseline}
.rowl:last-child{border-bottom:0}
.rowl .r{margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.muted{color:var(--dim);font-size:11.5px}
nav{position:fixed;left:0;right:0;bottom:0;z-index:30;display:flex;background:rgba(13,17,25,.92);
backdrop-filter:blur(16px);border-top:1px solid var(--line);padding:8px 6px calc(8px + env(safe-area-inset-bottom))}
nav button{flex:1;background:none;border:none;color:var(--dim);font-size:10.5px;font-weight:700;
display:flex;flex-direction:column;gap:3px;align-items:center;cursor:pointer;padding:4px}
nav button span{font-size:20px;filter:grayscale(1);opacity:.6}
nav button.on{color:var(--gold)}nav button.on span{filter:none;opacity:1}
#sheetbg{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:40;display:none}
#sheet{position:fixed;left:0;right:0;bottom:0;z-index:41;background:#161c28;border-radius:18px 18px 0 0;
padding:16px 16px calc(18px + env(safe-area-inset-bottom));display:none;max-height:78vh;overflow-y:auto}
#sheet h3{margin:0 0 4px;font-size:16px}
#sheet .sub{color:var(--dim);font-size:12px;margin-bottom:12px}
#sheet .act{display:block;width:100%;text-align:left;background:var(--card2);border:1px solid var(--line);
color:var(--tx);border-radius:11px;padding:12px;font-size:14px;font-weight:600;margin-bottom:8px;cursor:pointer}
#sheet .act.warn{color:var(--red)}
.tab{display:none}.tab.on{display:block}
.empty{color:var(--dim);font-size:13px;text-align:center;padding:26px 10px}
</style></head><body>
<header><b>FARBAHOLIX</b><span class="biz">БИЗНЕС</span><span class="v">v__VERSION__</span></header>

<div class="tab" id="tab-funnel"><div class="wrap">
  <div class="stat">
    <div class="chip"><div class="l">В воронке</div><div class="n" id="f-total">—</div></div>
    <div class="chip"><div class="l">Взвешенный прогноз</div><div class="n" id="f-w">—</div></div>
    <div class="chip"><div class="l">Оплачено · 90 дн</div><div class="n" id="f-paid">—</div></div>
  </div>
  <button class="addbtn" onclick="toggleForm('dealform')">＋ сделка</button>
  <div class="form" id="dealform">
    <select id="d-proj"><option value="">Новый проект…</option></select>
    <input id="d-name" placeholder="Название (клиент / объект)">
    <div class="row2"><input id="d-amt" type="number" inputmode="decimal" placeholder="Сумма €">
    <input id="d-date" type="date"></div>
    <div class="row2"><button class="btn" onclick="dealAdd()">Добавить</button>
    <button class="btn sec" onclick="toggleForm('dealform')">Отмена</button></div>
    <div class="muted">Сделка появится и во вкладке «Проекты» у Секретаря — это одна база.</div>
  </div>
  <div class="board" id="funnel-board"></div>
</div></div>

<div class="tab" id="tab-leads"><div class="wrap">
  <div class="today" id="today-box" style="display:none"><h4>🔥 КАСАНИЯ СЕГОДНЯ</h4><div id="today-list"></div></div>
  <button class="addbtn" onclick="toggleForm('leadform')">＋ лид</button>
  <div class="form" id="leadform">
    <input id="l-name" placeholder="Кто (кафе, фирма, человек)">
    <div class="row2">
      <select id="l-chan"><option value="referral">🗣 сарафан</option><option value="insta">📸 Instagram</option>
      <option value="google">🌍 Google/сайт</option><option value="partner">🤝 партнёр</option>
      <option value="letter">✉️ письмо</option><option value="visit">🚶 визит</option>
      <option value="tender">🏛 тендер</option><option value="other" selected>📌 другое</option></select>
      <input id="l-budget" type="number" inputmode="decimal" placeholder="Бюджет ~€">
    </div>
    <input id="l-na" placeholder="Следующее действие (напр. позвонить, зайти)">
    <input id="l-nad" type="date">
    <input id="l-notes" placeholder="Заметка (объект, детали)">
    <div class="row2"><button class="btn" onclick="leadAdd()">Добавить</button>
    <button class="btn sec" onclick="toggleForm('leadform')">Отмена</button></div>
  </div>
  <div class="board" id="leads-board"></div>
  <div class="sect" id="lost-box" style="display:none"><h4>❌ ОТКАЗЫ (последние)</h4><div id="lost-list"></div></div>
</div></div>

<div class="tab" id="tab-money"><div class="wrap">
  <div class="stat">
    <div class="chip"><div class="l">Баланс</div><div class="n" id="m-bal">—</div></div>
    <div class="chip"><div class="l">Карта</div><div class="n" id="m-card">—</div></div>
    <div class="chip"><div class="l">Наличные</div><div class="n" id="m-cash">—</div></div>
  </div>
  <div class="sect"><h4>ПОРОГ §19 KLEINUNTERNEHMER</h4>
    <div style="font-size:12.5px" id="th-prev-t"></div><div class="prog" id="th-prev-p"><i></i></div>
    <div class="muted" id="th-prev-m"></div>
    <div style="font-size:12.5px;margin-top:12px" id="th-cur-t"></div><div class="prog" id="th-cur-p"><i></i></div>
    <div class="muted" id="th-cur-m"></div>
  </div>
  <div class="sect"><h4>ОБОРОТ ПО ГОДАМ</h4><div class="bars" id="years-bars"></div></div>
  <div class="sect"><h4 id="mon-title">ПО МЕСЯЦАМ</h4><div class="bars" id="mon-bars" style="height:80px"></div></div>
  <div class="sect"><h4>ОТКРЫТЫЕ СЧЕТА (ждём оплату)</h4><div id="open-inv"></div></div>
  <div class="sect"><h4>ТОП-КЛИЕНТЫ</h4><div id="top-clients"></div></div>
</div></div>

<nav>
  <button id="nb-funnel" onclick="show('funnel')"><span>💰</span>Воронка</button>
  <button id="nb-leads" onclick="show('leads')"><span>🧲</span>Лиды</button>
  <button id="nb-money" onclick="show('money')"><span>📊</span>Деньги</button>
</nav>
<div id="sheetbg" onclick="closeSheet()"></div><div id="sheet"></div>

<script>
window.__INIT__=null;
let S=window.__INIT__||{rev:-1}, applied=-1, tab='funnel';
const eur=n=>new Intl.NumberFormat('de-DE',{maximumFractionDigits:0}).format(Math.round(n||0))+' €';
const CH={referral:'🗣',insta:'📸',google:'🌍',partner:'🤝',letter:'✉️',visit:'🚶',tender:'🏛',other:'📌'};
const FST=[['lead','🔵 Лид','var(--lead)'],['agreed','🟡 Согласовано','var(--agreed)'],
           ['invoiced','🟠 Счёт','var(--invoiced)'],['paid','✅ Оплачено','var(--paid)']];
const LST=[['new','📥 Новые'],['contacted','📞 Контакт'],['qualified','✅ Квалиф.'],['offer','📄 Оферта']];
const $=id=>document.getElementById(id);
const esc=s=>(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function show(t){tab=t;document.querySelectorAll('.tab').forEach(e=>e.classList.remove('on'));
document.querySelectorAll('nav button').forEach(e=>e.classList.remove('on'));
$('tab-'+t).classList.add('on');$('nb-'+t).classList.add('on');scrollTo(0,0)}
function toggleForm(id){$(id).classList.toggle('open')}
function openSheet(html){$('sheet').innerHTML=html;$('sheet').style.display='block';$('sheetbg').style.display='block'}
function closeSheet(){$('sheet').style.display='none';$('sheetbg').style.display='none'}

async function api(path,body){try{
const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
if(r.status===401||r.status===403){location.reload();return null}
const j=await r.json();if(j&&j.data)apply(j.data);return j}catch(e){return null}}
function apply(d){if(!d||typeof d.rev!=='number')return;if(d.rev<applied)return;applied=d.rev;S=d;render()}

/* ── ВОРОНКА ── */
function renderFunnel(){
const f=S.funnel||{deals:[],paid:[]};
$('f-total').textContent=eur(f.total);$('f-w').textContent='~'+eur(f.weighted);
$('f-paid').textContent=eur((f.paid||[]).reduce((a,p)=>a+(p.amount||0),0));
const sel=$('d-proj');const keep=sel.value;
sel.innerHTML='<option value="">Новый проект…</option>'+(S.projects||[]).map(p=>
`<option value="${p.id}">${esc(p.name)}</option>`).join('');sel.value=keep;
const cols=FST.map(([st,label,color])=>{
  let cards='',sum=0,n=0;
  if(st==='paid'){(f.paid||[]).forEach(p=>{sum+=p.amount||0;n++;
    cards+=`<div class="cardx" style="border-left-color:${color};cursor:default">
    <div class="nm">${esc(p.name)}</div><div class="meta"><span class="amt">${eur(p.amount)}</span>
    <span>${esc(p.date||'')}</span></div></div>`});}
  else{(f.deals||[]).filter(d=>d.status===st).forEach(d=>{sum+=d.amount;n++;
    cards+=`<div class="cardx" style="border-left-color:${color}" onclick='dealSheet(${d.id})'>
    <div class="nm">${esc(d.name)}</div><div class="meta"><span class="amt">${eur(d.amount)}</span>
    ${d.date?`<span class="${d.overdue?'od':''}">⏱ ${esc(d.date)}${d.overdue?' · просрочено':''}</span>`:''}
    </div></div>`});}
  return `<div class="col"><h3>${label} <span class="badge">${n}</span><span class="sum">${eur(sum)}</span></h3>
  ${cards||'<div class="empty">пусто</div>'}</div>`});
$('funnel-board').innerHTML=cols.join('');
}
function dealSheet(id){
const d=(S.funnel.deals||[]).find(x=>x.id===id);if(!d)return;
const stBtns=FST.filter(([st])=>st!==d.status&&st!=='paid').map(([st,l])=>
`<button class="act" onclick='setStage(${id},"${st}")'>→ ${l}</button>`).join('');
openSheet(`<h3>${esc(d.name)}</h3><div class="sub">${eur(d.amount)}${d.date?' · оплата ~'+esc(d.date):''}
 · стадия: ${(FST.find(([s])=>s===d.status)||[])[1]||d.status}</div>
${stBtns}
<button class="act" style="color:var(--paid)" onclick='markPaid(${id})'>✅ Оплачено (деньги пришли)</button>
<button class="act" onclick='editDeal(${id})'>✏️ Сумма / дата</button>
<button class="act sec" onclick="closeSheet()">Закрыть</button>`)}
async function setStage(id,st){closeSheet();await api('/api/deal_stage',{id,status:st})}
async function markPaid(id){const d=(S.funnel.deals||[]).find(x=>x.id===id);closeSheet();
openSheet(`<h3>Куда пришли деньги?</h3><div class="sub">${esc(d?d.name:'')} · ${eur(d?d.amount:0)}</div>
<button class="act" onclick='paidTo(${id},"card")'>💳 Карта</button>
<button class="act" onclick='paidTo(${id},"cash")'>💵 Наличные</button>
<button class="act sec" onclick="closeSheet()">Отмена</button>`)}
async function paidTo(id,acc){closeSheet();await api('/api/deal_stage',{id,status:'paid',account:acc})}
async function editDeal(id){const d=(S.funnel.deals||[]).find(x=>x.id===id);closeSheet();
const amt=prompt('Сумма €:',d?d.amount:'');if(amt===null)return;
const dt=prompt('Дата оплаты (ГГГГ-ММ-ДД, пусто — убрать):',d&&d.date?d.date:'');if(dt===null)return;
await api('/api/deal_update',{id,amount:parseFloat(amt)||0,date:dt.trim()})}
async function dealAdd(){
const pid=$('d-proj').value,name=$('d-name').value.trim(),amt=parseFloat($('d-amt').value)||0,dt=$('d-date').value;
if(!pid&&!name)return;await api('/api/deal_add',{project_id:pid?parseInt(pid):null,name,amount:amt,date:dt});
$('d-name').value='';$('d-amt').value='';$('d-date').value='';$('d-proj').value='';toggleForm('dealform')}

/* ── ЛИДЫ ── */
function leadCard(l){
const warn=!l.na&&!l.nad;
return `<div class="cardx ${warn?'warn':''}" style="border-left-color:var(--lead)" onclick='leadSheet(${l.id})'>
<div class="nm">${CH[l.channel]||'📌'} ${esc(l.name)}</div>
<div class="meta">${l.budget?`<span class="amt">~${eur(l.budget)}</span>`:''}
${l.na?`<span class="${l.overdue?'od':''}">▸ ${esc(l.na)}${l.nad?' · '+esc(l.nad):''}</span>`
      :'<span style="color:var(--gold)">⚠ нет следующего шага</span>'}
<span class="badge">👣 ${l.touches}</span></div></div>`}
function renderLeads(){
const items=(S.leads&&S.leads.items)||[];
const due=items.filter(l=>l.due_today);
$('today-box').style.display=due.length?'block':'none';
$('today-list').innerHTML=due.map(l=>`<div class="it" onclick='leadSheet(${l.id})'>
<span>${CH[l.channel]||'📌'}</span><b>${esc(l.name)}</b>
<span style="color:var(--dim)">${esc(l.na||'коснуться')}</span>
<span class="d ${l.overdue?'od':''}">${esc(l.nad||'')}</span></div>`).join('');
$('leads-board').innerHTML=LST.map(([st,label])=>{
const ls=items.filter(l=>l.stage===st);
return `<div class="col"><h3>${label} <span class="badge">${ls.length}</span></h3>
${ls.map(leadCard).join('')||'<div class="empty">пусто</div>'}</div>`}).join('');
const lost=(S.leads&&S.leads.lost)||[];
$('lost-box').style.display=lost.length?'block':'none';
$('lost-list').innerHTML=lost.map(x=>`<div class="rowl"><span>${esc(x.name)}</span>
<span class="muted">${esc(x.reason||'—')}</span><span class="r muted">${esc(x.date||'')}</span></div>`).join('');
}
function leadSheet(id){
const l=(S.leads.items||[]).find(x=>x.id===id);if(!l)return;
const stBtns=LST.filter(([st])=>st!==l.stage).map(([st,lb])=>
`<button class="act" onclick='leadStage(${id},"${st}")'>→ ${lb}</button>`).join('');
openSheet(`<h3>${CH[l.channel]||'📌'} ${esc(l.name)}</h3>
<div class="sub">${l.budget?'~'+eur(l.budget)+' · ':''}касаний: ${l.touches}
${l.notes?'<br>'+esc(l.notes):''}</div>
<button class="act" style="color:var(--gold)" onclick='leadTouch(${id})'>👣 Касание сделано → следующее</button>
${stBtns}
<button class="act" style="color:var(--paid)" onclick='leadConvert(${id})'>💰 Выиграли → в сделку</button>
<button class="act" onclick='leadEdit(${id})'>✏️ Правка (бюджет/заметка)</button>
<button class="act warn" onclick='leadLost(${id})'>❌ Отказ</button>
<button class="act sec" onclick="closeSheet()">Закрыть</button>`)}
async function leadStage(id,st){closeSheet();await api('/api/lead_update',{id,stage:st})}
async function leadTouch(id){closeSheet();
const na=prompt('Что дальше? (следующее действие)');if(na===null)return;
const nad=prompt('Когда? (ГГГГ-ММ-ДД)',S.today||'');if(nad===null)return;
await api('/api/lead_touch',{id,na,nad})}
async function leadConvert(id){closeSheet();const l=(S.leads.items||[]).find(x=>x.id===id);
const amt=prompt('Сумма сделки €:',l&&l.budget?l.budget:'');if(amt===null)return;
await api('/api/lead_convert',{id,amount:parseFloat(amt)||0});show('funnel')}
async function leadEdit(id){closeSheet();const l=(S.leads.items||[]).find(x=>x.id===id);
const b=prompt('Бюджет ~€:',l.budget||'');if(b===null)return;
const nt=prompt('Заметка:',l.notes||'');if(nt===null)return;
await api('/api/lead_update',{id,budget:parseFloat(b)||0,notes:nt})}
async function leadLost(id){closeSheet();const r=prompt('Причина отказа (важно для анализа):');
if(r===null)return;await api('/api/lead_lost',{id,reason:r})}
async function leadAdd(){const name=$('l-name').value.trim();if(!name)return;
await api('/api/lead_add',{name,channel:$('l-chan').value,budget:parseFloat($('l-budget').value)||0,
na:$('l-na').value,nad:$('l-nad').value,notes:$('l-notes').value});
['l-name','l-budget','l-na','l-nad','l-notes'].forEach(i=>$(i).value='');toggleForm('leadform')}

/* ── ДЕНЬГИ ── */
function renderMoney(){
const m=S.money||{};
$('m-bal').textContent=eur(m.balance);$('m-card').textContent=eur(m.card);$('m-cash').textContent=eur(m.cash);
const prev=m.prev_gross||0,cur=m.cur_gross||0,thP=25000,thC=100000;
const pp=Math.min(100,prev/thP*100),pc=Math.min(100,cur/thC*100);
$('th-prev-t').innerHTML=`Прошлый год: <b>${eur(prev)}</b> из ${eur(thP)}`;
$('th-prev-p').className='prog'+(pp>85?' hot':'');$('th-prev-p').firstElementChild.style.width=pp+'%';
$('th-prev-m').textContent=pp>=100?'⚠️ порог превышен — статус §19 под вопросом (к Юристу)':
  pp>85?'близко к порогу — обсуди с Юристом':'в пределах порога';
$('th-cur-t').innerHTML=`Текущий год: <b>${eur(cur)}</b> из ${eur(thC)}`;
$('th-cur-p').className='prog'+(pc>85?' hot':'');$('th-cur-p').firstElementChild.style.width=pc+'%';
$('th-cur-m').textContent='при превышении 100k€ переход на USt происходит сразу в течение года';
const ys=m.years||[];const mx=Math.max(1,...ys.map(y=>y.gross));
$('years-bars').innerHTML=ys.map(y=>`<div class="b"><span class="vl">${Math.round(y.gross/100)/10}k</span>
<div class="bar" style="height:${Math.max(3,y.gross/mx*78)}px"></div><span class="yl">${y.year}</span></div>`).join('')
||'<div class="empty">нет данных — пришли инвойсы Юристу (/collect)</div>';
$('mon-title').textContent=`ПО МЕСЯЦАМ · ${m.cur_year||''}`;
const ms=m.months||[];const mmx=Math.max(1,...ms);
$('mon-bars').innerHTML=ms.map((v,i)=>`<div class="b">${v?`<span class="vl">${Math.round(v/100)/10}k</span>`:''}
<div class="bar" style="height:${Math.max(2,v/mmx*54)}px;background:linear-gradient(180deg,#52e08a,#2e9c5f)"></div>
<span class="yl">${i+1}</span></div>`).join('');
const open=(S.funnel.deals||[]).filter(d=>d.status==='invoiced');
$('open-inv').innerHTML=open.map(d=>`<div class="rowl"><span>${esc(d.name)}</span>
${d.date?`<span class="muted ${d.overdue?'od':''}">${esc(d.date)}</span>`:''}
<span class="r">${eur(d.amount)}</span></div>`).join('')||'<div class="empty">нет выставленных счетов</div>';
$('top-clients').innerHTML=(m.clients||[]).map(c=>`<div class="rowl">
<span>${esc(c.name)} ${c.n>1?'<span class="badge">↻ '+c.n+'</span>':''}</span>
<span class="r">${eur(c.total)}</span></div>`).join('')||'<div class="empty">нет данных</div>';
}

function render(){renderFunnel();renderLeads();renderMoney()}

async function poll(){try{
const r=await fetch('/api/data',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
if(r.status===401){location.reload();return}
apply(await r.json())}catch(e){}}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){
navigator.sendBeacon&&navigator.sendBeacon('/api/lock','{}')}});
if(S&&typeof S.rev==='number'){applied=S.rev;render()}else{poll()}
show('funnel');setInterval(poll,5000);
</script></body></html>"""


ROUTES = {
    "/api/deal_add": api_deal_add, "/api/deal_stage": api_deal_stage,
    "/api/deal_update": api_deal_update,
    "/api/lead_add": api_lead_add, "/api/lead_update": api_lead_update,
    "/api/lead_touch": api_lead_touch, "/api/lead_convert": api_lead_convert,
    "/api/lead_lost": api_lead_lost, "/api/lead_delete": api_lead_delete,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _authed(self):
        global _last_seen
        cookie = self.headers.get("Cookie", "") or ""
        ok = any(part.strip().partition("=")[0] == "bizdash"
                 and part.strip().partition("=")[2] == SESSION_TOKEN
                 for part in cookie.split(";"))
        if not ok:
            return False
        now = time.time()
        if (now - _last_seen) > IDLE_TIMEOUT:
            return False
        _last_seen = now
        return True

    def _send(self, body, ctype, extra_headers=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        for h, v in (extra_headers or []):
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if not self._authed():
            if path.startswith("/api/"):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(LOCK_PAGE.encode(), "text/html; charset=utf-8")
            return
        if path == "/api/data":
            self._send(json.dumps(get_data(), ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
        else:
            try:
                data_json = json.dumps(get_data(), ensure_ascii=False)
                page = (PAGE.replace("__VERSION__", VERSION)
                            .replace("window.__INIT__=null", "window.__INIT__=" + data_json))
            except Exception:
                page = PAGE.replace("__VERSION__", VERSION)
            self._send(page.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        global _last_seen
        path = self.path.split('?', 1)[0]
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            payload = {}

        if path == "/api/unlock":
            result = _set_session(payload)
            extra = None
            if result.get("ok"):
                _last_seen = time.time()
                extra = [("Set-Cookie", f"bizdash={SESSION_TOKEN}; Path=/; SameSite=Lax; HttpOnly")]
            self._send(json.dumps(result).encode(), "application/json; charset=utf-8", extra)
            return
        if path == "/api/lock":
            _last_seen = 0.0
            extra = [("Set-Cookie", "bizdash=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly")]
            self._send(b'{"ok":true}', "application/json; charset=utf-8", extra)
            return
        if not self._authed():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/data":
            self._send(json.dumps(get_data(), ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
            return
        fn = ROUTES.get(path)
        try:
            result = fn(payload) if fn else {"ok": False}
        except Exception as e:
            # мутация не должна рвать соединение — клиент получает честную ошибку
            result = {"ok": False, "err": str(e)[:200]}
        if not isinstance(result, dict):
            result = {"ok": True}
        try:
            bump_rev()
            result["data"] = get_data()
        except Exception:
            pass
        self._send(json.dumps(result, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")


if __name__ == "__main__":
    print(f"Бизнес-пульт FARBAHOLIX: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
