/* Детектор клопа для браузера: то же правило, что и в detector.py —
 * ищем тёмное пятно нужного размера, которое живёт несколько кадров и ПОЛЗЁТ.
 *
 * По одному кадру крошка, ворсинка и клоп неотличимы. Отличает движение:
 * клоп ползёт 1–4 см/с, крошка лежит. Всё считаем в миллиметрах, поэтому
 * настройка одна — сколько миллиметров простыни влезает в кадр по ширине.
 *
 * Работает на сыром массиве яркости, без зависимостей: на iPhone 6s должно
 * тянуть ~8 кадров в секунду при рабочем разрешении 640×360.
 */

export const DEFAULTS = {
  fovWidthMm: 90,         // ширина кадра на простыне, мм
  bugLenMin: 1.5,         // личинка
  bugLenMax: 9.0,         // взрослый клоп
  minShortRatio: 0.25,    // тело овальное: отсекает волосы и складки
  minFill: 0.30,          // заполненность рамки: отсекает нитки и царапины
  darkThreshold: 18,      // насколько пятно темнее фона (0..255)
  bgAlpha: 0.02,          // скорость забывания фона в покое
  settleAlpha: 0.35,      // ускоренное забывание после шевеления
  warmupFrames: 20,       // кадры на построение фона
  maxChangeFrac: 0.02,    // >2% кадра изменилось — это ты повернулся
  settleFrames: 15,       // столько кадров после шевеления себе не верим
  minHits: 4,             // пятно должно прожить столько кадров
  minTravelMm: 2.0,       // и уползти на столько от точки старта
  speedMinMmS: 0.2,       // медленнее — это не ползание, а дрейф фона
  speedMaxMmS: 90.0,      // быстрее — это блик или помеха
  matchRadiusMm: 12.0,    // на столько пятно может сместиться за кадр
  missLimit: 5,           // столько кадров без пятна — трек закрыт
};

export function toGray(rgba, out) {
  for (let i = 0, p = 0; p < out.length; i += 4, p++) {
    out[p] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8;
  }
  return out;
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
  }

  setFov(mm) {
    this.cfg.fovWidthMm = mm;
    this.pxPerMm = this.w / mm;
  }

  reset() {
    this.bg = null;
    this.tracks = [];
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
      if (longMm < cfg.bugLenMin || longMm > cfg.bugLenMax) continue;   // крошка или рука
      if (shortMm < cfg.minShortRatio * longMm) continue;               // волос или складка
      if (area < cfg.minFill * bw * bh) continue;                       // нитка или царапина
      out.push({ x: minX + bw / 2, y: minY + bh / 2, lengthMm: longMm,
                 box: [minX, minY, bw, bh] });
    }
    return out;
  }

  // ── слежение ──────────────────────────────────────────────────────────────

  _track(blobs, ts) {
    const radius = this.cfg.matchRadiusMm * this.pxPerMm;
    const free = blobs.slice();
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
      tr.lastTs = ts; tr.hits++; tr.misses = 0;
    }
    this.tracks = this.tracks.filter((t) => t.misses <= this.cfg.missLimit);
    for (const b of free) {
      this.tracks.push({ x: b.x, y: b.y, startX: b.x, startY: b.y, firstTs: ts,
                         lastTs: ts, lengthMm: b.lengthMm, box: b.box,
                         hits: 1, misses: 0, pathMm: 0, fired: false });
    }
    return this._verdict();
  }

  /** Трек — клоп, только если прожил достаточно кадров и реально сместился. */
  _verdict() {
    const cfg = this.cfg;
    for (const tr of this.tracks) {
      if (tr.fired || tr.hits < cfg.minHits) continue;
      const netMm = Math.hypot(tr.x - tr.startX, tr.y - tr.startY) / this.pxPerMm;
      if (netMm < cfg.minTravelMm) continue;              // дрожит на месте — не ползёт
      const dt = Math.max(tr.lastTs - tr.firstTs, 1e-6);
      const speed = tr.pathMm / dt;
      if (speed < cfg.speedMinMmS || speed > cfg.speedMaxMmS) continue;
      tr.fired = true;
      const byLife = Math.min(tr.hits / Math.max(cfg.minHits * 3, 1), 1);
      const byTravel = Math.min(netMm / Math.max(cfg.minTravelMm * 4, 0.5), 1);
      return {
        ts: tr.lastTs, box: tr.box, lengthMm: tr.lengthMm, travelMm: netMm,
        speedMmS: speed, frames: tr.hits,
        score: Math.round((0.35 + 0.65 * (0.5 * byLife + 0.5 * byTravel)) * 100) / 100,
      };
    }
    return null;
  }
}
