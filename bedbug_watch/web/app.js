/* Ночной сторож в браузере телефона.
 *
 * Весь разбор кадров идёт прямо на телефоне: видео никуда не уходит, интернет
 * нужен только если включён Telegram. Один телефон — один пост наблюдения:
 * имя вписывается на самом телефоне и запоминается, так что ссылка на все
 * телефоны одна. Можно подставить и из ссылки: index.html?post=Изголовье&fov=90
 *
 * Подводные камни iOS, из-за которых это ломается чаще всего:
 *   • боковой переключатель «беззвучно» глушит ЛЮБОЙ звук со страницы —
 *     поэтому кроме сирены тревога мигает во весь экран;
 *   • камера останавливается, когда экран гаснет или уходишь из Safari, —
 *     держим Wake Lock, а на старых iOS просим выключить автоблокировку;
 *   • и камеру, и звук браузер даёт только по нажатию пальцем, поэтому
 *     всё включается одной кнопкой «НАЧАТЬ ДЕЖУРСТВО».
 */
import { BugDetector, toGray } from './detector.js';

const PROC_W = 640, PROC_H = 360;      // рабочее разрешение: тянет даже iPhone 6s
const TARGET_FPS = 8;
const COOLDOWN_MS = 90_000;            // пауза между тревогами
const JOURNAL_KEY = 'bedbug.journal';
const JOURNAL_CAP = 60;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SETTINGS_KEY = 'bedbug.settings';   // один телефон — один пост, ключ общий
let POST = 'без имени';

let detector, stream, video, ctx, imgData, gray;
let running = false, wakeLock = null;
let frames = 0, alerts = 0, lastAlert = -1e9, lastFrameAt = 0;
let audio = null, siren = null;

// ── настройки ────────────────────────────────────────────────────────────────

function loadSettings() {
  const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
  $('post-input').value = saved.post || params.get('post') || '';
  $('fov').value = saved.fov || params.get('fov') || 90;
  $('sens').value = saved.sens || 18;
  $('tg-token').value = saved.token || '';
  $('tg-chat').value = saved.chat || '';
  updateSensLabel();
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({
    post: $('post-input').value.trim(),
    fov: +$('fov').value, sens: +$('sens').value,
    token: $('tg-token').value.trim(), chat: $('tg-chat').value.trim(),
  }));
}

function updateSensLabel() {
  const v = +$('sens').value;
  $('sens-label').textContent = v <= 14 ? 'высокая — ловит слабый контраст'
    : v >= 24 ? 'низкая — только явные пятна' : 'обычная';
}

// ── звук ─────────────────────────────────────────────────────────────────────

/** Разбудить аудио нужно тем же касанием, что включает камеру, — иначе iOS
 *  откажет в звуке посреди ночи, когда касаться уже некому. */
function unlockAudio() {
  audio = new (window.AudioContext || window.webkitAudioContext)();
  const blip = audio.createOscillator();
  const g = audio.createGain();
  g.gain.value = 0.0001;
  blip.connect(g).connect(audio.destination);
  blip.start();
  blip.stop(audio.currentTime + 0.05);
}

function sirenOn() {
  if (!audio || siren) return;
  audio.resume();
  const osc = audio.createOscillator();
  const sweep = audio.createOscillator();
  const depth = audio.createGain();
  const vol = audio.createGain();
  osc.type = 'sawtooth';
  osc.frequency.value = 760;
  sweep.frequency.value = 3.2;              // вой «вверх-вниз», а не ровный писк
  depth.gain.value = 320;
  vol.gain.value = 0.85;
  sweep.connect(depth).connect(osc.frequency);
  osc.connect(vol).connect(audio.destination);
  osc.start(); sweep.start();
  siren = { osc, sweep };
}

function sirenOff() {
  if (!siren) return;
  siren.osc.stop(); siren.sweep.stop();
  siren = null;
}

// ── камера ───────────────────────────────────────────────────────────────────

