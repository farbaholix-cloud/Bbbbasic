"""Живой голосовой секретарь: непрерывный разговор без кнопок.

Браузер (PWA по HTTPS) стримит микрофон по WebSocket на этот сервер, сервер —
мост к Gemini Live API (модель сама держит очередь реплик и перебивания).
Голосовые функции (инструменты) обращаются напрямую к базе friedman.db:
задачи, финансы, проекты, обязательства. Ключ Gemini и база — только на сервере.

Запуск:  GEMINI_API_KEY=... python voicelive.py     (порт 8766)
Ключ также берётся из файла .gemini_key рядом с этим файлом.
"""
import os
import json
import sqlite3
import asyncio
import logging
import datetime

from aiohttp import web, WSMsgType
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voicelive")

_BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(_BASE, "friedman.db")
PORT = int(os.getenv("VOICE_PORT", "8766"))
MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-exp")


def _key() -> str:
    k = os.getenv("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(os.path.join(_BASE, ".gemini_key")) as f:
            return f.read().strip()
    except Exception:
        return ""


# ── доступ к базе (синхронно, запросы лёгкие) ───────────────────────────────
def _q(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
        con.commit()
        return rows
    finally:
        con.close()


def _exec(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid, cur.rowcount
    finally:
        con.close()


# ── инструменты, которые озвучивает и вызывает Gemini ───────────────────────
def t_list_tasks(area=None, limit=20):
    if area:
        rows = _q("SELECT text,area,priority FROM chaos WHERE done=0 AND area=? "
                  "ORDER BY created_at DESC LIMIT ?", (area, limit))
    else:
        rows = _q("SELECT text,area,priority FROM chaos WHERE done=0 "
                  "ORDER BY created_at DESC LIMIT ?", (limit,))
    return {"count": len(rows), "tasks": rows}


def t_add_task(text, area="other", priority="mid"):
    if not text:
        return {"ok": False, "error": "пустая задача"}
    _exec("INSERT INTO chaos(text,area,priority) VALUES(?,?,?)", (text, area, priority))
    return {"ok": True, "added": text}


def t_complete_task(text):
    rows = _q("SELECT id,text FROM chaos WHERE done=0 AND text LIKE ? "
              "ORDER BY created_at DESC LIMIT 1", (f"%{text}%",))
    if not rows:
        return {"ok": False, "error": "не нашёл такую открытую задачу"}
    _exec("UPDATE chaos SET done=1 WHERE id=?", (rows[0]["id"],))
    return {"ok": True, "completed": rows[0]["text"]}


def t_finance_summary(days=30):
    rows = _q("SELECT COUNT(*) n, COALESCE(SUM(amount),0) total FROM finance "
              "WHERE created_at >= datetime('now', ?)", (f"-{int(days)} days",))
    r = rows[0]
    return {"days": days, "operations": r["n"], "total": round(r["total"], 2)}


def t_add_expense(amount, comment="", account="card"):
    try:
        amount = float(amount)
    except Exception:
        return {"ok": False, "error": "сумма не распознана"}
    _exec("INSERT INTO finance(amount,comment,account) VALUES(?,?,?)",
          (amount, comment, account))
    return {"ok": True, "amount": amount, "comment": comment}


def t_list_projects():
    rows = _q("""SELECT p.name,
                        COUNT(s.id) AS total,
                        COALESCE(SUM(s.done),0) AS done
                 FROM projects p LEFT JOIN steps s ON s.project_id=p.id
                 GROUP BY p.id ORDER BY p.created_at DESC LIMIT 20""")
    return {"count": len(rows), "projects": rows}


def t_list_obligations():
    debts = _q("SELECT name,total,paid FROM debts ORDER BY due_date LIMIT 20")
    pays = _q("SELECT title,amount,recur FROM payments WHERE active=1 LIMIT 20")
    return {"debts": debts, "payments": pays}


def t_daily_brief():
    open_tasks = _q("SELECT COUNT(*) n FROM chaos WHERE done=0")[0]["n"]
    today = datetime.date.today().isoformat()
    due = _q("SELECT text FROM reminders WHERE sent=0 AND date(due_at)<=? LIMIT 20", (today,))
    return {"open_tasks": open_tasks, "reminders_due": [r["text"] for r in due]}


DISPATCH = {
    "list_tasks": t_list_tasks, "add_task": t_add_task, "complete_task": t_complete_task,
    "finance_summary": t_finance_summary, "add_expense": t_add_expense,
    "list_projects": t_list_projects, "list_obligations": t_list_obligations,
    "daily_brief": t_daily_brief,
}


def dispatch(name, args):
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"неизвестная функция {name}"}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {"error": f"неверные аргументы: {e}"}
    except Exception as e:
        return {"error": str(e)}


FUNCS = [
    {"name": "list_tasks", "description": "Открытые задачи (входящие). Можно отфильтровать по area.",
     "parameters": {"type": "object", "properties": {
         "area": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "add_task", "description": "Добавить новую задачу.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"}, "area": {"type": "string"},
         "priority": {"type": "string"}}, "required": ["text"]}},
    {"name": "complete_task", "description": "Закрыть задачу по совпадению текста.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"]}},
    {"name": "finance_summary", "description": "Сводка трат за последние N дней.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "add_expense", "description": "Записать трату/операцию.",
     "parameters": {"type": "object", "properties": {
         "amount": {"type": "number"}, "comment": {"type": "string"},
         "account": {"type": "string"}}, "required": ["amount"]}},
    {"name": "list_projects", "description": "Проекты и прогресс по шагам.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_obligations", "description": "Долги и регулярные платежи.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "daily_brief", "description": "Короткая сводка: открытые задачи и напоминания на сегодня.",
     "parameters": {"type": "object", "properties": {}}},
]

