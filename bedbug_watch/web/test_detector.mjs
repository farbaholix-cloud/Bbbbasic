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
console.log(bad ? `\nПровалено сценариев: ${bad}` : '\nВсе сценарии прошли.');
process.exit(bad ? 1 : 0);
