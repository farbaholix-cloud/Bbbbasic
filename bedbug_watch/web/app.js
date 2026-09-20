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
const TEST_COOLDOWN_MS = 5_000;        // в режиме проверки — чтобы не ждать полторы минуты
const JOURNAL_KEY = 'bedbug.journal';
const JOURNAL_CAP = 60;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SETTINGS_KEY = 'bedbug.settings';   // один телефон — один пост, ключ общий
let POST = 'без имени';

let detector, stream, video, ctx, imgData, gray;
let running = false, wakeLock = null;
let frames = 0, alerts = 0, lastAlert = -1e9, lastFrameAt = 0;
let cooldownMs = COOLDOWN_MS, muffled = 0;   // muffled — когда поймал, но пауза

// ── настройки ────────────────────────────────────────────────────────────────

function loadSettings() {
  const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
  // Что пришло в ссылке — главнее сохранённого: иначе телефон, на котором уже
  // дежурили, молча оставит старое имя поста, и в журнале смешаются два места.
  $('post-input').value = params.get('post') || saved.post || '';
  $('testmode').checked = !!saved.testmode;
  $('fov').value = params.get('fov') || saved.fov || 90;
  $('sens').value = saved.sens || 18;
  $('fire').value = saved.fire || 70;
  $('tg-token').value = saved.token || '';
  $('tg-chat').value = saved.chat || '';
  updateSensLabel();
  updateFireLabel();
  updateFovLabel();
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({
    post: $('post-input').value.trim(),
    testmode: $('testmode').checked,
    fov: +$('fov').value, sens: +$('sens').value, fire: +$('fire').value,
    token: $('tg-token').value.trim(), chat: $('tg-chat').value.trim(),
  }));
}

/* Самая дорогая ошибка установки — повесить телефон слишком высоко. На кадре
 * шириной 800 мм клоп занимает 4 точки: это ниже всякого разрешения, и сторож
 * честно не увидит ничего. Пусть об этом говорит экран, а не тишина ночью. */
function updateFovLabel() {
  const fov = +$('fov').value || 1;
  const bugPx = (5 * PROC_W) / fov;
  const el = $('fov-hint');
  const n = Math.round(bugPx);
  const dots = `~${n} ${plural(n, 'точку', 'точки', 'точек')}`;
  if (bugPx >= 12) {
    el.textContent = `Клоп займёт ${dots} — с запасом.`;
  } else if (bugPx >= 8) {
    el.textContent = `Клоп займёт ${dots} — впритык. ` +
                     'Слабые проходы будет пропускать, опусти камеру ниже.';
  } else {
    el.textContent = `Клоп займёт ${dots} — этого мало, ` +
                     'детектор его не увидит. Нужен кадр не шире 400 мм: ' +
                     'опусти камеру к самой простыне.';
  }
  if (detector) detector.setFov(fov);
}

function updateSensLabel() {
  const v = +$('sens').value;
  $('sens-label').textContent = v <= 14 ? 'ловит еле заметные'
    : v >= 24 ? 'только явно тёмные' : 'обычный';
}

/* Порог решает, с какой вероятности будить. Это и есть та самая
 * чувствительность: контрастом выше решается лишь, что вообще попадёт
 * в кандидаты, а разбудит тебя именно этот ползунок. */
function updateFireLabel() {
  const v = +$('fire').value;
  $('fire-label').textContent = v + '%';
  $('fire-hint').textContent = v <= 45
    ? 'Очень чутко: разбудит и сомнительное пятно. Для проверки днём, не для ночи.'
    : v >= 85 ? 'Строго: разбудит только безупречного клопа, слабые проходы пропустит.'
    : 'Разумно: клоп в норме набирает 90–100%, лежачая крошка — единицы.';
  if (detector) detector.cfg.fireScore = v / 100;   // крутится прямо во время дежурства
}

// ── звук ─────────────────────────────────────────────────────────────────────