SYS = (
    "Ты — Секретарь Фридмана, личный голосовой помощник художника по имени Слава "
    "(уличный художник FARBAHOLIX), Франкфурт-на-Майне. Говоришь по-русски, живо и "
    "по-человечески, коротко (1–3 предложения), как в разговоре, без списков и markdown. "
    "Для любых данных о задачах, финансах, проектах и обязательствах ВСЕГДА вызывай "
    "функции — не выдумывай. После действия коротко подтверждай голосом. "
    "Никогда не цитируй русских/советских авторов. Будь тёплым и собранным."
)


# ── WebSocket-мост браузер ↔ Gemini Live ────────────────────────────────────
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    log.info("браузер подключился (%s)", request.remote)
    key = _key()
    if not key:
        log.error("нет ключа Gemini")
        await ws.send_str(json.dumps({"type": "error", "text": "нет ключа Gemini"}))
        await ws.close()
        return ws

    client = genai.Client(api_key=key)
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": SYS,
        "tools": [{"function_declarations": FUNCS}],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "speech_config": {"language_code": "ru-RU"},
    }

    try:
        log.info("подключаюсь к Gemini Live (model=%s)…", MODEL)
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            log.info("Gemini Live сессия открыта")
            await ws.send_str(json.dumps({"type": "ready"}))

            async def browser_to_gemini():
                async for msg in ws:
                    if msg.type == WSMsgType.BINARY:
                        await session.send_realtime_input(
                            audio=types.Blob(data=msg.data, mime_type="audio/pcm;rate=16000"))
                    elif msg.type == WSMsgType.TEXT:
                        d = json.loads(msg.data)
                        if d.get("type") == "end":
                            break
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break

            async def gemini_to_browser():
                async for response in session.receive():
                    # ─ аудио: сначала response.data (новые SDK), затем через parts
                    raw = getattr(response, "data", None)
                    if raw:
                        await ws.send_bytes(raw)

                    sc = getattr(response, "server_content", None)
                    if sc:
                        mt = getattr(sc, "model_turn", None)
                        if mt:
                            for part in (getattr(mt, "parts", None) or []):
                                blob = getattr(part, "inline_data", None)
                                if blob and getattr(blob, "data", None):
                                    if not raw:  # не дублировать если уже послали
                                        await ws.send_bytes(blob.data)
                                txt = getattr(part, "text", None)
                                if txt:
                                    await ws.send_str(json.dumps({"type": "say", "text": txt}))

                        ot = getattr(sc, "output_transcription", None)
                        if ot and getattr(ot, "text", None):
                            await ws.send_str(json.dumps({"type": "say", "text": ot.text}))
                        it = getattr(sc, "input_transcription", None)
                        if it and getattr(it, "text", None):
                            await ws.send_str(json.dumps({"type": "heard", "text": it.text}))
                        if getattr(sc, "interrupted", False):
                            await ws.send_str(json.dumps({"type": "interrupted"}))

                    tc = getattr(response, "tool_call", None)
                    if tc and getattr(tc, "function_calls", None):
                        responses = []
                        for fc in tc.function_calls:
                            args = dict(fc.args) if fc.args else {}
                            res = await asyncio.get_event_loop().run_in_executor(
                                None, lambda n=fc.name, a=args: dispatch(n, a))
                            responses.append(types.FunctionResponse(
                                id=fc.id, name=fc.name, response={"result": res}))
                            await ws.send_str(json.dumps({"type": "tool", "name": fc.name}))
                        await session.send_tool_response(function_responses=responses)

            t1 = asyncio.create_task(browser_to_gemini())
            t2 = asyncio.create_task(gemini_to_browser())
            done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception as e:
        log.exception("ошибка сессии Gemini (model=%s): %s", MODEL, e)
        try:
            await ws.send_str(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass
    finally:
        log.info("сессия закрыта")
        if not ws.closed:
            await ws.close()
    return ws


async def index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def health(request):
    return web.json_response({"ok": True, "model": MODEL, "has_key": bool(_key())})


async def manifest(request):
    return web.json_response({
        "name": "Секретарь", "short_name": "Секретарь", "start_url": "/",
        "display": "standalone", "background_color": "#000000",
        "theme_color": "#000000",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    })


async def icon(request):
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'>"
           "<rect width='192' height='192' rx='44' fill='#0b0b0f'/>"
           "<circle cx='96' cy='96' r='52' fill='none' stroke='#d0142a' stroke-width='10'/>"
           "<circle cx='96' cy='96' r='8' fill='#fff'/></svg>")
    return web.Response(text=svg, content_type="image/svg+xml")