async function startCamera() {
  stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: 'environment' },
             width: { ideal: 1920 }, height: { ideal: 1080 } },
    audio: false,
  });
  video = document.createElement('video');
  video.srcObject = stream;
  video.muted = true;
  video.playsInline = true;
  video.setAttribute('playsinline', '');
  await video.play();
}

async function keepAwake() {
  try {
    wakeLock = await navigator.wakeLock.request('screen');
  } catch {
    // iOS 15 и старше Wake Lock не умеют — там спасает «Автоблокировка: Никогда»
  }
}

document.addEventListener('visibilitychange', () => {
  if (running && document.visibilityState === 'visible') keepAwake();
});

// ── дежурство ────────────────────────────────────────────────────────────────

async function start() {
  POST = $('post-input').value.trim() || 'без имени';
  saveSettings();
  document.title = POST === 'без имени' ? 'Ночной сторож' : `Сторож: ${POST}`;
  try {
    await startCamera();
  } catch (e) {
    alert('Камера не открылась: ' + e.message +
          '\n\nСтраница должна быть на https, и Safari должен спросить разрешение.');
    return;
  }
  unlockAudio();
  keepAwake();

  const canvas = $('preview');
  canvas.width = PROC_W; canvas.height = PROC_H;
  ctx = canvas.getContext('2d', { willReadFrequently: true });
  gray = new Uint8Array(PROC_W * PROC_H);
  detector = new BugDetector(PROC_W, PROC_H, {
    fovWidthMm: +$('fov').value,
    darkThreshold: +$('sens').value,
  });

  frames = 0; alerts = 0; lastAlert = -1e9; running = true;
  $('setup').classList.add('hidden');
  $('journal').classList.add('hidden');
  $('watch').classList.remove('hidden');
  $('watch-title').textContent = `Дежурю: ${POST}`;
  $('s-scale').textContent = (PROC_W / +$('fov').value).toFixed(1) + ' px/мм';
  requestAnimationFrame(tick);
}

function tick(now) {
  if (!running) return;
  requestAnimationFrame(tick);
  if (now - lastFrameAt < 1000 / TARGET_FPS) return;   // прореживаем до рабочей частоты
  lastFrameAt = now;

  ctx.drawImage(video, 0, 0, PROC_W, PROC_H);
  imgData = ctx.getImageData(0, 0, PROC_W, PROC_H);
  toGray(imgData.data, gray);

  const hit = detector.feed(gray, now / 1000);
  frames++;
  paintBoxes(hit);
  paintStats();

  if (hit && now - lastAlert > COOLDOWN_MS) {
    lastAlert = now;
    alerts++;
    fire(hit);
  }
}

function paintBoxes(hit) {
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(255,90,90,.55)';
  for (const b of detector.blobs) ctx.strokeRect(b.box[0] - 4, b.box[1] - 4,
                                                 b.box[2] + 8, b.box[3] + 8);
  if (hit) {
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#ff2b2b';
    ctx.strokeRect(hit.box[0] - 8, hit.box[1] - 8, hit.box[2] + 16, hit.box[3] + 16);
  }
}

function paintStats() {
  $('s-frames').textContent = frames;
  $('s-alerts').textContent = alerts;
  $('s-blobs').textContent = detector.blobs.length;
  $('s-noise').textContent = (detector.changeFrac * 100).toFixed(2) + '%';
  const warming = detector.frameIdx <= detector.cfg.warmupFrames;
  const shaky = detector.changeFrac > detector.cfg.maxChangeFrac;
  $('watch-sub').textContent = warming ? 'Учу фон — не шевели камеру…'
    : shaky ? 'Слишком много движения: камера дрожит или моргает свет'
    : 'Смотрю. Спокойной ночи.';
}

// ── тревога ──────────────────────────────────────────────────────────────────

