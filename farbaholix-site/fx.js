(function () {
  var root = document.querySelector('.fx');
  if (!root) return;

  // ---- Burger menu ----
  var burger = document.getElementById('fxBurger'), menu = document.getElementById('fxMenu'), closeBtn = document.getElementById('fxMenuClose');
  function toggleMenu(open) {
    root.classList.toggle('menu-open', open);
    burger.setAttribute('aria-expanded', open);
    menu.setAttribute('aria-hidden', !open);
  }
  if (burger && menu) {
    burger.addEventListener('click', function () { toggleMenu(true); });
    closeBtn.addEventListener('click', function () { toggleMenu(false); });
    menu.addEventListener('click', function (ev) { if (ev.target.tagName === 'A') toggleMenu(false); });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') toggleMenu(false); });
  }


  // ---- Contact form: posted to the site (stored, mailed, forwarded to the owner) – visitors stay on the page ----
  var t0 = Date.now();
  Array.prototype.forEach.call(document.querySelectorAll('[data-fx-form]'), function (f) {
    var btn = f.querySelector('.fx-cform-send'), label = btn.textContent, st = f.querySelector('.fx-cform-status');
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var c = f.elements.contact, m = f.elements.message;
      [c, m].forEach(function (x) { x.classList.toggle('is-bad', x.value.trim().length < (x === c ? 5 : 2)); });
      if (f.querySelector('.is-bad')) { f.querySelector('.is-bad').focus(); return; }
      btn.disabled = true; btn.textContent = btn.dataset.sending; st.textContent = ''; st.className = 'fx-cform-status';
      fetch('/wp-json/fx/v1/contact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        name: f.elements.name.value.trim(), contact: c.value.trim(), message: m.value.trim(), website: f.elements.website.value,
        page: location.href, lang: document.documentElement.lang || root.getAttribute('lang') || '', t: Date.now() - t0 }) })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function () { f.reset(); st.textContent = st.dataset.ok; st.classList.add('is-ok'); })
        .catch(function () { st.textContent = st.dataset.err; st.classList.add('is-err'); })
        .then(function () { btn.disabled = false; btn.textContent = label; });
    });
  });
  // floating message button + popup; [data-fx-contact] and the calculator open it (optionally prefilled)
  var fab = document.getElementById('fxFab'), pop = document.getElementById('fxPop');
  function togglePop(open, text) {
    if (!pop) return;
    pop.hidden = !open; fab.setAttribute('aria-expanded', open);
    if (open) { var ta = pop.querySelector('textarea'); if (text) ta.value = text; (text ? pop.querySelector('input[name=contact]') : ta).focus({ preventScroll: true }); }
  }
  window.fxContact = function (text) { togglePop(true, text); };
  if (fab && pop) {
    fab.addEventListener('click', function () { togglePop(pop.hidden); });
    document.getElementById('fxPopX').addEventListener('click', function () { togglePop(false); });
    document.addEventListener('click', function (ev) { var b = ev.target.closest && ev.target.closest('[data-fx-contact]'); if (b) { ev.preventDefault(); togglePop(true); } });
  }

  // ---- Call card: "available now" Mon–Sat 9–20 (Frankfurt time) ----
  try {
    var parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', weekday: 'short', hour: 'numeric', hour12: false }).formatToParts(new Date());
    var wd = parts.find(function (p) { return p.type === 'weekday'; }).value, hr = +parts.find(function (p) { return p.type === 'hour'; }).value;
    var available = wd !== 'Sun' && hr >= 9 && hr < 20;
    Array.prototype.forEach.call(document.querySelectorAll('.fx-call'), function (c) {
      c.classList.toggle('is-off', !available);
      var s = c.querySelector('.fx-call-status'); s.textContent = available ? s.dataset.on : s.dataset.off;
    });
  } catch (err) { /* keep default text */ }

  // ---- Layers (overview, lightbox) close with the phone's back button too ----
  var layers = [];
  function pushLayer(close) { layers.push(close); try { history.pushState({ fxLayer: layers.length }, ''); } catch (err) {} document.documentElement.classList.add('fx-noscroll'); }
  function closeTop() { if (layers.length) history.back(); }
  window.addEventListener('popstate', function () { var f = layers.pop(); if (f) f(); if (!layers.length) document.documentElement.classList.remove('fx-noscroll'); });

  // ---- Lightbox: a.fx-lb[data-lb=group]; shows data-cap, swipe / arrows / Esc ----
  var box = null, group = [], cur = 0, boxImg, boxCap, boxN, lastFocus = null;
  var svg = function (d) { return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + d + '"/></svg>'; };
  function buildBox() {
    box = document.createElement('div'); box.className = 'fx-lbx'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    box.innerHTML = '<button type="button" class="fx-lbx-x" aria-label="Close">' + svg('M6 6l12 12M18 6L6 18') + '</button><button type="button" class="fx-lbx-prev" aria-label="Previous">' + svg('M15 5l-7 7 7 7') + '</button>' +
      '<figure><img alt=""><figcaption></figcaption></figure><button type="button" class="fx-lbx-next" aria-label="Next">' + svg('M9 5l7 7-7 7') + '</button><span class="fx-lbx-n"></span>';
    document.body.appendChild(box);
    boxImg = box.querySelector('img'); boxCap = box.querySelector('figcaption'); boxN = box.querySelector('.fx-lbx-n');
    box.querySelector('.fx-lbx-x').onclick = closeTop;
    box.querySelector('.fx-lbx-prev').onclick = function () { show(cur - 1); };
    box.querySelector('.fx-lbx-next').onclick = function () { show(cur + 1); };
    box.addEventListener('click', function (ev) { if (ev.target === box || ev.target.tagName === 'FIGURE') closeTop(); });
    var x0 = null, y0 = null;
    box.addEventListener('touchstart', function (ev) { x0 = ev.touches[0].clientX; y0 = ev.touches[0].clientY; }, { passive: true });
    box.addEventListener('touchend', function (ev) {
      if (x0 === null) return; var dx = ev.changedTouches[0].clientX - x0, dy = ev.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) show(cur + (dx < 0 ? 1 : -1)); else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) closeTop();
      x0 = null;
    });
  }
  function show(i) {
    cur = (i + group.length) % group.length;
    var a = group[cur], im = a.querySelector('img');
    boxImg.classList.remove('is-in'); boxImg.src = a.href; boxImg.alt = im ? im.alt : (a.dataset.cap || '');
    boxImg.onload = function () { boxImg.classList.add('is-in'); };
    boxCap.textContent = a.dataset.cap || (im ? im.alt : '');
    boxN.textContent = (cur + 1) + ' / ' + group.length;
    box.classList.toggle('is-single', group.length < 2);
    [cur + 1, cur - 1].forEach(function (n) { var p = group[(n + group.length) % group.length]; if (p) new Image().src = p.href; });
  }
  function openList(list, start) {
    if (!list.length) return;
    if (!box) buildBox();
    group = list; lastFocus = document.activeElement;
    box.classList.add('is-on'); show(start || 0); box.querySelector('.fx-lbx-next').focus({ preventScroll: true });
    pushLayer(function () { box.classList.remove('is-on'); boxImg.src = ''; if (lastFocus) lastFocus.focus({ preventScroll: true }); });
  }
  var byGroup = function (name) { return Array.prototype.slice.call(document.querySelectorAll('a.fx-lb[data-lb="' + name + '"]')); };

  // ---- "All works" overview: category chips + thumbnail grid, tap a photo to open it full screen ----
  var go = document.getElementById('fxGo'), goGrid = go && go.querySelector('.fx-go-grid'), goList = [], goBuilt = false;
  function goFilter(cat) {
    Array.prototype.forEach.call(go.querySelectorAll('.fx-go-cats button'), function (b) { var on = b.dataset.cat === cat; b.classList.toggle('is-on', on); b.setAttribute('aria-selected', on); if (on) b.scrollIntoView({ inline: 'center', block: 'nearest' }); });
    goList = [];
    Array.prototype.forEach.call(goGrid.children, function (t) { var on = cat === 'all' || t._src.dataset.cat === cat; t.hidden = !on; if (on) goList.push(t._src); });
    go.scrollTop = 0;
  }
  function goOpen(cat) {
    if (!go) return;
    if (!goBuilt) {
      goBuilt = true;
      document.body.appendChild(go);   // escape the page's stacking context so it covers header and chat button
      var src = byGroup('works');
      src.filter(function (a) { return a.dataset.recent; }).concat(src.filter(function (a) { return !a.dataset.recent; })).forEach(function (a) {   // recent projects first
        var t = document.createElement('button'); t.type = 'button'; t.className = 'fx-go-tile'; t._src = a;
        t.innerHTML = '<img loading="lazy" decoding="async" alt="">'; t.firstChild.src = a.dataset.thumb || a.href; t.firstChild.alt = a.dataset.cap || '';
        t.onclick = function () { openList(goList, goList.indexOf(a)); };
        goGrid.appendChild(t);
      });
      Array.prototype.forEach.call(go.querySelectorAll('.fx-go-cats button'), function (b) { b.onclick = function () { goFilter(b.dataset.cat); }; });
      go.querySelector('.fx-go-x').onclick = closeTop;
    }
    go.hidden = false; goFilter(cat || 'all');
    pushLayer(function () { go.hidden = true; });
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target.closest ? ev.target : null; if (!t) return;
    var g = t.closest('[data-go-open]');
    if (g && go) { ev.preventDefault(); goOpen(g.dataset.goOpen); return; }
    var a = t.closest('a.fx-lb');
    if (a) { ev.preventDefault(); var list = byGroup(a.dataset.lb); openList(list, Math.max(0, list.indexOf(a))); return; }
    var b = t.closest('[data-lb-open]');
    if (b) openList(byGroup(b.dataset.lbOpen), 0);
  });
  document.addEventListener('keydown', function (ev) {
    if (!layers.length) return;
    if (ev.key === 'Escape') closeTop();
    else if (box && box.classList.contains('is-on')) { if (ev.key === 'ArrowRight') show(cur + 1); else if (ev.key === 'ArrowLeft') show(cur - 1); }
  });

  // ---- Home: logo glides to the corner, background darkens around the video ----
  var logo = document.getElementById('fxLogo'), video = document.getElementById('fxVideo');
  if (logo && video) {
    var BROWN = [43, 29, 18], BLACK = [0, 0, 0], SMALL = 56, MARGIN = 12, ticking = false;
    var clamp = function (v) { return Math.max(0, Math.min(1, v)); };
    var ease = function (t) { return t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; };
    var update = function () {
      ticking = false;
      var vw = window.innerWidth, vh = window.innerHeight, size = logo.offsetWidth;
      // scroll distance at which the video sits in the viewport centre
      var r = video.getBoundingClientRect(), centre = r.top + r.height / 2;
      var startDist = Math.max(centre + window.scrollY - vh / 2, vh * 0.25);
      var p = ease(clamp(window.scrollY / startDist));
      var startX = (vw - size) / 2, startY = (vh * 0.55 - size) / 2;
      logo.style.transform = 'translate(' + (startX + (MARGIN - startX) * p) + 'px,' + (startY + (MARGIN - startY) * p) + 'px) scale(' + (1 + (SMALL / size - 1) * p) + ')';
      // brown at page top -> black with the video centred -> brown again further down
      var k = ease(clamp(Math.abs(centre - vh / 2) / startDist));
      var c = BLACK.map(function (b, i) { return Math.round(b + (BROWN[i] - b) * k); });
      document.documentElement.style.background = document.body.style.background = 'rgb(' + c + ')';
    };
    var onScroll = function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    video.addEventListener('loadedmetadata', update);
    update();
  }

  // ---- "Halogen tube": flickers on while the photo block crosses the screen middle, off outside ----
  var zone = document.getElementById('fxLit'), artist = document.getElementById('fxArtist');
  if (!zone || !('IntersectionObserver' in window)) return;
  var on = false, seen = false;
  function syncArtist() { if (artist) artist.classList.toggle('is-up', seen && on); }
  function set(state) {
    if (state === on) return;
    on = state;
    root.classList.remove('lights-on', 'lights-off');
    void root.offsetWidth;                 // restart the CSS animation
    root.classList.add(state ? 'lights-on' : 'lights-off');
    syncArtist();
  }
  new IntersectionObserver(function (entries) { set(entries[0].isIntersecting); }, { rootMargin: '-45% 0px -45% 0px' }).observe(zone);

  // Slavik rises from behind his photo once it is well in view and the light is on
  if (artist) new IntersectionObserver(function (entries) {
    seen = entries[0].intersectionRatio >= 0.5;
    syncArtist();
  }, { threshold: [0, 0.5, 1] }).observe(artist.parentNode);
})();