/* Тревога — цвириканье птицы: девятисекундная петля, входящая мягко.
 * Ночью важнее не напугать, а разбудить, поэтому громкость поднимается сама:
 * первые секунды еле слышно, а если ты не проснулся — за полминуты выходит на
 * полную. Файл может не загрузиться (нет сети в три часа ночи), и тогда
 * включается запасной вой на осцилляторе: сигнализация не имеет права молчать.
 *
 * Имя переменной нарочно без названия звука: поменять птицу на что угодно
 * другое — это правка одной строки ниже, а не переименование половины файла.
 */
const ALARM_SOUND_URL = 'sound/birds.mp3';
const GENTLE_LEVEL = 0.30;    // громкость, до которой доходим мягко
const GENTLE_S = 3.0;         // за сколько секунд
const FULL_S = 30.0;          // и за сколько выходим на полную, если не проснулся

let audio = null, soundRaw = null, soundBuf = null;
let sirenSrc = null, sirenGain = null, beeper = null;

// Байты тянем сразу при открытии страницы: вечером сеть обычно есть, а ночью
// может не быть. Раскодируем позже — для этого нужен звуковой контекст.
fetch(ALARM_SOUND_URL).then((r) => (r.ok ? r.arrayBuffer() : null))
  .then((b) => { soundRaw = b; }).catch(() => { soundRaw = null; });

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
  decodeAlarmSound();
}

function decodeAlarmSound() {
  if (soundBuf || !soundRaw || !audio) return;
  const raw = soundRaw.slice(0);          // decodeAudioData забирает буфер себе
  try {
    const p = audio.decodeAudioData(raw, (b) => { soundBuf = b; }, () => {});
    if (p && p.then) p.then((b) => { soundBuf = b; }, () => {});
  } catch { /* останется запасной вой */ }
}

/** Вой на осцилляторе — запасной вариант, если файл не загрузился. */
function startBeeper() {
  const osc = audio.createOscillator();
  const sweep = audio.createOscillator();
  const depth = audio.createGain();
  const vol = audio.createGain();
  osc.type = 'sawtooth';
  osc.frequency.value = 760;
  sweep.frequency.value = 3.2;
  depth.gain.value = 320;
  vol.gain.value = 0.85;
  sweep.connect(depth).connect(osc.frequency);
  osc.connect(vol).connect(audio.destination);
  osc.start(); sweep.start();
  return { osc, sweep };
}

/** fast — для дневной проверки: там нужно услышать сразу, а не через полминуты. */
function sirenOn(fast = false) {
  if (!audio || sirenSrc || beeper) return;
  audio.resume();
  decodeAlarmSound();
  if (!soundBuf) { beeper = startBeeper(); return; }

  const src = audio.createBufferSource();
  src.buffer = soundBuf;
  src.loop = true;
  const g = audio.createGain();
  const now = audio.currentTime;
  const rise = fast ? 1.0 : GENTLE_S;
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(fast ? 0.8 : GENTLE_LEVEL, now + rise);
  if (!fast) g.gain.exponentialRampToValueAtTime(1.0, now + FULL_S);
  src.connect(g).connect(audio.destination);
  src.start();
  sirenSrc = src; sirenGain = g;
}

function sirenOff() {
  if (beeper) { beeper.osc.stop(); beeper.sweep.stop(); beeper = null; }
  if (!sirenSrc) return;
  const src = sirenSrc, g = sirenGain;
  sirenSrc = null; sirenGain = null;
  const now = audio.currentTime;
  // Обрыв на полуслове щёлкает — уводим за треть секунды.
  g.gain.cancelScheduledValues(now);
  g.gain.setValueAtTime(Math.max(g.gain.value, 0.0001), now);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
  try { src.stop(now + 0.4); } catch { /* уже остановлен */ }
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
    fireScore: +$('fire').value / 100,
  });

  frames = 0; alerts = 0; lastAlert = -1e9; muffled = 0; running = true;
  cooldownMs = $('testmode').checked ? TEST_COOLDOWN_MS : COOLDOWN_MS;
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
  // Рамки рисуем до тревоги — чтобы они попали в миниатюру улики, а счётчики
  // после неё, иначе на экране они отстают от происходящего на кадр.
  paintBoxes();

  if (hit && now - lastAlert > cooldownMs) {
    lastAlert = now;
    alerts++;
    fire(hit);
  } else if (hit) {
    muffled = now;          // поймал, но ещё идёт пауза — об этом надо сказать вслух
  }

  paintStats();
  paintWhy(now);
}