function fire(hit) {
  const when = new Date();
  const detail = `тело ~${hit.lengthMm.toFixed(1)} мм, проползло ` +
                 `${hit.travelMm.toFixed(1)} мм со скоростью ${hit.speedMmS.toFixed(0)} мм/с`;
  sirenOn();
  $('alarm-detail').textContent = detail;
  $('alarm-post').textContent = `${POST}, ${when.toLocaleTimeString('ru-RU')}`;
  $('alarm').classList.remove('hidden');

  const thumb = cutThumb(hit.box);
  remember({ ts: when.toISOString(), post: POST, detail, score: hit.score, thumb });
  sendTelegram(`🛏 ${POST}: движение на простыне в ` +
               `${when.toLocaleTimeString('ru-RU')}\n${detail}`);
}

/** Кусок кадра вокруг находки: точка на полном кадре никого не убеждает. */
function cutThumb(box) {
  const pad = 40;
  const x = Math.max(0, box[0] - pad), y = Math.max(0, box[1] - pad);
  const w = Math.min(PROC_W - x, box[2] + pad * 2);
  const h = Math.min(PROC_H - y, box[3] + pad * 2);
  const c = document.createElement('canvas');
  c.width = 180; c.height = Math.round((h / w) * 180);
  c.getContext('2d').drawImage($('preview'), x, y, w, h, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.6);
}

function sendTelegram(text) {
  const { token, chat } = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
  if (!token || !chat) return;
  $('preview').toBlob((blob) => {
    const fd = new FormData();
    fd.append('chat_id', chat);
    fd.append('caption', text);
    fd.append('photo', blob, 'bug.jpg');
    fetch(`https://api.telegram.org/bot${token}/sendPhoto`, { method: 'POST', body: fd })
      .catch(() => {                        // ночью сеть отваливается — хотя бы текстом
        fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chat, text }),
        }).catch(() => {});
      });
  }, 'image/jpeg', 0.7);
}

// ── журнал ───────────────────────────────────────────────────────────────────

function remember(entry) {
  const log = JSON.parse(localStorage.getItem(JOURNAL_KEY) || '[]');
  log.unshift(entry);
  try {
    localStorage.setItem(JOURNAL_KEY, JSON.stringify(log.slice(0, JOURNAL_CAP)));
  } catch {
    localStorage.setItem(JOURNAL_KEY, JSON.stringify(log.slice(0, 10)));  // память кончилась
  }
}

function showJournal() {
  const log = JSON.parse(localStorage.getItem(JOURNAL_KEY) || '[]');
  $('events').innerHTML = log.map((e) => {
    const d = new Date(e.ts);
    return `<div class="event"><img src="${e.thumb}" alt="">
      <div><div class="when">${d.toLocaleString('ru-RU')} · ${e.post}</div>
      <div class="what">${e.detail} · уверенность ${Math.round(e.score * 100)}%</div>
      </div></div>`;
  }).join('') || '<p class="sub">Пока тихо — ни одной сработки.</p>';
  $('journal-sub').textContent = log.length
    ? `Сработок: ${log.length}. Где их больше всего — там и гнездо.` : '';
  $('setup').classList.add('hidden');
  $('journal').classList.remove('hidden');
}

// ── управление ───────────────────────────────────────────────────────────────

function stop() {
  running = false;
  sirenOff();
  stream?.getTracks().forEach((t) => t.stop());
  wakeLock?.release().catch(() => {});
  wakeLock = null;
  $('watch').classList.add('hidden');
  $('alarm').classList.add('hidden');
  $('setup').classList.remove('hidden');
}

$('start').onclick = start;
$('stop').onclick = stop;
$('sens').oninput = updateSensLabel;
$('alarm-off').onclick = () => { sirenOff(); $('alarm').classList.add('hidden'); };
$('show-journal').onclick = showJournal;
$('journal-back').onclick = () => {
  $('journal').classList.add('hidden');
  $('setup').classList.remove('hidden');
};
$('journal-clear').onclick = () => {
  if (confirm('Стереть журнал целиком?')) { localStorage.removeItem(JOURNAL_KEY); showJournal(); }
};

loadSettings();
$('post-name').textContent = $('post-input').value ? `· ${$('post-input').value}` : '';
$('post-input').oninput = () => {
  $('post-name').textContent = $('post-input').value ? `· ${$('post-input').value}` : '';
};
