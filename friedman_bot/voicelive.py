"""Голосовой секретарь: асинхронный диалог без платных API.

Браузер записывает речь → VAD определяет паузу → WebSocket отправляет PCM →
Whisper (STT) → Claude haiku (LLM с контекстом базы) → Edge TTS → MP3 обратно.

Запуск: python voicelive.py   (порт 8766)
"""
import os
import json
import sqlite3
import asyncio
import logging
import tempfile
import wave
import subprocess
import datetime

from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voicelive")

_BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(_BASE, "friedman.db")
PORT = int(os.getenv("VOICE_PORT", "8766"))
EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "ru-RU-SvetlanaNeural")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
CLAUDE_MODEL = os.getenv("CLAUDE_VOICE_MODEL", "haiku")

SYS = (
    "Ты — Секретарь Фридмана, личный голосовой помощник художника Слава (бренд FARBAHOLIX), "
    "Франкфурт-на-Майне. Говори по-русски, коротко (1-3 предложения), живо, как в разговоре. "
    "Без markdown и списков. Никогда не цитируй русских/советских авторов. "
    "Будь тёплым и собранным. Для данных о задачах/финансах используй контекст ниже."
)

_whisper_model = None


# ── краткий контекст из базы ──────────────────────────────────────────────────
def _get_context() -> str:
    try:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        tasks = con.execute(
            "SELECT text, area FROM chaos WHERE done=0 ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        bal = con.execute("SELECT COALESCE(SUM(amount),0) FROM finance").fetchone()[0]
        cash = con.execute(
            "SELECT COALESCE(SUM(amount),0) FROM finance WHERE account='cash'"
        ).fetchone()[0]
        reminders = con.execute(
            "SELECT text, due_at FROM reminders WHERE sent=0 ORDER BY due_at LIMIT 5"
        ).fetchall()
        con.close()
        lines = [f"Сегодня: {datetime.date.today().isoformat()}"]
        if tasks:
            lines.append("Открытые задачи:")
            for t in tasks:
                lines.append(f"  • [{t['area']}] {t['text']}")
        lines.append(f"Баланс: {bal:+.0f}€ (наличные {cash:+.0f}€)")
        if reminders:
            lines.append("Напоминания:")
            for r in reminders:
                lines.append(f"  • {r['due_at'][:10]} — {r['text']}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("db context error: %s", e)
        return ""


# ── STT (Whisper) ─────────────────────────────────────────────────────────────
def _transcribe(wav_path: str) -> str:
    global _whisper_model
    try:
        import whisper
        if _whisper_model is None:
            log.info("загружаю Whisper small…")
            _whisper_model = whisper.load_model("small")
        result = _whisper_model.transcribe(wav_path, language="ru")
        return result["text"].strip()
    except Exception as e:
        log.error("whisper: %s", e)
        return ""


# ── LLM (Claude CLI) ─────────────────────────────────────────────────────────
def _ask_claude(user_text: str) -> str:
    ctx = _get_context()
    prompt = f"{ctx}\n\nВопрос: {user_text}" if ctx else user_text
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--append-system-prompt", SYS,
             "--model", CLAUDE_MODEL,
             "--max-turns", "1", "--tools", ""],
            capture_output=True, text=True, timeout=60,
            env={**os.environ,
                 "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        return r.stdout.strip()
    except Exception as e:
        log.error("claude: %s", e)
        return ""


# ── TTS (Edge TTS) ───────────────────────────────────────────────────────────
async def _tts(text: str) -> bytes:
    try:
        import edge_tts
        fd, p = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        await edge_tts.Communicate(text, EDGE_VOICE).save(p)
        if os.path.getsize(p) < 256:
            os.unlink(p)
            return b""
        with open(p, "rb") as f:
            data = f.read()
        os.unlink(p)
        return data
    except Exception as e:
        log.error("edge-tts: %s", e)
        return b""


# ── обработка одного высказывания ─────────────────────────────────────────────
async def process_utterance(ws: web.WebSocketResponse, pcm: bytes):
    if len(pcm) < 6400:  # < 0.2 сек при 16kHz 16-bit — игнорируем
        return
    try:
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(pcm)

        await ws.send_str(json.dumps({"type": "status", "text": "слышу…"}))
        text = await asyncio.get_event_loop().run_in_executor(None, _transcribe, wav)
        try: os.unlink(wav)
        except Exception: pass

        if not text or len(text.strip()) < 2:
            await ws.send_str(json.dumps({"type": "status", "text": "слушаю…"}))
            return

        log.info("услышал: %s", text)
        await ws.send_str(json.dumps({"type": "heard", "text": text}))
        await ws.send_str(json.dumps({"type": "status", "text": "думаю…"}))

        reply = await asyncio.get_event_loop().run_in_executor(None, _ask_claude, text)
        if not reply:
            await ws.send_str(json.dumps({"type": "status", "text": "слушаю…"}))
            return

        log.info("отвечаю: %s", reply[:80])
        await ws.send_str(json.dumps({"type": "say", "text": reply}))
        await ws.send_str(json.dumps({"type": "status", "text": "говорю…"}))

        audio = await _tts(reply)
        if audio:
            await ws.send_bytes(audio)

        await ws.send_str(json.dumps({"type": "done"}))

    except Exception as e:
        log.exception("process_utterance: %s", e)
        try:
            await ws.send_str(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass


# ── WebSocket-хендлер ─────────────────────────────────────────────────────────
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    log.info("браузер подключился (%s)", request.remote)
    await ws.send_str(json.dumps({"type": "ready"}))

    chunks = []

    async for msg in ws:
        if msg.type == WSMsgType.BINARY:
            chunks.append(msg.data)
        elif msg.type == WSMsgType.TEXT:
            try:
                d = json.loads(msg.data)
            except Exception:
                continue
            if d.get("type") == "utterance_end" and chunks:
                pcm = b"".join(chunks)
                chunks.clear()
                asyncio.create_task(process_utterance(ws, pcm))
            elif d.get("type") == "end":
                break
        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
            break

    log.info("сессия закрыта")
    if not ws.closed:
        await ws.close()
    return ws


# ── статика ───────────────────────────────────────────────────────────────────
async def index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def health(request):
    return web.json_response({"ok": True, "mode": "whisper+claude+edge-tts"})


async def manifest(request):
    return web.json_response({
        "name": "Секретарь", "short_name": "Секретарь",
        "start_url": "/", "display": "standalone",
        "background_color": "#000000", "theme_color": "#000000",
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
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health)
    app.router.add_get("/manifest.webmanifest", manifest)
    app.router.add_get("/icon.svg", icon)
    return app


# ── браузерное приложение ─────────────────────────────────────────────────────
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
#wrap{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:28px;
  padding:env(safe-area-inset-top) 20px calc(28px + env(safe-area-inset-bottom))}
#orb{width:200px;height:200px;border-radius:50%;position:relative;
  transition:transform .08s ease-out,box-shadow .15s;
  background:radial-gradient(circle at 38% 32%,#ff5a5a,#d0142a 45%,#5e0512 100%);
  box-shadow:0 0 60px 10px rgba(208,20,42,.45),inset 0 0 60px rgba(0,0,0,.45)}
#orb::after{content:"";position:absolute;inset:-14px;border-radius:50%;
  border:1px solid rgba(255,90,90,.25);animation:halo 3s ease-in-out infinite}
@keyframes halo{0%,100%{transform:scale(1);opacity:.5}50%{transform:scale(1.08);opacity:.9}}
.idle #orb{background:radial-gradient(circle at 38% 32%,#3a3a52,#15151f 60%);
  box-shadow:0 0 40px rgba(80,80,120,.3)}
.speaking #orb{box-shadow:0 0 80px 20px rgba(255,80,80,.65),inset 0 0 60px rgba(0,0,0,.4)}
.processing #orb{animation:pulse 1s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}
#status{font-size:15px;letter-spacing:.3px;color:rgba(238,238,255,.55);min-height:20px;text-align:center}
#cap{max-width:560px;text-align:center;font-size:17px;line-height:1.5;color:#dfe2ff;min-height:52px}
#cap .me{color:#8aa0ff}
#cap .ai{color:#eef}
#btn{padding:16px 34px;border:none;border-radius:30px;font-size:17px;font-weight:600;color:#fff;
  background:linear-gradient(180deg,#e2233c,#a30f23);box-shadow:0 8px 24px rgba(208,20,42,.4);
  transition:opacity .2s;cursor:pointer}
#btn.stop{background:linear-gradient(180deg,#2a2a3a,#16161f);box-shadow:none;color:#cdd}
.bar{position:fixed;top:calc(14px + env(safe-area-inset-top));right:16px;
  font-size:11px;color:rgba(255,255,255,.3)}
</style></head>
<body class="idle">
<div class="bar">whisper · claude · edge</div>
<div id="wrap">
  <div id="orb"></div>
  <div id="status">нажми, чтобы начать разговор</div>
  <div id="cap"></div>
  <button id="btn">Поговорить</button>
</div>
<script>
const body=document.body,orb=document.getElementById('orb'),
      statusEl=document.getElementById('status'),
      cap=document.getElementById('cap'),btn=document.getElementById('btn');

const IN_RATE=16000;
const SILENCE_THRESH=0.012; // порог тишины (RMS)
const SILENCE_MS=1300;       // пауза → конец высказывания

let ws=null,actx=null,proc=null,micStream=null,running=false,playing=false;
let silenceTimer=null,hasSpoken=false;

function setState(s,txt){body.className=s;if(txt!=null)statusEl.textContent=txt;}

function downsample(buf,from,to){
  if(from===to)return buf;
  const ratio=from/to,len=Math.round(buf.length/ratio),out=new Float32Array(len);
  let o=0,i=0;
  while(o<len){const nx=Math.round((o+1)*ratio);let s=0,c=0;
    for(;i<nx&&i<buf.length;i++){s+=buf[i];c++;}out[o++]=c?s/c:0;}
  return out;
}
function f32toI16(f){
  const o=new Int16Array(f.length);
  for(let i=0;i<f.length;i++){const v=Math.max(-1,Math.min(1,f[i]));o[i]=v<0?v*32768:v*32767;}
  return o;
}

async function playMP3(data){
  if(!actx)return;
  playing=true;
  setState('speaking','говорит…');
  try{
    const decoded=await actx.decodeAudioData(data.slice(0));
    const src=actx.createBufferSource();
    src.buffer=decoded;src.connect(actx.destination);src.start();
    src.onended=()=>{
      playing=false;
      hasSpoken=false; // сбрасываем после ответа — не посылаем тишину как речь
      if(running)setState('listening','слушаю…');
    };
  }catch(e){
    playing=false;
    if(running)setState('listening','слушаю…');
  }
}

function sendEnd(){
  if(ws&&ws.readyState===1){
    ws.send(JSON.stringify({type:'utterance_end'}));
    setState('processing','обрабатываю…');
  }
  hasSpoken=false;
  silenceTimer=null;
}

async function start(){
  try{
    actx=new(window.AudioContext||window.webkitAudioContext)();
    await actx.resume();
    micStream=await navigator.mediaDevices.getUserMedia(
      {audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
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
      if(playing)return; // не слушаем пока говорит секретарь
      const buf=e.inputBuffer.getChannelData(0);
      let s=0;for(let i=0;i<buf.length;i++)s+=buf[i]*buf[i];
      const rms=Math.sqrt(s/buf.length);
      orb.style.transform='scale('+(1+Math.min(.4,rms*5))+')';
      if(ws&&ws.readyState===1){
        const ds=downsample(buf,actx.sampleRate,IN_RATE);
        ws.send(f32toI16(ds).buffer);
      }
      if(rms>SILENCE_THRESH){
        hasSpoken=true;
        if(silenceTimer){clearTimeout(silenceTimer);silenceTimer=null;}
      }else if(hasSpoken&&!silenceTimer){
        silenceTimer=setTimeout(sendEnd,SILENCE_MS);
      }
    };
    running=true;
    btn.textContent='Закончить';btn.classList.add('stop');
    setState('listening','слушаю…');
  };

  ws.onmessage=ev=>{
    if(ev.data instanceof ArrayBuffer){playMP3(ev.data);return;}
    let m;try{m=JSON.parse(ev.data);}catch(e){return;}
    if(m.type==='heard'){cap.innerHTML='<span class="me">'+m.text+'</span>';}
    else if(m.type==='say'){cap.innerHTML='<span class="ai">'+m.text+'</span>';}
    else if(m.type==='status'){statusEl.textContent=m.text;}
    else if(m.type==='done'&&!playing){setState('listening','слушаю…');}
    else if(m.type==='error'){setState('idle','ошибка: '+m.text);}
  };
  ws.onerror=()=>setState('idle','нет связи с сервером — проверь /setupvoicelive');
  ws.onclose=()=>{if(running){running=false;setState('idle','связь закрыта');reset();}};
}

function reset(){
  btn.textContent='Поговорить';btn.classList.remove('stop');
  orb.style.transform='';
}

function stop(){
  running=false;playing=false;
  if(silenceTimer){clearTimeout(silenceTimer);silenceTimer=null;}
  try{ws&&ws.send(JSON.stringify({type:'end'}))}catch(e){}
  try{ws&&ws.close()}catch(e){}
  try{proc&&proc.disconnect()}catch(e){}
  try{micStream&&micStream.getTracks().forEach(t=>t.stop())}catch(e){}
  setState('idle','нажми, чтобы начать разговор');reset();
}

btn.addEventListener('click',()=>{running?stop():start();});
</script></body></html>"""


if __name__ == "__main__":
    log.info("старт voicelive: порт=%s, режим=whisper+claude+edge-tts", PORT)
    web.run_app(make_app(), host="0.0.0.0", port=PORT,
                print=lambda *a: log.info(" ".join(map(str, a))))