/* Рядом с каждым пятном пишем его вероятность. Без цифры рамка ничего не
 * объясняет: непонятно, это «почти клоп» или «мимо на порядок». */
function paintBoxes() {
  const fire = detector.cfg.fireScore;
  ctx.font = '600 13px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'bottom';
  for (const c of detector.candidates) {
    const [x, y, w, h] = c.box;
    const hot = c.score >= fire;
    ctx.lineWidth = hot ? 3 : 2;
    ctx.strokeStyle = hot ? '#ff2b2b'
                          : `rgba(255,120,120,${(0.3 + 0.6 * c.score).toFixed(2)})`;
    const pad = hot ? 8 : 4;
    ctx.strokeRect(x - pad, y - pad, w + pad * 2, h + pad * 2);

    const text = Math.round(c.score * 100) + '%';
    const tw = ctx.measureText(text).width;
    let tx = x - pad, ty = y - pad - 3;
    if (ty < 16) ty = y + h + pad + 16;               // у верхнего края — подпись снизу
    if (tx + tw + 8 > PROC_W) tx = PROC_W - tw - 8;
    ctx.fillStyle = hot ? '#ff2b2b' : 'rgba(0,0,0,.65)';
    ctx.fillRect(tx - 3, ty - 13, tw + 6, 15);
    ctx.fillStyle = hot ? '#ffffff' : `rgba(255,160,160,${(0.5 + 0.5 * c.score).toFixed(2)})`;
    ctx.fillText(text, tx, ty);
  }
}

/* Самый частый вопрос к такой штуке — «вижу рамку, почему молчишь». Пока
 * причина не написана на экране, отладка превращается в гадание. */
function paintWhy(now) {
  const left = Math.ceil((cooldownMs - (now - lastAlert)) / 1000);
  const best = detector.best;
  if (muffled && now - muffled < 3000 && left > 0) {
    $('why').textContent = `Поймал, но пауза после прошлой тревоги — ещё ${left} с`;
    return;
  }
  // Кот, плечо или поехавшее одеяло — пусть будет видно, что сторож не спит,
  // а сознательно молчит, и по какой причине.
  if (now / 1000 < detector.vetoUntil) {
    $('why').textContent = `Молчу: ${detector.vetoWhy}`;
    return;
  }
  if (!best) { $('why').textContent = ''; return; }
  const pct = Math.round(best.score * 100);
  $('why').textContent = best.score >= detector.cfg.fireScore
    ? `${pct}% — этого хватает, поднимаю тревогу`
    : `${pct}% — не хватает: ${best.why || 'чуть-чуть до порога'}`;
}

function paintStats() {
  $('s-frames').textContent = frames;
  $('s-alerts').textContent = alerts;
  $('s-blobs').textContent = detector.candidates.length;
  $('s-best').textContent = detector.best
    ? Math.round(detector.best.score * 100) + '%' : '—';
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
$('fire').oninput = updateFireLabel;
$('fov').oninput = updateFovLabel;
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

// ── самопроверка ─────────────────────────────────────────────────────────────

/* Отвечает на вопрос «а этот браузер вообще потянет?» прямо на телефоне.
 * Главное здесь — вторая проверка: браузеры с защитой от слежки (Brave и
 * подобные) подмешивают шум в чтение кадра с canvas, а детектор читает кадры
 * именно так. Если шум есть, сторож начнёт видеть клопов там, где их нет. */
/** Русские окончания: 1 уровень, 2 уровня, 5 уровней. */
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  return b === 1 ? one : many;
}

