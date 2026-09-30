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


  // ---- Contact form → /wp-json/fx/v1/contact (stored, mailed, forwarded to Slavik: WhatsApp + Telegram).
  //      When Telegram is connected ("live"), the form turns into a chat: Slavik's Telegram replies appear here (token in localStorage).
  var t0 = Date.now(), API = '/wp-json/fx/v1/', KEY = 'fxThread', forms = [].slice.call(document.querySelectorAll('[data-fx-form]'));
  function store(v) { try { if (v) localStorage.setItem(KEY, JSON.stringify(v)); else localStorage.removeItem(KEY); } catch (err) {} }
  function stored() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (err) { return null; } }
  var th = stored(), msgs = [], timer = null, lastAct = Date.now();
  function el(tag, cls, txt) { var x = document.createElement(tag); if (cls) x.className = cls; if (txt != null) x.textContent = txt; return x; }
  function tm(t) { var d = new Date(t * 1000); return d.toLocaleString(document.documentElement.lang || undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  function view(f) {   // chat block right after the form, built once
    if (f._th) return f._th;
    var d = f.dataset, v = el('div', 'fx-thread'), log = el('div', 'fx-thread-log'), note = el('p', 'fx-thread-wait'),
        rf = el('form', 'fx-thread-form'), ta = el('textarea'), sb = el('button', 'fx-btn fx-thread-send', d.thSend), nb = el('button', 'fx-thread-new', d.thNew);
    log.setAttribute('aria-live', 'polite'); ta.rows = 2; ta.maxLength = 3000; ta.placeholder = d.thPh; ta.setAttribute('aria-label', d.thPh); sb.type = 'submit'; nb.type = 'button';
    rf.appendChild(ta); rf.appendChild(sb); v.appendChild(log); v.appendChild(note); v.appendChild(rf); v.appendChild(nb);
    rf.addEventListener('submit', function (ev) {
      ev.preventDefault(); var x = ta.value.trim(); if (!x || !th) return;
      sb.disabled = true; lastAct = Date.now();
      fetch(API + 'thread', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ t: th.t, message: x }) })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (j) { ta.value = ''; msgs = j.msgs || msgs; renderAll(); poll(true); })
        .catch(function () { ta.classList.add('is-bad'); })
        .then(function () { sb.disabled = false; });
    });
    ta.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) rf.requestSubmit(); });
    nb.addEventListener('click', function () { th = null; store(null); msgs = []; clearTimeout(timer); forms.forEach(function (x) { x.hidden = false; if (x._th) x._th.hidden = true; }); setBadge(false); });
    f.parentNode.insertBefore(v, f.nextSibling); f._th = v; return v;
  }
  function renderAll() {
    forms.forEach(function (f) {
      var v = view(f), d = f.dataset, log = v.querySelector('.fx-thread-log');
      f.hidden = true; v.hidden = false; log.innerHTML = '';
      msgs.forEach(function (m) {
        var b = el('div', 'fx-msg ' + (m.w === 's' ? 'fx-msg-s' : 'fx-msg-v'));
        b.appendChild(el('b', null, m.w === 's' ? d.thMe : d.thYou)); b.appendChild(el('span', 'fx-msg-t', tm(m.t)));
        b.appendChild(el('p', null, m.x)); log.appendChild(b);
      });
      var answered = msgs.some(function (m) { return m.w === 's'; });
      v.querySelector('.fx-thread-wait').textContent = answered ? '' : d.thWait + (th && th.mail ? d.thMail : '');
      log.scrollTop = log.scrollHeight;
    });
  }
  function setBadge(on) { var fb = document.getElementById('fxFab'); if (fb) fb.classList.toggle('has-new', !!on); }
  function poll(soon) {
    clearTimeout(timer); if (!th) return;
    var idle = Date.now() - lastAct, delay = soon ? 4000 : idle < 6e5 ? 8000 : idle < 36e5 ? 30000 : 120000;
    timer = setTimeout(function () {
      if (document.hidden) return poll();
      fetch(API + 'thread?t=' + encodeURIComponent(th.t), { cache: 'no-store' })
        .then(function (r) { if (r.status === 404) { th = null; store(null); forms.forEach(function (x) { x.hidden = false; if (x._th) x._th.hidden = true; }); throw 0; } return r.json(); })
        .then(function (j) {
          var n = (j.msgs || []).length;
          if (n !== msgs.length) { msgs = j.msgs; renderAll(); var pop = document.getElementById('fxPop'); if (pop && pop.hidden && msgs[n - 1].w === 's') setBadge(true); }
          poll();
        }).catch(function (x) { if (x !== 0) poll(); });
    }, delay);
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden && th) { lastAct = Date.now(); poll(true); } });
  forms.forEach(function (f) {
    var btn = f.querySelector('.fx-cform-send'), label = btn.textContent, st = f.querySelector('.fx-cform-status');
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var c = f.elements.contact, m = f.elements.message;
      [c, m].forEach(function (x) { x.classList.toggle('is-bad', x.value.trim().length < (x === c ? 5 : 2)); });
      if (f.querySelector('.is-bad')) { f.querySelector('.is-bad').focus(); return; }
      btn.disabled = true; btn.textContent = btn.dataset.sending; st.textContent = ''; st.className = 'fx-cform-status';
      var contact = c.value.trim(), text = m.value.trim();
      fetch(API + 'contact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        name: f.elements.name.value.trim(), contact: contact, message: text, website: f.elements.website.value,
        page: location.href, lang: document.documentElement.lang || root.getAttribute('lang') || '', t: Date.now() - t0 }) })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (j) {
          f.reset();
          if (j.token && j.live) {
            th = { t: j.token, mail: /\S+@\S+\.\S+/.test(contact) }; store(th); lastAct = Date.now();
            msgs = [{ w: 'v', x: text, t: Date.now() / 1000 }]; renderAll(); poll();
          } else { st.textContent = st.dataset.ok; st.classList.add('is-ok'); }
        })
        .catch(function () { st.textContent = st.dataset.err; st.classList.add('is-err'); })
        .then(function () { btn.disabled = false; btn.textContent = label; });
    });
  });
  if (th && th.t && forms.length) {   // returning visitor with an open conversation
    fetch(API + 'thread?t=' + encodeURIComponent(th.t), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) {
        msgs = j.msgs || []; renderAll(); poll();
        if (msgs.length && msgs[msgs.length - 1].w === 's' && (th.seen || 0) < msgs.length) setBadge(true);
      })
      .catch(function () { th = null; store(null); });
  }
  // floating message button + popup; [data-fx-contact] and the calculator open it (optionally prefilled)
  var fab = document.getElementById('fxFab'), pop = document.getElementById('fxPop');
  function togglePop(open, text) {
    if (!pop) return;
    pop.hidden = !open; fab.setAttribute('aria-expanded', open);
    if (open && th) { setBadge(false); th.seen = msgs.length; store(th); var lg = pop.querySelector('.fx-thread-log'); if (lg) lg.scrollTop = lg.scrollHeight; }
    if (open && !(th && !text)) { var ta = pop.querySelector('textarea'); if (text && th) { forms.forEach(function (x) { x.hidden = false; if (x._th) x._th.hidden = true; }); }
      if (text) ta.value = text; (text ? pop.querySelector('input[name=contact]') : ta).focus({ preventScroll: true }); }
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
      '<button type="button" class="fx-lbx-zoom" aria-label="Zoom">' + svg('M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM20 20l-4.8-4.8M10.5 7.5v6M7.5 10.5h6') + '</button>' +
      '<figure><img alt="" draggable="false"><figcaption></figcaption></figure><button type="button" class="fx-lbx-next" aria-label="Next">' + svg('M9 5l7 7-7 7') + '</button><span class="fx-lbx-n"></span>';
    document.body.appendChild(box);
    boxImg = box.querySelector('img'); boxCap = box.querySelector('figcaption'); boxN = box.querySelector('.fx-lbx-n'); zBind();
    box.querySelector('.fx-lbx-x').onclick = closeTop;
    box.querySelector('.fx-lbx-prev').onclick = function () { show(cur - 1); };
    box.querySelector('.fx-lbx-next').onclick = function () { show(cur + 1); };
    box.addEventListener('click', function (ev) { if (ev.target === box || ev.target.tagName === 'FIGURE') closeTop(); });
    var x0 = null, y0 = null;
    box.addEventListener('touchstart', function (ev) { if (ev.touches.length > 1 || zm.z > 1) { x0 = null; return; } x0 = ev.touches[0].clientX; y0 = ev.touches[0].clientY; }, { passive: true });
    box.addEventListener('touchend', function (ev) {
      if (x0 === null || zm.z > 1 || zm.pinched) { if (!ev.touches.length) zm.pinched = false; x0 = null; return; } var dx = ev.changedTouches[0].clientX - x0, dy = ev.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) show(cur + (dx < 0 ? 1 : -1)); else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) closeTop();
      x0 = null;
    });
  }
  // zoom: double tap / double click, pinch, mouse wheel, button, +/- keys; drag to pan while zoomed
  var zm = { z: 1, x: 0, y: 0, pinched: false }, ptr = {}, pinch = null, pan = null, lastTap = 0, tapXY = null;
  function zApply(anim) {
    boxImg.classList.toggle('is-gesture', !anim);
    boxImg.style.transform = zm.z > 1 ? 'translate(' + zm.x + 'px,' + zm.y + 'px) scale(' + zm.z + ')' : '';
    box.classList.toggle('is-zoomed', zm.z > 1);
  }
  function zClamp() {
    var mx = boxImg.offsetWidth * (zm.z - 1) / 2, my = boxImg.offsetHeight * (zm.z - 1) / 2;
    zm.x = Math.max(-mx, Math.min(mx, zm.x)); zm.y = Math.max(-my, Math.min(my, zm.y));
  }
  function zAt(cx, cy, nz, anim) {   // keep the point under (cx, cy) in place
    nz = Math.max(1, Math.min(4, nz));
    var r = boxImg.getBoundingClientRect(), px = cx - (r.left + r.width / 2 - zm.x), py = cy - (r.top + r.height / 2 - zm.y);
    zm.x = px - (px - zm.x) * nz / zm.z; zm.y = py - (py - zm.y) * nz / zm.z; zm.z = nz;
    if (nz === 1) { zm.x = 0; zm.y = 0; }
    zClamp(); zApply(anim);
  }
  function zReset() { zm.z = 1; zm.x = 0; zm.y = 0; ptr = {}; pinch = pan = null; if (boxImg) zApply(true); }
  function zToggle(cx, cy) { if (zm.z > 1) zAt(cx, cy, 1, true); else zAt(cx, cy, 2.5, true); }
  function zBind() {
    var dist = function (a, b) { return Math.hypot(a.x - b.x, a.y - b.y); };
    boxImg.addEventListener('pointerdown', function (ev) {
      ev.preventDefault(); boxImg.setPointerCapture(ev.pointerId);
      ptr[ev.pointerId] = { x: ev.clientX, y: ev.clientY }; var ids = Object.keys(ptr);
      if (ids.length === 2) { var a = ptr[ids[0]], b = ptr[ids[1]]; pinch = { d: dist(a, b), z: zm.z }; pan = null; zm.pinched = true; }
      else if (ids.length === 1) { pan = { x: ev.clientX, y: ev.clientY, ox: zm.x, oy: zm.y, moved: 0 }; }
    });
    boxImg.addEventListener('pointermove', function (ev) {
      if (!ptr[ev.pointerId]) return;
      ptr[ev.pointerId] = { x: ev.clientX, y: ev.clientY }; var ids = Object.keys(ptr);
      if (pinch && ids.length >= 2) { var a = ptr[ids[0]], b = ptr[ids[1]]; zAt((a.x + b.x) / 2, (a.y + b.y) / 2, pinch.z * dist(a, b) / pinch.d, false); }
      else if (pan) {
        pan.moved = Math.max(pan.moved, Math.abs(ev.clientX - pan.x) + Math.abs(ev.clientY - pan.y));
        if (zm.z > 1) { zm.x = pan.ox + ev.clientX - pan.x; zm.y = pan.oy + ev.clientY - pan.y; zClamp(); zApply(false); }
      }
    });
    function up(ev) {
      if (!ptr[ev.pointerId]) return;
      delete ptr[ev.pointerId];
      if (Object.keys(ptr).length < 2) pinch = null;
      if (zm.z < 1.05 && zm.z !== 1) zAt(ev.clientX, ev.clientY, 1, true);
      if (pan && !Object.keys(ptr).length) {
        if (pan.moved < 10 && !zm.pinched) {   // a tap: two taps within 300 ms = zoom toggle
          var now = Date.now();
          if (now - lastTap < 300 && tapXY && Math.abs(tapXY.x - ev.clientX) + Math.abs(tapXY.y - ev.clientY) < 40) { zToggle(ev.clientX, ev.clientY); lastTap = 0; }
          else { lastTap = now; tapXY = { x: ev.clientX, y: ev.clientY }; }
        }
        pan = null;
      }
    }
    boxImg.addEventListener('pointerup', up); boxImg.addEventListener('pointercancel', up);
    box.addEventListener('wheel', function (ev) { if (!box.classList.contains('is-on')) return; ev.preventDefault(); zAt(ev.clientX, ev.clientY, zm.z * Math.exp(-ev.deltaY * 0.0022), false); }, { passive: false });
    box.querySelector('.fx-lbx-zoom').onclick = function () { var r = boxImg.getBoundingClientRect(); zToggle(r.left + r.width / 2, r.top + r.height / 2); };
    document.addEventListener('keydown', function (ev) {
      if (!box.classList.contains('is-on')) return;
      var r = boxImg.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      if (ev.key === '+' || ev.key === '=') zAt(cx, cy, zm.z * 1.5, true); else if (ev.key === '-') zAt(cx, cy, zm.z / 1.5, true); else if (ev.key === '0') zAt(cx, cy, 1, true);
    });
  }
  function show(i) {
    zReset();
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
    pushLayer(function () { zReset(); box.classList.remove('is-on'); boxImg.src = ''; if (lastFocus) lastFocus.focus({ preventScroll: true }); });
  }
  var byGroup = function (name) { return Array.prototype.slice.call(document.querySelectorAll('a.fx-lb[data-lb="' + name + '"]')); };

  // ---- Video player: any [data-video] (home video, project reel, process clips) opens full screen with controls ----
  var vbox = null, vEl = null;
  function openVideo(src, poster, t) {
    if (!vbox) {
      vbox = document.createElement('div'); vbox.className = 'fx-vbox'; vbox.setAttribute('role', 'dialog'); vbox.setAttribute('aria-modal', 'true');
      vbox.innerHTML = '<button type="button" class="fx-vbox-x" aria-label="Close">' + svg('M6 6l12 12M18 6L6 18') + '</button><video controls playsinline></video>';
      document.body.appendChild(vbox); vEl = vbox.querySelector('video');
      vbox.querySelector('.fx-vbox-x').onclick = closeTop;
      vbox.addEventListener('click', function (ev) { if (ev.target === vbox) closeTop(); });
    }
    vEl.poster = poster || ''; vEl.src = src; vEl.muted = false;
    vbox.classList.add('is-on');
    vEl.addEventListener('loadedmetadata', function once() { vEl.removeEventListener('loadedmetadata', once); if (t) try { vEl.currentTime = t; } catch (err) {} }, false);
    var p = vEl.play(); if (p && p.catch) p.catch(function () { vEl.muted = true; vEl.play().catch(function () {}); });
    Array.prototype.forEach.call(document.querySelectorAll('video[data-autoplay], #fxVideo'), function (x) { x.pause(); });
    pushLayer(function () { vEl.pause(); vEl.removeAttribute('src'); vEl.load(); vbox.classList.remove('is-on');
      Array.prototype.forEach.call(document.querySelectorAll('video[data-autoplay].is-vis, #fxVideo'), function (x) { x.play().catch(function () {}); }); });
  }
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest && ev.target.closest('[data-video]'); if (!b) return;
    ev.preventDefault();
    var inner = b.tagName === 'VIDEO' ? b : b.querySelector && b.querySelector('video');
    openVideo(b.getAttribute('data-video'), b.getAttribute('data-poster') || (inner && inner.getAttribute('poster')), inner && b.id === 'fxVideo' ? 0 : 0);
  });
  // silent process loops play only while visible
  var autos = document.querySelectorAll('video[data-autoplay]');
  if (autos.length && 'IntersectionObserver' in window) {
    var vio = new IntersectionObserver(function (es) { es.forEach(function (en) {
      var v = en.target; v.classList.toggle('is-vis', en.isIntersecting);
      if (en.isIntersecting) { if (!v.getAttribute('src')) v.src = v.dataset.src; v.play().catch(function () {}); } else v.pause();
    }); }, { rootMargin: '120px' });
    Array.prototype.forEach.call(autos, function (v) { vio.observe(v); });
  }

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

  // ---- Logo: on the home page it scrolls smoothly back to the very top (other pages link to the home page) ----
  var homeLogo = document.getElementById('fxLogo');
  if (homeLogo) homeLogo.addEventListener('click', function (ev) {
    ev.preventDefault();
    if (root.classList.contains('menu-open')) toggleMenu(false);
    if (location.hash) try { history.replaceState(history.state, '', location.pathname + location.search); } catch (err) {}
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
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
      var x = startX + (MARGIN - startX) * p, y = startY + (MARGIN - startY) * p, sc = 1 + (SMALL / size - 1) * p;
      // keep the badge below the language switcher / burger while it still reaches under them
      var top = document.querySelector('.fx-top .fx-langs');
      if (top) {
        var tr = top.getBoundingClientRect(), over = x + size * sc - (tr.left - 8);
        if (over > 0) y = Math.max(y, (tr.bottom + 8) * Math.min(1, over / 40));
      }
      logo.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + sc + ')';
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
