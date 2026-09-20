/* Проверка браузерного детектора на синтетических «простынях».
 * Запуск:  node test_detector.mjs
 * Те же семь сценариев, что и у питоновской версии: код другой — значит и
 * проверять надо заново, а не верить, что порт «наверняка такой же».
 */
import { BugDetector } from './detector.js';

const W = 640, H = 360, FPS = 10;
const FOV_MM = 90;
const PX_MM = W / FOV_MM;

function rng(seed) {                       // детерминированный шум, без сюрпризов
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sheet(seed = 7) {
  const g = new Uint8Array(W * H);
  const r = rng(seed);
  for (let i = 0; i < g.length; i++) g[i] = 200 + Math.round((r() - 0.5) * 10);
  for (const [cx, cy] of [[80, 60], [470, 270], [290, 200]]) disc(g, cx, cy, 5, 70);
  for (let x = 0; x < W; x++) {            // складка простыни
    const y = 310 + Math.round((x / W) * 12);
    g[y * W + x] = 150; g[(y + 1) * W + x] = 150;
  }
  return g;
}

function disc(g, cx, cy, r, v) {
  for (let y = cy - r; y <= cy + r; y++)
    for (let x = cx - r; x <= cx + r; x++)
      if ((x - cx) ** 2 + (y - cy) ** 2 <= r * r && x >= 0 && y >= 0 && x < W && y < H)
        g[y * W + x] = v;
}

function bug(g, cx, cy, lenMm = 5) {       // тело клопа: тёмный овал
  const a = (lenMm * PX_MM) / 2, b = a * 0.62;
  for (let y = Math.floor(cy - a); y <= cy + a; y++)
    for (let x = Math.floor(cx - a); x <= cx + a; x++)
      if (((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 <= 1 && x >= 0 && y >= 0 && x < W && y < H)
        g[y * W + x] = 55;
  return g;
}

/* Одеяло со складками: именно они дают пятна размером с клопа, когда ткань
   чуть смещается от дыхания. Генерируем один раз и сдвигаем целиком. */
const FOLD_W = W + 80, FOLD_H = H + 80;
const fold = new Float32Array(FOLD_W * FOLD_H);
{
  const r = rng(2024);
  for (let k = 0; k < 160; k++) {
    const cx = r() * FOLD_W, cy = r() * FOLD_H;
    const len = 6 + r() * 90, ang = r() * Math.PI, amp = 8 + r() * 34;
    for (let t = 0; t < len; t++) {
      const x = Math.round(cx + Math.cos(ang) * t), y = Math.round(cy + Math.sin(ang) * t);
      if (x >= 0 && y >= 0 && x < FOLD_W && y < FOLD_H) fold[y * FOLD_W + x] -= amp;
    }
  }
}

/** Кадр одеяла, сдвинутого на (dx,dy); cat — крупное тёмное пятно или null. */
function blanket(seed, dx, dy, cat) {
  const g = new Uint8Array(W * H), r = rng(seed);
  const ox = Math.round(40 + dx), oy = Math.round(40 + dy);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      g[y * W + x] = Math.max(0, Math.min(255,
        150 + fold[(y + oy) * FOLD_W + (x + ox)] + (r() - 0.5) * 20));
    }
  }
  if (cat) {
    for (let y = Math.floor(cat.cy - cat.ry); y <= cat.cy + cat.ry; y++)
      for (let x = Math.floor(cat.cx - cat.rx); x <= cat.cx + cat.rx; x++)
        if (x >= 0 && y >= 0 && x < W && y < H &&
            ((x - cat.cx) / cat.rx) ** 2 + ((y - cat.cy) / cat.ry) ** 2 <= 1)
          g[y * W + x] = Math.max(0, g[y * W + x] - 70);
  }
  return g;
}

function run(frames) {
  const det = new BugDetector(W, H, { fovWidthMm: FOV_MM });
  let hit = null;
  frames.forEach((f, i) => { const d = det.feed(f, i / FPS); if (d && !hit) hit = d; });
  return hit;
}

const warmup = (n = 30) => Array.from({ length: n }, () => sheet());

const CASES = [
  ['клоп ползёт', true, () => {
    const f = warmup(); let x = 180;
    for (let i = 0; i < 12; i++) { f.push(bug(sheet(), x, 160)); x += 2 * PX_MM; }
    return f;
  }],
  ['личинка ползёт', true, () => {
    const f = warmup(); let x = 180;
    for (let i = 0; i < 16; i++) { f.push(bug(sheet(), x, 160, 2.2)); x += 0.8 * PX_MM; }
    return f;
  }],
  ['тихая ночь', false, () => warmup(200)],
  ['пополз, замер, пополз', true, () => {   // так они и ходят на самом деле
    const f = warmup();
    let x = 180;
    for (let b = 0; b < 3; b++) {
      for (let i = 0; i < 2; i++) { f.push(bug(sheet(), x, 160)); x += 2 * PX_MM; }
      for (let i = 0; i < 40; i++) f.push(bug(sheet(), x, 160));   // стоит 4 с
    }
    return f;
  }],
  ['кот прошёл по кровати', false, () => {
    const f = [];
    for (let i = 0; i < 30; i++) f.push(blanket(i, 0, 0, null));
    for (let i = 0; i < 60; i++) {                 // кот идёт через весь кадр
      f.push(blanket(100 + i, 0, 0, { cx: (i / 60) * W, cy: 180, rx: 70, ry: 45 }));
    }
    for (let i = 0; i < 30; i++) f.push(blanket(200 + i, 0, 0, null));
    return f;
  }],
  ['одеяло дышит', false, () => {
    const f = [];
    for (let i = 0; i < 240; i++) {                // ±1.5 точки с периодом 4 с
      const t = i / FPS;
      f.push(blanket(300 + i, Math.sin(t * Math.PI / 2) * 1.5,
                              Math.cos(t * Math.PI / 2) * 1.0, null));
    }
    return f;
  }],
  ['клоп на дышащем одеяле', true, () => {
    const f = [];
    for (let i = 0; i < 40; i++) {
      const t = i / FPS;
      f.push(blanket(400 + i, Math.sin(t * Math.PI / 2) * 1.5, 0, null));
    }
    let x = 200;
    for (let i = 0; i < 24; i++) {                 // ползёт сам, пока ткань дышит
      const t = (40 + i) / FPS;
      const g = blanket(500 + i, Math.sin(t * Math.PI / 2) * 1.5, 0, null);
      const a = 2.5 * PX_MM, b = a * 0.62;
      for (let y = Math.floor(120 - a); y <= 120 + a; y++)
        for (let xx = Math.floor(x - a); xx <= x + a; xx++)
          if (((xx - x) / a) ** 2 + ((y - 120) / b) ** 2 <= 1 &&
              xx >= 0 && y >= 0 && xx < W && y < H)
            g[y * W + xx] = Math.max(0, g[y * W + xx] - 60);
      f.push(g); x += 1.2 * PX_MM;
    }
    return f;
  }],
  ['упавшая крошка', false, () => {
    const f = warmup();
    for (let i = 0; i < 40; i++) f.push(bug(sheet(), 330, 170));
    return f;
  }],
  ['спящий повернулся', false, () => {
    const f = warmup();
    for (let i = 0; i < 30; i++) {
      const g = sheet();
      for (let y = 0; y < H; y++) for (let x = 0; x < W / 2; x++) g[y * W + x] *= 0.55;
      f.push(g);
    }
    return f;
  }],
  ['крупная моль', false, () => {
    const f = warmup(); let x = 180;
    for (let i = 0; i < 12; i++) { f.push(bug(sheet(), x, 160, 25)); x += 4 * PX_MM; }
    return f;
  }],
  ['быстрая тень', false, () => {          // мошка, штора, блик — клоп так не бегает
    const f = warmup();
    const step = (250 / FPS) * PX_MM;      // 25 см/с, втрое выше потолка
    for (let x = 30; x < W - 30; x += step) f.push(bug(sheet(), x, 160));
    return f;
  }],
  ['волос на простыне', false, () => {
    const f = warmup(); let x = 180;
    for (let i = 0; i < 12; i++) {
      const g = sheet();
      for (let k = 0; k < 40; k++) { const px = x + k, py = 150 + ((k * 22) / 40) | 0;
        if (px < W) g[py * W + px] = 60; }
      f.push(g); x += 8;
    }
    return f;
  }],
];

/* Отдельная проверка: замерший клоп не должен пропадать с экрана. Раньше фон
 * съедал его за 13 секунд, и пятно исчезало из кандидатов совсем. */
function checkStaysVisible() {
  const det = new BugDetector(W, H, { fovWidthMm: FOV_MM });
  warmup().forEach((f, i) => det.feed(f, i / FPS));
  let x = 200;
  for (let i = 0; i < 4; i++) { det.feed(bug(sheet(), x, 160), (30 + i) / FPS); x += 2 * PX_MM; }
  let goneAt = null;
  for (let i = 0; i < 400 && goneAt === null; i++) {
    det.feed(bug(sheet(), x, 160), (34 + i) / FPS);
    if (!det.candidates.length) goneAt = i / FPS;
  }
  const ok = goneAt === null;
  console.log(` ${ok ? '✓' : '✗'} ${'замерший не пропадает'.padEnd(22)} ` +
    (ok ? 'виден все 50 с простоя' : `ПРОПАЛ через ${goneAt.toFixed(1)} с`));
  return ok ? 0 : 1;
}

let bad = 0;
for (const [name, want, build] of CASES) {
  const hit = run(build());
  const ok = !!hit === want;
  bad += ok ? 0 : 1;
  const detail = hit
    ? `тело ~${hit.lengthMm.toFixed(1)} мм, проползло ${hit.travelMm.toFixed(1)} мм, ` +
      `${hit.speedMmS.toFixed(0)} мм/с, уверенность ${Math.round(hit.score * 100)}%`
    : 'тихо';
  const miss = ok ? '' : `   ← ожидали ${want ? 'тревогу' : 'тишину'}`;
  console.log(` ${ok ? '✓' : '✗'} ${name.padEnd(22)} ${detail}${miss}`);
}
bad += checkStaysVisible();
console.log(bad ? `\nПровалено сценариев: ${bad}` : '\nВсе сценарии прошли.');
process.exit(bad ? 1 : 0);
