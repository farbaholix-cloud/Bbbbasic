/*
 * Легкі SVG-графіки без зовнішніх бібліотек (працюють офлайн).
 * Кольори беруться з CSS-токенів, тому світла і темна теми працюють автоматично.
 */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  let tip;
  function tooltip() {
    if (!tip) { tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; document.body.appendChild(tip); }
    return tip;
  }
  function showTip(html, x, y) {
    const t = tooltip(); t.innerHTML = html; t.hidden = false;
    const w = t.offsetWidth, hgt = t.offsetHeight;
    let left = x + 14, top = y - hgt - 10;
    if (left + w > innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 16;
    t.style.left = Math.max(8, left) + 'px'; t.style.top = top + 'px';
  }
  function hideTip() { if (tip) tip.hidden = true; }
  document.addEventListener('scroll', hideTip, { passive: true });

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  }

  /* Лінійний графік з областю, перехрестям і підказкою. data: [{x, y, label}] */
  function line(host, data, o) {
    o = Object.assign({ h: 200, color: 'var(--s1)', fmt: v => Math.round(v), target: null, targetLabel: '' }, o);
    host.innerHTML = '';
    const W = Math.max(280, host.clientWidth || 600), H = o.h, P = { l: 38, r: 12, t: 12, b: 24 };
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, class: 'chart', role: 'img', 'aria-label': o.aria || '' }, host);
    const ys = data.map(d => d.y);
    const max = niceMax(Math.max(o.target || 0, ...ys) * 1.08);
    const x = i => P.l + (W - P.l - P.r) * (data.length < 2 ? 0.5 : i / (data.length - 1));
    const y = v => P.t + (H - P.t - P.b) * (1 - v / max);
    for (let i = 0; i <= 4; i++) {
      const v = max * i / 4;
      el('line', { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), class: 'grid' }, svg);
      el('text', { x: P.l - 6, y: y(v) + 4, class: 'axis', 'text-anchor': 'end' }, svg).textContent = o.fmt(v);
    }
    const step = Math.ceil(data.length / Math.max(2, Math.floor((W - P.l) / 70)));
    data.forEach((d, i) => { if (i % step === 0 || i === data.length - 1) el('text', { x: x(i), y: H - 6, class: 'axis', 'text-anchor': 'middle' }, svg).textContent = d.label; });
    if (o.target != null) {
      el('line', { x1: P.l, x2: W - P.r, y1: y(o.target), y2: y(o.target), class: 'target' }, svg);
      el('text', { x: W - P.r, y: y(o.target) - 5, class: 'axis target-label', 'text-anchor': 'end' }, svg).textContent = o.targetLabel;
    }
    const pts = data.map((d, i) => [x(i), y(d.y)]);
    const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    if (pts.length) {
      el('path', { d: path + ` L${pts[pts.length - 1][0]} ${y(0)} L${pts[0][0]} ${y(0)} Z`, fill: o.color, opacity: 0.1 }, svg);
      el('path', { d: path, fill: 'none', stroke: o.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
      const last = pts[pts.length - 1];
      el('circle', { cx: last[0], cy: last[1], r: 4, fill: o.color, stroke: 'var(--surface)', 'stroke-width': 2 }, svg);
    }
    const cross = el('line', { y1: P.t, y2: H - P.b, class: 'cross', visibility: 'hidden' }, svg);
    const dot = el('circle', { r: 5, fill: o.color, stroke: 'var(--surface)', 'stroke-width': 2, visibility: 'hidden' }, svg);
    const hit = el('rect', { x: P.l, y: 0, width: W - P.l - P.r, height: H, fill: 'transparent' }, svg);
    const move = ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * W / r.width;
      const i = Math.round((px - P.l) / (W - P.l - P.r) * (data.length - 1));
      const d = data[Math.max(0, Math.min(data.length - 1, i))]; if (!d) return;
      const ii = data.indexOf(d);
      cross.setAttribute('x1', x(ii)); cross.setAttribute('x2', x(ii)); cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', x(ii)); dot.setAttribute('cy', y(d.y)); dot.setAttribute('visibility', 'visible');
      showTip(`<b>${d.tip || d.label}</b><span>${o.name || ''}: ${o.fmt(d.y)}</span>`, ev.clientX, ev.clientY);
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip(); });
  }

  /* Горизонтальні смуги (HTML). rows: [{label, value, text, color, tip}] */
  function bars(host, rows, o) {
    o = Object.assign({ fmt: v => v, color: 'var(--s1)' }, o);
    const max = Math.max(1, ...rows.map(r => r.value));
    host.innerHTML = '<div class="hbars">' + rows.map((r, i) =>
      `<div class="hbar" data-i="${i}"><span class="hbar-label">${r.label}</span><span class="hbar-track"><span class="hbar-fill" style="width:${(r.value / max * 100).toFixed(1)}%;background:${r.color || o.color}"></span></span><span class="hbar-val">${r.text != null ? r.text : o.fmt(r.value)}</span></div>`
    ).join('') + '</div>';
    host.querySelectorAll('.hbar').forEach(b => {
      const r = rows[+b.dataset.i];
      if (!r.tip) return;
      b.addEventListener('pointermove', ev => showTip(r.tip, ev.clientX, ev.clientY));
      b.addEventListener('pointerleave', hideTip);
    });
  }

  /* Одна складена смуга з легендою: частки каналів. parts: [{label, value, color}] */
  function stack(host, parts, o) {
    o = Object.assign({ fmt: v => v }, o);
    const total = parts.reduce((s, p) => s + p.value, 0) || 1;
    host.innerHTML = `<div class="stack">${parts.map((p, i) => `<span class="stack-seg" data-i="${i}" style="flex:${p.value} 1 0;background:${p.color}"></span>`).join('')}</div>
      <ul class="legend">${parts.map(p => `<li><i style="background:${p.color}"></i>${p.label} <b>${Math.round(p.value / total * 100)}%</b>${p.extra ? `<span class="muted"> · ${p.extra}</span>` : ''}</li>`).join('')}</ul>`;
    host.querySelectorAll('.stack-seg').forEach(s => {
      const p = parts[+s.dataset.i];
      s.addEventListener('pointermove', ev => showTip(`<b>${p.label}</b><span>${o.fmt(p.value)} · ${Math.round(p.value / total * 100)}%</span>`, ev.clientX, ev.clientY));
      s.addEventListener('pointerleave', hideTip);
    });
  }

  /* Теплова карта день тижня × година. m[7][24] */
  function heat(host, m, o) {
    o = Object.assign({ rows: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'], fmt: v => v.toFixed(1) }, o);
    const max = Math.max(...m.flat()) || 1;
    let html = '<div class="heat-wrap"><div class="heat" style="--cols:24">';
    html += '<span></span>' + Array.from({ length: 24 }, (_, h) => `<span class="heat-h">${h % 3 === 0 ? h : ''}</span>`).join('');
    m.forEach((row, r) => {
      html += `<span class="heat-r">${o.rows[r]}</span>`;
      row.forEach((v, h) => {
        const k = Math.round(8 + v / max * 92);
        html += `<span class="heat-c" data-r="${r}" data-h="${h}" style="background:color-mix(in oklab, var(--seq) ${k}%, var(--surface))"></span>`;
      });
    });
    html += '</div></div><div class="heat-scale"><span>менше</span><i></i><span>більше звернень</span></div>';
    host.innerHTML = html;
    host.querySelectorAll('.heat-c').forEach(c => {
      c.addEventListener('pointermove', ev => showTip(`<b>${o.rows[c.dataset.r]}, ${c.dataset.h}:00–${+c.dataset.h + 1}:00</b><span>${o.fmt(m[c.dataset.r][c.dataset.h])} звернень на годину в середньому</span>`, ev.clientX, ev.clientY));
      c.addEventListener('pointerleave', hideTip);
    });
  }

  /* Колонки «є» з маркером «потрібно» по годинах доби. rows: [{h, have, need}] */
  function needHave(host, rows) {
    host.innerHTML = '';
    const W = Math.max(280, host.clientWidth || 600), H = 190, P = { l: 26, r: 6, t: 10, b: 22 };
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, class: 'chart' }, host);
    const max = niceMax(Math.max(...rows.map(r => Math.max(r.have, r.need))) * 1.1);
    const bw = (W - P.l - P.r) / rows.length;
    const y = v => P.t + (H - P.t - P.b) * (1 - v / max);
    for (let i = 0; i <= max; i += max > 6 ? 2 : 1) {
      el('line', { x1: P.l, x2: W - P.r, y1: y(i), y2: y(i), class: 'grid' }, svg);
      el('text', { x: P.l - 5, y: y(i) + 4, class: 'axis', 'text-anchor': 'end' }, svg).textContent = i;
    }
    rows.forEach((r, i) => {
      const x0 = P.l + i * bw + 1, w = Math.max(2, bw - 2);
      const short = r.have + 0.25 < r.need;
      const top = y(r.have), base = y(0);
      el('path', { d: `M${x0} ${base} V${top + 3} Q${x0} ${top} ${x0 + 3} ${top} H${x0 + w - 3} Q${x0 + w} ${top} ${x0 + w} ${top + 3} V${base} Z`, fill: short ? 'var(--crit)' : 'var(--s1)', opacity: short ? 0.85 : 0.75 }, svg);
      el('line', { x1: x0 - 1, x2: x0 + w + 1, y1: y(r.need), y2: y(r.need), stroke: 'var(--ink)', 'stroke-width': 2, 'stroke-linecap': 'round' }, svg);
      if (r.h % 3 === 0) el('text', { x: x0 + w / 2, y: H - 6, class: 'axis', 'text-anchor': 'middle' }, svg).textContent = r.h;
      const hit = el('rect', { x: x0 - 1, y: 0, width: bw, height: H, fill: 'transparent' }, svg);
      hit.addEventListener('pointermove', ev => showTip(`<b>${r.h}:00–${r.h + 1}:00</b><span>Потрібно: ${r.need} · Є: ${r.have.toFixed(1)}</span><span>${r.lam.toFixed(1)} звернень/год, обробка ${r.aht.toFixed(0)} хв</span>`, ev.clientX, ev.clientY));
      hit.addEventListener('pointerleave', hideTip);
    });
  }

  /* Спарклайн для таблиць */
  function spark(values, color) {
    const W = 80, H = 22, max = Math.max(1, ...values);
    const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1) * (W - 4) + 2).toFixed(1)},${(H - 3 - v / max * (H - 6)).toFixed(1)}`);
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><polyline points="${pts.join(' ')}" fill="none" stroke="${color || 'var(--s1)'}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  window.Charts = { line, bars, stack, heat, needHave, spark, showTip, hideTip };
})();
