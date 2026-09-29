// Farbaholix price calculator. All prices are NET (VAT added separately).
// >>> CONFIG: the only place to tune prices <<<
var FX_CFG = {
  // € per artist day (flat rate)
  dayRate: 900,
  minProject: 1000,        // € minimum project price
  minHiphop: 0,            // hip-hop projects: below 1000 € possible
  // m² one artist paints per day at normal height, by detail level
  productivity: { low: 12, medium: 4, high: 1 },
  heightFactor: { h1: 1.0, h2: 1.2, h3: 1.4 },           // up to 3 m / 3–6 m scaffold / over 6 m lift
  whatFactor:   { facade: 1.15, indoor: 1.0, concept: 1.1, object: 1.3 },
  material:     { facade: 18, indoor: 10, concept: 12, object: 25 },   // € per m²
  prep:         { ready: 0, clean: 6, repair: 18 },                   // € per m²
  urgency:      { flex: 0.95, normal: 1.0, fast: 1.25, express: 1.5 },
  travelPerDay: { ffm: 0, r30: 40, r100: 120, r300: 250, far: 400 },  // € per working day
  payment: [0.10, 0.50, 0.40], // deposit (non-refundable, sketches) / after sketch approval / on completion
  hiphopDiscount: 0.10,    // project with hip-hop culture
  visibilityDiscount: 0.07,// high visibility / brings new clients
  maxDiscount: 0.15,
  ukraine: 0.10,           // optional +10 % for Ukrainian underground artists
  vat: 0.19,
  spread: 0.15             // shown as a ±15 % range
};

(function () {
  var form = document.getElementById('fxCalc');
  if (!form) return;
  var T = window.FX_CALC_TEXT;
  var out = document.getElementById('fxCalcOut'), stop = document.getElementById('fxCalcStop');
  var areaIn = form.elements.area, areaOut = document.getElementById('fxAreaVal');
  var C = FX_CFG, last = null;
  // small floating price pill while the questions are on screen
  var mini = document.createElement('button'); mini.type = 'button'; mini.id = 'fxMini';
  document.body.appendChild(mini);
  mini.addEventListener('click', function () { out.scrollIntoView({ behavior: 'smooth', block: 'center' }); });
  if ('IntersectionObserver' in window) {
    var formIn = false, resIn = false;
    var sync = function () { mini.classList.toggle('is-on', formIn && !resIn && !out.hidden); };
    new IntersectionObserver(function (en) { formIn = en[0].isIntersecting; sync(); }).observe(form);
    new IntersectionObserver(function (en) { resIn = en[0].isIntersecting; sync(); }).observe(out.parentNode);
  }

  function val(name) { var el = form.querySelector('[name="' + name + '"]:checked'); return el ? el.value : (form.elements[name] && form.elements[name].value); }
  function on(name) { var el = form.elements[name]; return !!(el && el.checked); }
  function money(x) { return new Intl.NumberFormat(T.locale, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(x); }
  function r50(x) { return Math.round(x / 50) * 50; }
  function label(name) { var el = form.querySelector('[name="' + name + '"]:checked'); return el ? el.parentNode.textContent.trim() : form.elements[name].selectedOptions[0].textContent.trim(); }

  function calc() {
    var what = val('what');
    areaOut.textContent = areaIn.value + ' m²';
    if (what === 'toilet') { out.hidden = true; stop.hidden = false; last = null; mini.classList.remove('is-on'); stop.scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
    stop.hidden = true; out.hidden = false;
    var area = +areaIn.value;
    var days = Math.max(0.5, Math.ceil(area / C.productivity[val('detail')] * C.heightFactor[val('height')] * 2) / 2);
    var labor = days * C.dayRate * C.whatFactor[what] * C.urgency[val('when')];
    var material = area * C.material[what];
    var prep = area * C.prep[val('surface')];
    var travel = Math.ceil(days) * C.travelPerDay[val('where')];
    var disc = Math.min(C.maxDiscount, (on('hiphop') ? C.hiphopDiscount : 0) + (on('visible') ? C.visibilityDiscount : 0));
    var base = (labor + material + prep + travel) * (1 - disc);
    var hiphop = on('hiphop');
    var minimum = hiphop ? C.minHiphop : C.minProject;
    var net = Math.max(minimum, base);
    var ua = on('ukraine') ? net * C.ukraine : 0;
    var total = net + ua;
    var lo = r50(total * (1 - C.spread)), hi = r50(total * (1 + C.spread));
    if (net === minimum && minimum) lo = Math.max(lo, minimum);
    document.getElementById('fxPrice').textContent = money(lo) + ' – ' + money(hi);
    document.getElementById('fxGross').textContent = T.gross.replace('{lo}', money(r50(lo * (1 + C.vat)))).replace('{hi}', money(r50(hi * (1 + C.vat))));
    var rows = [[T.days, days.toLocaleString(T.locale) + ' ' + T.daysUnit]];
    if (disc) rows.push([T.discRow, '−' + Math.round(disc * 100) + ' %']);
    if (ua) rows.push([T.uaRow, money(ua)]);
    if (net === minimum && minimum) rows.push([T.minRow, money(minimum)]);
    if (hiphop && base < C.minProject) rows.push([T.hiphopRow, '✓']);
    var mid = (lo + hi) / 2;
    T.payRows.forEach(function (label, i) { rows.push([label, '≈ ' + money(r50(mid * C.payment[i]))]); });
    document.getElementById('fxRows').innerHTML = rows.map(function (r) { return '<li><span>' + r[0] + '</span><b>' + r[1] + '</b></li>'; }).join('');
    last = { lo: lo, hi: hi, days: days };
    mini.innerHTML = money(lo) + ' – ' + money(hi) + '<small>' + T.net + '</small>';
  }

  function brief() {
    var names = ['what', 'detail', 'height', 'design', 'surface', 'when', 'where'];
    var lines = [T.briefTitle, T.qArea + ': ' + areaIn.value + ' m²'].concat(names.map(function (n) { return T.q[n] + ': ' + label(n); }));
    ['hiphop', 'visible', 'ukraine'].forEach(function (n) { if (on(n)) lines.push('✓ ' + label(n)); });
    if (last) lines.push(T.briefPrice + ': ' + money(last.lo) + ' – ' + money(last.hi) + ' ' + T.net);
    return lines.join('\n');
  }

  form.addEventListener('input', calc);
  form.addEventListener('change', calc);
  document.getElementById('fxCalcSend').addEventListener('click', function () {
    if (window.fxContact) window.fxContact(brief()); else location.href = 'mailto:farbaholix@gmail.com?body=' + encodeURIComponent(brief());
  });
  document.getElementById('fxCalcMail').addEventListener('click', function (ev) {
    ev.currentTarget.href = 'mailto:farbaholix@gmail.com?subject=' + encodeURIComponent(T.briefTitle) + '&body=' + encodeURIComponent(brief());
  });
  calc();
})();
