/* Детектор клопа для браузера: то же правило, что и в detector.py —
 * ищем тёмное пятно нужного размера, которое живёт несколько кадров и ПОЛЗЁТ.
 *
 * По одному кадру крошка, ворсинка и клоп неотличимы. Отличает движение:
 * клоп ползёт 1–4 см/с, крошка лежит. Всё считаем в миллиметрах, поэтому
 * настройка одна — сколько миллиметров простыни влезает в кадр по ширине.
 *
 * Каждому пятну в каждом кадре выставляется вероятность 0–100 %:
 *
 *     вероятность = внешность × движение
 *     внешность = размер тела и форма (овал, а не нитка)
 *     движение  = живучесть × (путь + скорость)
 *
 * Произведение выбрано не случайно: неподвижная крошка правильного размера
 * получает честный ноль, а не «половину за внешность». Тревога поднимается,
 * когда вероятность дотянула до порога (fireScore) — его и крутит ползунок
 * чувствительности.
 *
 * Работает на сыром массиве яркости, без зависимостей: на iPhone 6s должно
 * тянуть ~8 кадров в секунду при рабочем разрешении 640×360.
 */

export const DEFAULTS = {
  fovWidthMm: 90,         // ширина кадра на простыне, мм
  bugLenMin: 1.5,         // личинка
  bugLenMax: 9.0,         // взрослый клоп
  bugLenBest: [3.0, 6.0], // тело обычного взрослого — тут размер даёт полный балл
  minShortRatio: 0.25,    // тело овальное: отсекает волосы и складки
  minFill: 0.30,          // заполненность рамки: отсекает нитки и царапины
  darkThreshold: 18,      // насколько пятно темнее фона (0..255)
  bgAlpha: 0.02,          // скорость забывания фона в покое
  settleAlpha: 0.35,      // ускоренное забывание после шевеления
  warmupFrames: 20,       // кадры на построение фона
  maxChangeFrac: 0.02,    // >2% кадра изменилось — это ты повернулся
  settleFrames: 15,       // столько кадров после шевеления себе не верим
  minHits: 4,             // столько кадров пятно должно прожить на полный балл
  minTravelMm: 2.0,       // столько проползти на полный балл
  speedMinMmS: 0.2,       // медленнее — это не ползание, а дрейф фона
  speedBestMmS: [3, 45],  // обычный шаг клопа — тут скорость даёт полный балл
  speedMaxMmS: 130.0,     // быстрее — блик, мошка или рука проверяющего
  matchRadiusMm: 18.0,    // на столько пятно может сместиться за кадр
  missLimit: 5,           // столько кадров без пятна — трек закрыт
  fireScore: 0.70,        // с какой вероятности будить
};

