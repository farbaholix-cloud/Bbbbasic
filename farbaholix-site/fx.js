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


  // ---- WhatsApp: every [data-wa-form] opens a chat with the typed message ----
  var WA = '4915172450347';
  Array.prototype.forEach.call(document.querySelectorAll('[data-wa-form]'), function (f) {
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var name = f.elements.wa_name.value.trim(), msg = f.elements.wa_msg.value.trim();
      var text = (name ? f.elements.wa_hello.value.replace('{name}', name) + '\n' : '') + (msg || '') + '\n' + f.elements.wa_from.value;
      window.open('https://wa.me/' + WA + '?text=' + encodeURIComponent(text.trim()), '_blank', 'noopener');
    });
  });
  var fab = document.getElementById('fxWaFab'), pop = document.getElementById('fxWaPop');
  if (fab && pop) {
    var toggle = function (open) { pop.hidden = !open; fab.setAttribute('aria-expanded', open); if (open) { var t = pop.querySelector('textarea'); if (t) t.focus(); } };
    fab.addEventListener('click', function () { toggle(pop.hidden); });
    document.getElementById('fxWaPopX').addEventListener('click', function () { toggle(false); });
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

  // ---- Lightbox: every a.fx-lb opens its group (data-lb); [data-lb-open] opens a group from the start ----
  var box = null, group = [], cur = 0, boxImg, boxCap, boxN, lastFocus = null;
  function buildBox() {
    box = document.createElement('div'); box.className = 'fx-lbx'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    box.innerHTML = '<button type="button" class="fx-lbx-x" aria-label="Close">×</button><button type="button" class="fx-lbx-prev" aria-label="Previous">‹</button>' +
      '<figure><img alt=""><figcaption></figcaption></figure><button type="button" class="fx-lbx-next" aria-label="Next">›</button><span class="fx-lbx-n"></span>';
    document.body.appendChild(box);
    boxImg = box.querySelector('img'); boxCap = box.querySelector('figcaption'); boxN = box.querySelector('.fx-lbx-n');
    box.querySelector('.fx-lbx-x').onclick = closeBox;
    box.querySelector('.fx-lbx-prev').onclick = function () { show(cur - 1); };
    box.querySelector('.fx-lbx-next').onclick = function () { show(cur + 1); };
    box.addEventListener('click', function (ev) { if (ev.target === box) closeBox(); });
    var x0 = null;
    box.addEventListener('touchstart', function (ev) { x0 = ev.touches[0].clientX; }, { passive: true });
    box.addEventListener('touchend', function (ev) { if (x0 === null) return; var dx = ev.changedTouches[0].clientX - x0; if (Math.abs(dx) > 45) show(cur + (dx < 0 ? 1 : -1)); x0 = null; });
  }
  function show(i) {
    cur = (i + group.length) % group.length;
    var a = group[cur], im = a.querySelector('img');
    boxImg.src = a.href; boxImg.alt = im ? im.alt : (a.dataset.cap || '');
    boxCap.textContent = a.dataset.cap || (im ? im.alt : '');
    boxN.textContent = (cur + 1) + ' / ' + group.length;
    box.classList.toggle('is-single', group.length < 2);
    [cur + 1, cur - 1].forEach(function (n) { var p = group[(n + group.length) % group.length]; if (p) new Image().src = p.href; });
  }
  function openBox(name, start) {
    if (!box) buildBox();
    group = Array.prototype.slice.call(document.querySelectorAll('a.fx-lb[data-lb="' + name + '"]'));
    if (!group.length) return;
    lastFocus = document.activeElement;
    box.classList.add('is-on'); document.documentElement.classList.add('fx-noscroll');
    show(start || 0); box.querySelector('.fx-lbx-next').focus();
  }
  function closeBox() { box.classList.remove('is-on'); document.documentElement.classList.remove('fx-noscroll'); boxImg.src = ''; if (lastFocus) lastFocus.focus(); }
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest && ev.target.closest('a.fx-lb');
    if (a) { ev.preventDefault(); var list = Array.prototype.slice.call(document.querySelectorAll('a.fx-lb[data-lb="' + a.dataset.lb + '"]')); openBox(a.dataset.lb, list.indexOf(a)); return; }
    var b = ev.target.closest && ev.target.closest('[data-lb-open]');
    if (b) openBox(b.dataset.lbOpen, 0);
  });
  document.addEventListener('keydown', function (ev) {
    if (!box || !box.classList.contains('is-on')) return;
    if (ev.key === 'Escape') closeBox(); else if (ev.key === 'ArrowRight') show(cur + 1); else if (ev.key === 'ArrowLeft') show(cur - 1);
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