async function runSelfTest() {
  const out = $('selftest-out');
  const rows = [];
  out.classList.remove('hidden');
  out.innerHTML = 'Проверяю…';

  // 1. Чтение кадра без подмешанного шума
  const c = document.createElement('canvas');
  c.width = 64; c.height = 1;
  const cx = c.getContext('2d', { willReadFrequently: true });
  for (let i = 0; i < 64; i++) { cx.fillStyle = `rgb(${i * 4},${i * 4},${i * 4})`; cx.fillRect(i, 0, 1, 1); }
  const px = cx.getImageData(0, 0, 64, 1).data;
  let dev = 0;
  for (let i = 0; i < 64; i++) dev = Math.max(dev, Math.abs(px[i * 4] - i * 4));
  rows.push(dev === 0
    ? ['✓', 'Кадр читается точно, без подмешанного шума']
    : ['✗', `Браузер искажает кадр на ${dev} ${plural(dev, 'уровень', 'уровня', 'уровней')} ` +
            'яркости — это защита от ' +
            'слежки. Выключи её для этого сайта или открой страницу в Safari']);

  // 2. Камера: даёт ли она кадры и какого размера
  let cam = null;
  try {
    cam = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' },
               width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
    const t = cam.getVideoTracks()[0].getSettings();
    const v = document.createElement('video');
    v.srcObject = cam; v.muted = true; v.playsInline = true;
    v.setAttribute('playsinline', ''); await v.play();
    await new Promise((r) => setTimeout(r, 600));
    const pc = document.createElement('canvas');
    pc.width = 160; pc.height = 90;
    const pctx = pc.getContext('2d', { willReadFrequently: true });
    pctx.drawImage(v, 0, 0, 160, 90);
    const d = pctx.getImageData(0, 0, 160, 90).data;
    let mean = 0;
    for (let i = 0; i < d.length; i += 4) mean += d[i];
    mean /= d.length / 4;
    rows.push(mean > 4
      ? ['✓', `Камера даёт картинку, ${t.width}×${t.height}`]
      : ['✗', 'Камера открылась, но кадр чёрный — сними крышку или добавь света']);
    if (t.width && t.width < 1280) {
      rows.push(['!', `Разрешение всего ${t.width} точек по ширине: масштаб ` +
                      'мельче, клопа разглядеть труднее']);
    }
  } catch (e) {
    rows.push(['✗', 'Камера не открылась: ' + e.name +
                    '. Разреши доступ в настройках браузера']);
  } finally {
    cam?.getTracks().forEach((t) => t.stop());
  }

  // 3. Wake Lock: удержит ли страница экран
  rows.push('wakeLock' in navigator
    ? ['✓', 'Страница сможет держать экран включённым']
    : ['!', 'Этот браузер экран не удержит — поставь Автоблокировку на «Никогда»']);

  render(rows, out);

  // 4. Звук — последним, потому что ответить может только человек
  if (!audio) unlockAudio();
  sirenOn(true);                         // в проверке — сразу в полный голос
  await new Promise((r) => setTimeout(r, 3500));
  sirenOff();
  rows.push(confirm('Слышал птицу?')
    ? ['✓', (soundBuf ? 'Птица слышна'
                      : 'Звук слышен (файл не загрузился — играет запасной вой)')
             + ' — разбудит']
    : ['✗', 'Звука не было: переключатель звонка НЕ на беззвучном, громкость на максимум']);

  const bad = rows.filter((r) => r[0] === '✗').length;
  rows.push(bad
    ? ['', `<b>Дежурить пока нельзя: сначала почини ${bad} ` +
           `${plural(bad, 'пункт', 'пункта', 'пунктов')} выше.</b>`]
    : ['', '<b>Всё готово. Можно дежурить.</b>']);
  render(rows, out);
}

function render(rows, out) {
  out.innerHTML = rows.map(([m, t]) => (m ? `${m} ${t}` : t)).join('<br>');
}

$('selftest').onclick = runSelfTest;