export function toGray(rgba, out) {
  for (let i = 0, p = 0; p < out.length; i += 4, p++) {
    out[p] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8;
  }
  return out;
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

/** Трапеция: 0 вне [lo,hi], 1 внутри [bestLo,bestHi], плавный переход между. */
function band(v, lo, bestLo, bestHi, hi) {
  if (v <= lo || v >= hi) return 0;
  if (v >= bestLo && v <= bestHi) return 1;
  return v < bestLo ? (v - lo) / (bestLo - lo) : (hi - v) / (hi - bestHi);
}

export class BugDetector {
  constructor(width, height, cfg = {}) {
    this.cfg = { ...DEFAULTS, ...cfg };
    this.w = width;
    this.h = height;
    this.pxPerMm = width / this.cfg.fovWidthMm;
    const n = width * height;
    this.bg = null;
    this.blur = new Uint8Array(n);
    this.mask = new Uint8Array(n);
    this.tmp = new Uint8Array(n);
    this.labelStack = new Int32Array(n);
    this.tracks = [];
    this.frameIdx = 0;
    this.settleLeft = 0;
    this.changeFrac = 0;
    this.blobs = [];
    this.candidates = [];   // что сейчас в кадре, с вероятностью и разбором
    this.best = null;       // самый вероятный кандидат этого кадра
  }

  setFov(mm) {
    this.cfg.fovWidthMm = mm;
    this.pxPerMm = this.w / mm;
  }

  reset() {
    this.bg = null;
    this.tracks = [];
    this.candidates = [];
    this.best = null;
    this.frameIdx = 0;
    this.settleLeft = 0;
  }

  /** gray — Uint8Array яркости, ts — время в секундах. Вернёт находку или null. */
  feed(gray, ts) {
    const { w, h, cfg } = this;
    const n = w * h;
    this._boxBlur(gray, this.blur);

    if (!this.bg) {
      this.bg = new Float32Array(n);
      for (let i = 0; i < n; i++) this.bg[i] = this.blur[i];
    }
    this.frameIdx++;

    // Клоп ТЕМНЕЕ простыни, поэтому берём только потемнения: блик от экрана
    // или включённый свет дают посветление и насекомым не считаются.
    let changed = 0;
    for (let i = 0; i < n; i++) {
      const dark = this.bg[i] - this.blur[i];
      const on = dark > cfg.darkThreshold ? 1 : 0;
      this.mask[i] = on;
      changed += on;
    }
    this.changeFrac = changed / n;
    const disturbed = this.changeFrac > cfg.maxChangeFrac;

    if (disturbed) {
      // Ты повернулся, поправил одеяло или включили свет — кадру не верим,
      // треки сбрасываем, фон быстро переучиваем под новую позу.
      this.settleLeft = cfg.settleFrames;
      this.tracks = [];
      this.blobs = [];
      this.candidates = [];
      this.best = null;
    }

    const alpha = this.settleLeft > 0 ? cfg.settleAlpha : cfg.bgAlpha;
    for (let i = 0; i < n; i++) this.bg[i] += alpha * (this.blur[i] - this.bg[i]);

    if (this.settleLeft > 0) { this.settleLeft--; return null; }
    if (this.frameIdx <= cfg.warmupFrames || disturbed) return null;

    this._open(this.mask, this.tmp);
    this.blobs = this._blobs();
    return this._track(this.blobs, ts);
  }

  // ── обработка кадра ───────────────────────────────────────────────────────

  _boxBlur(src, dst) {
    const { w, h } = this;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        if (x === 0 || y === 0 || x === w - 1 || y === h - 1) { dst[i] = src[i]; continue; }
        dst[i] = (src[i - w - 1] + src[i - w] + src[i - w + 1] +
                  src[i - 1] + src[i] + src[i + 1] +
                  src[i + w - 1] + src[i + w] + src[i + w + 1]) / 9;
      }
    }
  }

  /** Морфологическое открытие 3×3: съедает одиночный шум матрицы. */
  _open(mask, tmp) {
    const { w, h } = this;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        if (x === 0 || y === 0 || x === w - 1 || y === h - 1) { tmp[i] = 0; continue; }
        tmp[i] = (mask[i - w - 1] && mask[i - w] && mask[i - w + 1] &&
                  mask[i - 1] && mask[i] && mask[i + 1] &&
                  mask[i + w - 1] && mask[i + w] && mask[i + w + 1]) ? 1 : 0;
      }
    }
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        if (x === 0 || y === 0 || x === w - 1 || y === h - 1) { mask[i] = 0; continue; }
        mask[i] = (tmp[i - w - 1] || tmp[i - w] || tmp[i - w + 1] ||
                   tmp[i - 1] || tmp[i] || tmp[i + 1] ||
                   tmp[i + w - 1] || tmp[i + w] || tmp[i + w + 1]) ? 1 : 0;
      }
    }
  }

  /** Связные пятна подходящего размера и формы. Всё лишнее отсекаем здесь. */
  _blobs() {
    const { w, h, cfg, mask, labelStack, pxPerMm } = this;
    const seen = this.tmp;
    seen.fill(0);
    const out = [];
    for (let i = 0, n = w * h; i < n; i++) {
      if (!mask[i] || seen[i]) continue;
      let top = 0, area = 0;
      let minX = w, maxX = 0, minY = h, maxY = 0;
      labelStack[top++] = i;
      seen[i] = 1;
      while (top > 0) {
        const p = labelStack[--top];
        const px = p % w, py = (p / w) | 0;
        area++;
        if (px < minX) minX = px;
        if (px > maxX) maxX = px;
        if (py < minY) minY = py;
        if (py > maxY) maxY = py;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const nx = px + dx, ny = py + dy;
            if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
            const q = ny * w + nx;
            if (mask[q] && !seen[q]) { seen[q] = 1; labelStack[top++] = q; }
          }
        }
      }
      const bw = maxX - minX + 1, bh = maxY - minY + 1;
      const longMm = Math.max(bw, bh) / pxPerMm;
      const shortMm = Math.min(bw, bh) / pxPerMm;
      const ratio = shortMm / longMm;
      const fill = area / (bw * bh);
      if (longMm < cfg.bugLenMin || longMm > cfg.bugLenMax) continue;   // крошка или рука
      if (ratio < cfg.minShortRatio) continue;                          // волос или складка
      if (fill < cfg.minFill) continue;                                 // нитка или царапина
      out.push({ x: minX + bw / 2, y: minY + bh / 2, lengthMm: longMm,
                 ratio, fill, box: [minX, minY, bw, bh] });
    }
    return out;
  }

  // ── слежение ──────────────────────────────────────────────────────────────

  _track(blobs, ts) {
    const radius = this.cfg.matchRadiusMm * this.pxPerMm;
    const free = blobs.slice();
    // Где пятна были в прошлом кадре — чтобы отличить «новое пятно» от «то же
    // самое, но прыгнувшее слишком далеко». Иначе быстрый объект каждый кадр
    // заводит новый трек, и разбор врёт про «стоит на месте».
    const prev = this.tracks.map((t) => ({ x: t.x, y: t.y }));
    for (const tr of this.tracks) {
      let best = null, bestD = radius;
      for (const b of free) {
        const d = Math.hypot(b.x - tr.x, b.y - tr.y);
        if (d < bestD) { best = b; bestD = d; }
      }
      if (!best) { tr.misses++; continue; }
      free.splice(free.indexOf(best), 1);
      tr.pathMm += bestD / this.pxPerMm;
      tr.x = best.x; tr.y = best.y;
      tr.box = best.box; tr.lengthMm = best.lengthMm;
      tr.ratio = best.ratio; tr.fill = best.fill;
      tr.lastTs = ts; tr.hits++; tr.misses = 0;
    }
    this.tracks = this.tracks.filter((t) => t.misses <= this.cfg.missLimit);
    for (const b of free) {
      let jumpMm = 0;
      let near = Infinity;
      for (const q of prev) near = Math.min(near, Math.hypot(b.x - q.x, b.y - q.y));
      if (near > radius && near < radius * 8) jumpMm = near / this.pxPerMm;
      this.tracks.push({ x: b.x, y: b.y, startX: b.x, startY: b.y, firstTs: ts,
                         lastTs: ts, lengthMm: b.lengthMm, ratio: b.ratio, fill: b.fill,
                         box: b.box, hits: 1, misses: 0, pathMm: 0, fired: false, jumpMm });
    }
    return this._evaluate();
  }

  /** Вероятность для одного трека плюс разбор, чего ему не хватает. */
  _rate(tr) {
    const cfg = this.cfg;
    const netMm = Math.hypot(tr.x - tr.startX, tr.y - tr.startY) / this.pxPerMm;
    const dt = Math.max(tr.lastTs - tr.firstTs, 1e-6);
    const speed = tr.hits > 1 ? tr.pathMm / dt : 0;

    const fSize = band(tr.lengthMm, cfg.bugLenMin, cfg.bugLenBest[0],
                       cfg.bugLenBest[1], cfg.bugLenMax);
    const fRatio = clamp01((tr.ratio - cfg.minShortRatio) / (0.55 - cfg.minShortRatio));
    const fFill = clamp01((tr.fill - cfg.minFill) / (0.70 - cfg.minFill));
    const fShape = 0.5 * fRatio + 0.5 * fFill;
    const fLife = Math.min(tr.hits / cfg.minHits, 1);
    const fTravel = Math.min(netMm / cfg.minTravelMm, 1);
    const fSpeed = band(speed, cfg.speedMinMmS, cfg.speedBestMmS[0],
                        cfg.speedBestMmS[1], cfg.speedMaxMmS);

    const look = 0.6 * fSize + 0.4 * fShape;
    const move = fLife * (0.5 * fTravel + 0.5 * fSpeed);
    const score = look * move;

    // Разбор пишем от самого слабого: именно он и держит вероятность внизу.
    const speedWord = speed >= cfg.speedMaxMmS
      ? `скорость ${speed.toFixed(0)} мм/с — выше потолка ${cfg.speedMaxMmS}`
      : speed <= cfg.speedMinMmS
        ? 'стоит на месте'
        : `скорость ${speed.toFixed(1)} мм/с`;
    // Пятно, прыгнувшее дальше радиуса сшивки, выглядит как новорождённый трек.
    // Говорим правду: дело не в том, что оно стоит, а в том, что оно летит.
    if (tr.hits <= 2 && tr.jumpMm > 0) {
      return { score, why: `прыгает ${tr.jumpMm.toFixed(0)} мм за кадр — ` +
                           `быстрее, чем детектор успевает сшить (предел ` +
                           `${cfg.matchRadiusMm} мм). Веди медленнее`,
               netMm, speed, fLife, fTravel, fSpeed, fSize, fShape };
    }
    const parts = [
      [`живёт ${tr.hits} из ${cfg.minHits} кадров`, fLife],
      [`проползло ${netMm.toFixed(1)} из ${cfg.minTravelMm} мм`, fTravel],
      [speedWord, fSpeed],
      [`тело ${tr.lengthMm.toFixed(1)} мм`, fSize],
      ['форма пятна', fShape],
    ].filter(([, f]) => f < 0.9).sort((a, b) => a[1] - b[1]);

    const why = parts.slice(0, 2)
      .map(([t, f]) => `${t} (${Math.round(f * 100)}%)`).join(', ');
    return { score, why, netMm, speed, fLife, fTravel, fSpeed, fSize, fShape };
  }

  /** Считаем всех, показываем всех, будим — того, кто дотянул до порога. */
  _evaluate() {
    const cfg = this.cfg;
    this.candidates = [];
    let hit = null;
    for (const tr of this.tracks) {
      const r = this._rate(tr);
      tr.score = r.score;
      this.candidates.push({
        box: tr.box, score: r.score, why: r.why, lengthMm: tr.lengthMm,
        travelMm: r.netMm, speedMmS: r.speed, frames: tr.hits, fired: tr.fired,
        jumpMm: tr.jumpMm || 0,
      });
      if (!tr.fired && r.score >= cfg.fireScore && !hit) {
        tr.fired = true;
        hit = { ts: tr.lastTs, box: tr.box, lengthMm: tr.lengthMm, travelMm: r.netMm,
                speedMmS: r.speed, frames: tr.hits, score: Math.round(r.score * 100) / 100,
                why: r.why };
      }
    }
    // При равной вероятности вперёд пускаем того, кто прыгнул: его разбор
    // объясняет причину, а «стоит на месте» у соседнего нуля — нет.
    this.candidates.sort((a, b) => (b.score - a.score) || (b.jumpMm - a.jumpMm));
    this.best = this.candidates[0] || null;
    return hit;
  }
}
