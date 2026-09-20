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
  minFill: 0.45,          // заполненность рамки: у тела ~0.78, у волоса ~0.37
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
  speedWindowS: 1.5,      // за сколько секунд меряем текущую скорость
  motionHalfLifeS: 4.0,   // за столько забывается недавнее движение
  holdFactor: 0.08,       // во столько раз медленнее фон съедает отслеживаемое пятно
  matchRadiusMm: 18.0,    // на столько пятно может сместиться за кадр
  missLimit: 16,          // столько кадров без пятна — трек закрыт
  fireScore: 0.70,        // с какой вероятности будить

  // ── Пороги в ПИКСЕЛЯХ. Всё, что выше, задано в миллиметрах, и это удобно,
  // пока в миллиметре хватает точек. На широком кадре «проползти 2 мм»
  // превращается в полтора пикселя — столько же даёт дыхание под одеялом,
  // и сторож честно срабатывает на дрожь ткани. Поэтому снизу стоят упоры,
  // ниже которых миллиметрам верить нельзя.
  minLenPx: 8,            // короче — тело не разрешается камерой
  minShortPx: 4,          // тоньше — это волос или нитка, а не тело
  minTravelPx: 5,         // меньше — это дрожь, а не переползание

  // ── Что в кадре, кроме клопа ───────────────────────────────────────────
  maxCandidates: 8,       // больше пятен — это фактура ткани, а не насекомые
  bigBlobFrac: 0.01,      // объект крупнее доли кадра — кот или ты сам
  bigBlobHoldS: 3.0,      // столько секунд молчим после крупного объекта
  coherentMin: 3,         // столько согласованно ползущих пятен = ткань поехала
  coherentRatio: 0.6,     // насколько единодушно они должны двигаться
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
    this.holdBuf = new Uint8Array(n);
    this.tracks = [];
    this.frameIdx = 0;
    this.settleLeft = 0;
    this.changeFrac = 0;
    this.blobs = [];
    this.candidates = [];   // что сейчас в кадре, с вероятностью и разбором
    this.best = null;       // самый вероятный кандидат этого кадра
    this.bigArea = 0;       // площадь самого крупного пятна в кадре
    this.vetoUntil = 0;     // до какого времени тревоги запрещены
    this.vetoWhy = '';      // и почему
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

  /** Запретить тревоги на несколько секунд и запомнить, из-за чего. */
  _veto(ts, secs, why) {
    this.vetoUntil = Math.max(this.vetoUntil, ts + secs);
    this.vetoWhy = why;
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

    if (this.settleLeft > 0) {
      this._updateBg(cfg.settleAlpha, null);
      this.settleLeft--;
      return null;
    }
    if (this.frameIdx <= cfg.warmupFrames) {
      this._updateBg(cfg.bgAlpha, null);
      return null;
    }

    this._open(this.mask, this.tmp);
    this.blobs = this._blobs();
    // Фон обновляем в последнюю очередь и ПРИДЕРЖИВАЕМ под найденными пятнами.
    // Иначе замерший клоп через десяток секунд впитывается в фон и пропадает
    // с экрана — а они именно так и ходят: пополз, замер, снова пополз.
    this._updateBg(cfg.bgAlpha, this.blobs);

    // Кот на кровати или твоё плечо дают пятно в сотни раз крупнее клопа.
    // Само по себе оно отсеивается по размеру, но рядом с ним шевелится всё:
    // складки, тени, шерсть. Поэтому на такие секунды тревоги запрещаем.
    if (this.bigArea > cfg.bigBlobFrac * n) {
      this._veto(ts, cfg.bigBlobHoldS, 'в кадре крупный объект — кот или ты сам');
    }
    return this._track(this.blobs, ts);
  }

  /** Фон ползёт к текущему кадру; под отслеживаемыми пятнами — заметно медленнее. */
  _updateBg(alpha, blobs) {
    const { w, h, bg, blur, cfg } = this;
    const n = w * h;
    if (!blobs || !blobs.length) {
      for (let i = 0; i < n; i++) bg[i] += alpha * (blur[i] - bg[i]);
      return;
    }
    const hold = this.holdBuf;
    hold.fill(0);
    const pad = 2;
    for (const b of blobs) {
      const [bx, by, bw, bh] = b.box;
      const x0 = Math.max(0, bx - pad), y0 = Math.max(0, by - pad);
      const x1 = Math.min(w - 1, bx + bw + pad), y1 = Math.min(h - 1, by + bh + pad);
      for (let y = y0; y <= y1; y++) {
        const row = y * w;
        for (let x = x0; x <= x1; x++) hold[row + x] = 1;
      }
    }
    const slow = alpha * cfg.holdFactor;
    for (let i = 0; i < n; i++) bg[i] += (hold[i] ? slow : alpha) * (blur[i] - bg[i]);
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
    this.bigArea = 0;
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
      const longPx = Math.max(bw, bh);
      if (area > this.bigArea) this.bigArea = area;
      // Не разрешается камерой либо слишком тонкое: размытие дробит волос на
      // фрагменты, и отдельный кусок выглядит компактным, как тело.
      if (longPx < cfg.minLenPx || Math.min(bw, bh) < cfg.minShortPx) continue;
      const longMm = longPx / pxPerMm;
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
    const moves = [];   // куда и насколько сместилось каждое пятно за этот кадр
    for (const tr of this.tracks) {
      let best = null, bestD = radius;
      for (const b of free) {
        const d = Math.hypot(b.x - tr.x, b.y - tr.y);
        if (d < bestD) { best = b; bestD = d; }
      }
      if (!best) { tr.misses++; continue; }
      free.splice(free.indexOf(best), 1);
      if (bestD > 0.3) moves.push({ dx: best.x - tr.x, dy: best.y - tr.y });
      tr.x = best.x; tr.y = best.y;
      tr.hist.push({ ts, x: best.x, y: best.y });
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
                         box: b.box, hits: 1, misses: 0, fired: false, jumpMm,
                         hist: [{ ts, x: b.x, y: b.y }], motion: 0, motionTs: ts });
    }
    // Клоп ползёт сам по себе. Если сразу несколько пятен поехали в одну
    // сторону — это не стая клопов, это дрогнуло одеяло под дышащим хозяином.
    if (moves.length >= this.cfg.coherentMin) {
      let sx = 0, sy = 0, sum = 0;
      for (const m of moves) { sx += m.dx; sy += m.dy; sum += Math.hypot(m.dx, m.dy); }
      if (sum > 0 && Math.hypot(sx, sy) / sum > this.cfg.coherentRatio) {
        this._veto(ts, this.cfg.bigBlobHoldS, 'ткань поехала целиком — дыхание или поворот');
      }
    }

    for (const tr of this.tracks) this._motion(tr, ts);
    return this._evaluate(ts);
  }

  /* Скорость меряем по последним полутора секундам, а не в среднем за всю
   * жизнь трека: иначе остановка задним числом обнуляет заслуги предыдущего
   * проползания, и клоп, который прошёл и замер, скатывается в проценты
   * неподвижной крошки. Свежий рывок запоминается и затухает вдвое за
   * motionHalfLifeS — «двигался только что» остаётся уликой ещё несколько
   * секунд, а «лежит с прошлой недели» перестаёт ею быть. */
  _motion(tr, ts) {
    const cfg = this.cfg;
    const dt = ts - tr.motionTs;
    if (dt > 0) {
      tr.motion *= Math.pow(0.5, dt / cfg.motionHalfLifeS);
      tr.motionTs = ts;
    }
    while (tr.hist.length > 1 && ts - tr.hist[0].ts > cfg.speedWindowS) tr.hist.shift();
    if (tr.hist.length > 1) {
      let path = 0;
      for (let i = 1; i < tr.hist.length; i++) {
        path += Math.hypot(tr.hist[i].x - tr.hist[i - 1].x,
                           tr.hist[i].y - tr.hist[i - 1].y);
      }
      const elapsed = tr.hist[tr.hist.length - 1].ts - tr.hist[0].ts;
      if (elapsed > 0.05) tr.motion = Math.max(tr.motion, path / this.pxPerMm / elapsed);
    }
  }

  /** Вероятность для одного трека плюс разбор, чего ему не хватает. */
  _rate(tr) {
    const cfg = this.cfg;
    const netMm = Math.hypot(tr.x - tr.startX, tr.y - tr.startY) / this.pxPerMm;
    const speed = tr.motion;     // недавнее движение, а не среднее за всю жизнь

    const fSize = band(tr.lengthMm, cfg.bugLenMin, cfg.bugLenBest[0],
                       cfg.bugLenBest[1], cfg.bugLenMax);
    const fRatio = clamp01((tr.ratio - cfg.minShortRatio) / (0.55 - cfg.minShortRatio));
    const fFill = clamp01((tr.fill - cfg.minFill) / (0.75 - cfg.minFill));
    const fShape = 0.5 * fRatio + 0.5 * fFill;
    const fLife = Math.min(tr.hits / cfg.minHits, 1);
    const netPx = netMm * this.pxPerMm;
    const fTravel = Math.min(netMm / cfg.minTravelMm, netPx / cfg.minTravelPx, 1);
    const fSpeed = band(speed, cfg.speedMinMmS, cfg.speedBestMmS[0],
                        cfg.speedBestMmS[1], cfg.speedMaxMmS);

    const look = 0.6 * fSize + 0.4 * fShape;
    const move = fLife * (0.5 * fTravel + 0.5 * fSpeed);
    const score = look * move;

    // Разбор пишем от самого слабого: именно он и держит вероятность внизу.
    const speedWord = speed >= cfg.speedMaxMmS
      ? `скорость ${speed.toFixed(0)} мм/с — выше потолка ${cfg.speedMaxMmS}`
      : speed <= cfg.speedMinMmS
        ? 'не двигалось ни разу'
        : `двигалось ${speed.toFixed(1)} мм/с`;
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
      [netPx < cfg.minTravelPx
        ? `сместилось ${netPx.toFixed(1)} из ${cfg.minTravelPx} точек — это дрожь`
        : `проползло ${netMm.toFixed(1)} из ${cfg.minTravelMm} мм`, fTravel],
      [speedWord, fSpeed],
      [`тело ${tr.lengthMm.toFixed(1)} мм`, fSize],
      ['форма пятна', fShape],
    ].filter(([, f]) => f < 0.9).sort((a, b) => a[1] - b[1]);

    const why = parts.slice(0, 2)
      .map(([t, f]) => `${t} (${Math.round(f * 100)}%)`).join(', ');
    return { score, why, netMm, speed, fLife, fTravel, fSpeed, fSize, fShape };
  }

  /** Считаем всех, показываем всех, будим — того, кто дотянул до порога. */
  _evaluate(ts) {
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
      if (!tr.fired && r.score >= cfg.fireScore && !hit && ts > this.vetoUntil) {
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

    // Столько пятен разом бывает только на фактурной ткани. Чистая простыня
    // даёт единицы — значит камера смотрит не туда, и верить кадру нельзя.
    if (this.candidates.length > cfg.maxCandidates) {
      this._veto(ts, cfg.bigBlobHoldS,
                 `пятен в кадре ${this.candidates.length} — это фактура, а не клопы`);
    }
    return hit;
  }
}