def make_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/manifest.webmanifest", manifest)
    app.router.add_get("/icon.svg", icon)
    return app


PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.svg">
<title>Секретарь</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-user-select:none;user-select:none}
html,body{height:100%;background:radial-gradient(1200px 800px at 50% -10%,#171727,#05060a 60%);
  color:#eef;font-family:-apple-system,sans-serif;overflow:hidden}
#wrap{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px;
  padding:env(safe-area-inset-top) 20px calc(28px + env(safe-area-inset-bottom))}
#orb{width:210px;height:210px;border-radius:50%;position:relative;transition:transform .12s ease-out;
  background:radial-gradient(circle at 38% 32%,#ff5a5a,#d0142a 45%,#5e0512 100%);
  box-shadow:0 0 60px 10px rgba(208,20,42,.45),inset 0 0 60px rgba(0,0,0,.45)}
#orb::after{content:"";position:absolute;inset:-14px;border-radius:50%;
  border:1px solid rgba(255,90,90,.25);animation:halo 3s ease-in-out infinite}
@keyframes halo{0%,100%{transform:scale(1);opacity:.5}50%{transform:scale(1.08);opacity:.9}}
.idle #orb{background:radial-gradient(circle at 38% 32%,#3a3a52,#15151f 60%);box-shadow:0 0 40px rgba(80,80,120,.3)}
.speaking #orb{box-shadow:0 0 80px 18px rgba(255,80,80,.6),inset 0 0 60px rgba(0,0,0,.4)}
#status{font-size:15px;letter-spacing:.3px;color:rgba(238,238,255,.55);min-height:20px;text-align:center}
#cap{max-width:560px;text-align:center;font-size:17px;line-height:1.45;color:#dfe2ff;min-height:52px}
#cap .me{color:#8aa0ff}
#btn{padding:16px 34px;border:none;border-radius:30px;font-size:17px;font-weight:600;color:#fff;
  background:linear-gradient(180deg,#e2233c,#a30f23);box-shadow:0 8px 24px rgba(208,20,42,.4);transition:opacity .2s}
#btn.stop{background:linear-gradient(180deg,#2a2a3a,#16161f);box-shadow:none;color:#cdd}
.bar{position:fixed;top:calc(14px + env(safe-area-inset-top));right:16px;font-size:11px;color:rgba(255,255,255,.3)}
</style></head>
<body class="idle">
<div class="bar" id="ver">live</div>
<div id="wrap">
  <div id="orb"></div>
  <div id="status">нажми, чтобы начать разговор</div>
  <div id="cap"></div>
  <button id="btn">Поговорить</button>
</div>
<script>
const body=document.body,orb=document.getElementById('orb'),statusEl=document.getElementById('status'),
      cap=document.getElementById('cap'),btn=document.getElementById('btn');
let ws=null,actx=null,proc=null,micStream=null,playT=0,running=false,sources=[];
const IN_RATE=16000,OUT_RATE=24000;

function setState(s,txt){body.className=s;if(txt!=null)statusEl.textContent=txt;}
function downsample(buf,from,to){
  if(to>=from)return buf;
  const ratio=from/to,len=Math.round(buf.length/ratio),out=new Float32Array(len);
  let o=0,i=0;
  while(o<len){const next=Math.round((o+1)*ratio);let s=0,c=0;
    for(;i<next&&i<buf.length;i++){s+=buf[i];c++;}out[o]=c?s/c:0;o++;}
  return out;
}
function f32toI16(f){const o=new Int16Array(f.length);
  for(let i=0;i<f.length;i++){let v=Math.max(-1,Math.min(1,f[i]));o[i]=v<0?v*32768:v*32767;}return o;}

function playPCM(i16){
  const f=new Float32Array(i16.length);
  for(let i=0;i<i16.length;i++)f[i]=i16[i]/32768;
  const buf=actx.createBuffer(1,f.length,OUT_RATE);buf.copyToChannel(f,0);
  const src=actx.createBufferSource();src.buffer=buf;src.connect(actx.destination);
  const now=actx.currentTime;if(playT<now)playT=now;
  src.start(playT);playT+=buf.duration;sources.push(src);
  setState('speaking','говорит…');
  src.onended=()=>{sources=sources.filter(s=>s!==src);
    if(!sources.length&&running)setState('listening','слушаю…');};
}
function stopPlayback(){sources.forEach(s=>{try{s.stop()}catch(e){}});sources=[];playT=0;}

async function start(){
  try{
    actx=new (window.AudioContext||window.webkitAudioContext)();
    await actx.resume();
    micStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  }catch(e){setState('idle','нет доступа к микрофону: '+e.message);return;}
  const proto=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(proto+'://'+location.host+'/ws');
  ws.binaryType='arraybuffer';
  ws.onopen=()=>{
    const src=actx.createMediaStreamSource(micStream);
    proc=actx.createScriptProcessor(4096,1,1);
    const mute=actx.createGain();mute.gain.value=0;
    src.connect(proc);proc.connect(mute);mute.connect(actx.destination);
    proc.onaudioprocess=e=>{
      const inBuf=e.inputBuffer.getChannelData(0);
      let s=0;for(let i=0;i<inBuf.length;i++)s+=inBuf[i]*inBuf[i];
      const rms=Math.sqrt(s/inBuf.length);
      orb.style.transform='scale('+(1+Math.min(.35,rms*4))+')';
      if(ws&&ws.readyState===1){
        const ds=downsample(inBuf,actx.sampleRate,IN_RATE);
        ws.send(f32toI16(ds).buffer);
      }
    };
    running=true;setState('listening','слушаю…');
    btn.textContent='Закончить';btn.classList.add('stop');
  };
  ws.onmessage=ev=>{
    if(typeof ev.data!=='string'){playPCM(new Int16Array(ev.data));return;}
    const m=JSON.parse(ev.data);
    if(m.type==='say'){cap.innerHTML='<span class="ai">'+m.text+'</span>';}
    else if(m.type==='heard'){cap.innerHTML='<span class="me">'+m.text+'</span>';}
    else if(m.type==='interrupted'){stopPlayback();setState('listening','слушаю…');}
    else if(m.type==='tool'){statusEl.textContent='смотрю в базу…';}
    else if(m.type==='error'){setState('idle','ошибка: '+m.text);}
  };
  ws.onerror=()=>{setState('idle','нет связи с сервером — проверь /setupvoicelive');};
  ws.onclose=()=>{if(running){running=false;setState('idle','связь закрыта');reset();}};
}
function reset(){btn.textContent='Поговорить';btn.classList.remove('stop');}
function stop(){running=false;stopPlayback();
  try{ws&&ws.send(JSON.stringify({type:'end'}))}catch(e){}
  try{ws&&ws.close()}catch(e){}
  try{proc&&proc.disconnect()}catch(e){}
  try{micStream&&micStream.getTracks().forEach(t=>t.stop())}catch(e){}
  setState('idle','нажми, чтобы начать разговор');reset();orb.style.transform='';}

btn.addEventListener('click',()=>{running?stop():start();});
</script></body></html>"""


if __name__ == "__main__":
    log.info("старт voicelive: порт=%s, model=%s, ключ=%s",
             PORT, MODEL, "есть" if _key() else "НЕТ")
    if not _key():
        log.warning("Нет ключа Gemini. Задай GEMINI_API_KEY или файл .gemini_key")
    web.run_app(make_app(), host="0.0.0.0", port=PORT, print=lambda *a: log.info(" ".join(map(str, a))))
