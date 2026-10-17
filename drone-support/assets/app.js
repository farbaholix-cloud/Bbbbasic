/* Інтерфейс системи обліку. Маршрути — через #хеш, ролі: consultant / head. */
(function () {
  const A = Analytics, D = DICT;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = new Intl.NumberFormat('uk-UA');
  const num = (n, d) => nf.format(+(+n).toFixed(d || 0));
  const money = n => num(Math.round(n)) + ' ' + Store.settings().currency;
  const pct = x => Math.round(x * 100) + '%';
  const sec = s => s < 90 ? Math.round(s) + ' с' : Math.floor(s / 60) + ' хв ' + Math.round(s % 60) + ' с';
  const hm = t => new Date(t).toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
  const dm = t => new Date(t).toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit' });
  const dmy = t => new Date(t).toLocaleDateString('uk-UA');
  const dur = ms => { const m = Math.floor(ms / 6e4); return Math.floor(m / 60) + ' год ' + (m % 60) + ' хв'; };
  const inFrame = (() => { try { return window.self !== window.top; } catch (e) { return true; } })();
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* без збереження */ } }
  };
  const COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)', 'var(--s6)', 'var(--s7)', 'var(--s8)'];
  const LVL = { crit: 'Критично', warn: 'Увага', info: 'До відома', good: 'Добре' };

  const state = {
    user: null,
    period: ls.get('dss.period', 30),
    teamSort: { k: 'score', dir: -1 },
    draft: null,
    endingShift: false,
    propFilter: 'open'
  };

  /* ---------- Загальне ---------- */
  function toast(msg, kind) {
    const t = document.createElement('div');
    t.className = 'toast' + (kind ? ' toast-' + kind : '');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.classList.add('out'), 2600);
    setTimeout(() => t.remove(), 3000);
  }
  function download(name, text, type) {
    if (inFrame) { toast('Завантаження доступне у повній версії системи'); return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: type || 'text/plain' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  function copyText(text, btn) {
    const done = () => toast('Скопійовано');
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback());
    else fallback();
    function fallback() {
      const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { toast('Виділіть текст і скопіюйте вручну'); }
      ta.remove();
    }
  }
  function users(role) { return Store.all('users').filter(u => !role || u.role === role); }
  function userName(id) { const u = Store.byId('users', id); return u ? u.name : '—'; }
  function openShift(uid) { return Store.all('shifts').find(s => s.uid === uid && !s.end); }
  function rg() { return A.range(state.period); }
  function delta(cur, prev, better, fmt) {
    if (!prev) return '';
    const d = cur - prev; if (Math.abs(d) < 1e-9) return '<span class="delta">без змін</span>';
    const good = better === 'up' ? d > 0 : d < 0;
    return `<span class="delta ${good ? 'up' : 'down'}">${d > 0 ? '▲' : '▼'} ${fmt(Math.abs(d))}</span>`;
  }
  function tile(label, value, sub, extra) {
    return `<div class="tile${extra && extra.cls ? ' ' + extra.cls : ''}"><span class="tile-label">${label}</span><span class="tile-value">${value}</span><span class="tile-sub">${sub || ''}</span></div>`;
  }
  function statusPill(ok, textOk, textBad) {
    return ok ? `<span class="pill pill-good">✓ ${textOk}</span>` : `<span class="pill pill-crit">! ${textBad}</span>`;
  }
  function periodPicker() {
    return `<div class="seg period" role="group" aria-label="Період">${[7, 30, 90].map(p => `<button type="button" data-period="${p}" class="${state.period === p ? 'on' : ''}">${p} днів</button>`).join('')}</div>`;
  }

  /* ---------- Вхід ---------- */
  function renderLogin() {
    const list = users().filter(u => u.active).sort((a, b) => (a.role === 'head' ? -1 : 1) - (b.role === 'head' ? -1 : 1) || a.name.localeCompare(b.name));
    document.body.dataset.view = 'login';
    $('#app').innerHTML = `
      <div class="login">
        <div class="login-brand">
          <div class="mark" aria-hidden="true">${logoSvg()}</div>
          <div><div class="eyebrow">${esc(DSS_CONFIG.company)}</div><h1>${esc(DSS_CONFIG.department)}</h1>
          <p class="muted">Облік чергувань, звернень з лінії фронту та ефективності команди.</p></div>
        </div>
        <form class="card login-card" id="login-form" autocomplete="off">
          <label class="field"><span>Хто ви</span>
            <select id="login-user" required>
              <option value="">Оберіть себе зі списку</option>
              ${list.map(u => `<option value="${u.id}">${esc(u.name)}${u.role === 'head' ? ' — керівник' : ''}</option>`).join('')}
            </select></label>
          <label class="field"><span>PIN-код</span><input id="login-pin" type="password" inputmode="numeric" maxlength="8" required placeholder="••••"></label>
          <button class="btn btn-primary btn-block" type="submit">Увійти</button>
          ${Store.db.demo ? '<p class="hint">Демо-режим. PIN керівника — 0000, консультантів — 1111.</p>' : ''}
        </form>
      </div>`;
    $('#login-form').addEventListener('submit', e => {
      e.preventDefault();
      const u = Store.byId('users', $('#login-user').value);
      if (!u || u.pin !== $('#login-pin').value) { toast('Невірний PIN. Перевірте і спробуйте ще раз', 'crit'); return; }
      state.user = u; ls.set('dss.session', u.id);
      location.hash = u.role === 'head' ? 'overview' : 'duty';
      route();
    });
  }

  function logoSvg() {
    return `<svg viewBox="0 0 40 40" width="40" height="40"><rect width="40" height="40" rx="9" fill="var(--accent)"/><g stroke="var(--on-accent)" stroke-width="2.4" fill="none" stroke-linecap="round"><circle cx="11" cy="11" r="5"/><circle cx="29" cy="11" r="5"/><circle cx="11" cy="29" r="5"/><circle cx="29" cy="29" r="5"/><path d="M15 15l10 10M25 15L15 25"/></g><rect x="17" y="17" width="6" height="6" rx="1.5" fill="var(--amber)"/></svg>`;
  }

  /* ---------- Оболонка ---------- */
  const NAV = {
    consultant: [
      { id: 'duty', label: 'Чергування', render: viewDuty },
      { id: 'mine', label: 'Мої показники', render: viewMine },
      { id: 'history', label: 'Мої звернення', render: viewHistory }
    ],
    head: [
      { id: 'overview', label: 'Огляд', render: viewOverview },
      { id: 'team', label: 'Команда', render: viewTeam },
      { id: 'load', label: 'Навантаження і штат', render: viewLoad },
      { id: 'finance', label: 'Фінанси', render: viewFinance },
      { id: 'recs', label: 'Рекомендації', render: viewRecs },
      { id: 'proposals', label: 'Пропозиції', render: viewProposals },
      { id: 'report', label: 'Звіт керівництву', render: viewReport },
      { id: 'staff', label: 'Персонал', render: viewStaff },
      { id: 'settings', label: 'Налаштування', render: viewSettings }
    ]
  };

  function shell(active) {
    const u = state.user;
    const nav = NAV[u.role];
    const newProps = Store.all('proposals').filter(p => p.status === 'new').length;
    return `
      <header class="top">
        <div class="top-in">
          <a class="brand" href="#${nav[0].id}"><span class="mark">${logoSvg()}</span><span class="brand-text"><b>${esc(DSS_CONFIG.department)}</b><small>${esc(DSS_CONFIG.company)}</small></span></a>
          <div class="top-actions">
            ${Store.db.demo ? '<span class="pill pill-demo" title="Показано демонстраційні дані">Демо-дані</span>' : ''}
            <button class="icon-btn" id="theme-btn" type="button" title="Тема оформлення" aria-label="Тема оформлення">${themeIcon()}</button>
            <button class="icon-btn user-btn" id="logout-btn" type="button" title="Вийти"><span class="avatar">${initials(u.name)}</span><span class="user-name">${esc(u.name)}</span><span aria-hidden="true">⎋</span></button>
            <button class="btn btn-reg" id="reg-btn" type="button" aria-haspopup="dialog"><span class="reg-ico" aria-hidden="true">§</span><span class="reg-long">Генеральний регламент</span><span class="reg-short">Регламент</span></button>
          </div>
        </div>
        <nav class="tabs" aria-label="Розділи"><div class="tabs-in">
          ${nav.map(n => `<a href="#${n.id}" class="${n.id === active ? 'on' : ''}">${n.label}${n.id === 'proposals' && newProps ? ` <span class="badge">${newProps}</span>` : ''}</a>`).join('')}
        </div></nav>
      </header>
      <main id="view" class="wrap"></main>
      ${proposalFooter()}
    `;
  }
  function initials(n) { return n.split(' ').map(x => x[0]).slice(0, 2).join(''); }

  function route() {
    const id = ls.get('dss.session', null);
    state.user = id ? Store.byId('users', id) : null;
    if (!state.user || !state.user.active) { renderLogin(); return; }
    const nav = NAV[state.user.role];
    let view = location.hash.replace('#', '');
    if (!nav.some(n => n.id === view)) view = nav[0].id;
    document.body.dataset.view = view;
    $('#app').innerHTML = shell(view);
    bindShell();
    const v = nav.find(n => n.id === view);
    v.render($('#view'));
    $('#view').focus({ preventScroll: true });
  }
  function rerender() { const y = scrollY; route(); scrollTo(0, y); }

  function bindShell() {
    $('#logout-btn').onclick = () => { ls.set('dss.session', null); state.user = null; location.hash = ''; renderLogin(); };
    $('#reg-btn').onclick = () => openReglament();
    $('#theme-btn').onclick = cycleTheme;
    bindProposalForm();
  }

  /* ---------- Тема ---------- */
  function themeIcon() { const t = ls.get('dss.theme', 'system'); return t === 'dark' ? '☾' : t === 'light' ? '☀' : '◐'; }
  function applyTheme() { const t = ls.get('dss.theme', 'system'); if (t === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t); }
  function cycleTheme() {
    const order = ['system', 'light', 'dark'];
    const t = order[(order.indexOf(ls.get('dss.theme', 'system')) + 1) % 3];
    ls.set('dss.theme', t); applyTheme(); $('#theme-btn').textContent = themeIcon();
    toast(t === 'system' ? 'Тема: як у системі' : t === 'light' ? 'Тема: світла' : 'Тема: темна');
    rerender();
  }

  /* ---------- Регламент ---------- */
  function reglamentItems() {
    const out = [];
    REGLAMENT.sections.forEach(s => s.items.forEach(([id, text]) => out.push({ id, text, section: s })));
    return out;
  }
  function openReglament(focusId) {
    let dlg = $('#reg-dialog');
    if (!dlg) {
      dlg = document.createElement('div');
      dlg.id = 'reg-dialog'; dlg.className = 'drawer'; dlg.setAttribute('role', 'dialog'); dlg.setAttribute('aria-modal', 'true'); dlg.setAttribute('aria-label', 'Генеральний регламент');
      document.body.appendChild(dlg);
    }
    const R = REGLAMENT;
    const accepted = Store.all('proposals').filter(p => p.status === 'accepted');
    dlg.innerHTML = `
      <div class="drawer-scrim" data-close></div>
      <aside class="drawer-panel">
        <div class="drawer-head">
          <div><div class="eyebrow">Редакція ${R.version} · ${dmy(R.date)} · ${esc(R.status)}</div><h2>Генеральний регламент</h2></div>
          <button class="icon-btn" data-close type="button" aria-label="Закрити">✕</button>
        </div>
        <div class="drawer-tools">
          <input type="search" id="reg-search" placeholder="Пошук у регламенті: «нічні», «ОПСЕК», «30 секунд»" aria-label="Пошук у регламенті">
          ${inFrame ? '' : '<button class="btn btn-ghost" id="reg-md" type="button">Завантажити .md</button>'}
        </div>
        <div class="drawer-body">
          <nav class="reg-toc">${R.sections.map(s => `<a href="#" data-goto="s${s.id}"><b>${s.id}</b> ${esc(s.title)}</a>`).join('')}</nav>
          <div class="reg-text">
            ${R.sections.map(s => `
              <section class="reg-sec" id="s${s.id}"><h3><span>${s.id}.</span> ${esc(s.title)}</h3>
                ${s.items.map(([id, text]) => `<div class="reg-item" id="ri-${id}" data-text="${esc((id + ' ' + text).toLowerCase())}"><span class="reg-num">${id}</span><p>${esc(text)}</p><button class="link" type="button" data-propose="${id}">Запропонувати зміну</button></div>`).join('')}
              </section>`).join('')}
            <section class="reg-sec"><h3>Журнал змін</h3>
              ${R.changelog.map(c => `<p><b>${c.version}</b> · ${dmy(c.date)} — ${esc(c.text)}</p>`).join('')}
              ${accepted.length ? `<h4>Прийняті пропозиції, що увійдуть у наступну редакцію</h4>${accepted.map(p => `<p><b>п. ${esc(p.section)}</b> — ${esc(p.text)} <span class="muted">(${esc(userName(p.uid))})</span></p>`).join('')}` : ''}
            </section>
            <p class="reg-empty muted" hidden>Нічого не знайдено. Спробуйте інше слово.</p>
          </div>
        </div>
      </aside>`;
    dlg.hidden = false;
    document.body.classList.add('no-scroll');
    const close = () => { dlg.hidden = true; document.body.classList.remove('no-scroll'); };
    $$('[data-close]', dlg).forEach(b => b.onclick = close);
    dlg.onkeydown = e => { if (e.key === 'Escape') close(); };
    $$('[data-goto]', dlg).forEach(a => a.onclick = e => { e.preventDefault(); $('#' + a.dataset.goto, dlg).scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    $$('[data-propose]', dlg).forEach(b => b.onclick = () => {
      close();
      const sel = $('#prop-section'); if (!sel) return;
      sel.value = b.dataset.propose;
      $('#proposal').scrollIntoView({ behavior: 'smooth' });
      setTimeout(() => $('#prop-text').focus(), 400);
    });
    $('#reg-search', dlg).oninput = e => {
      const q = e.target.value.trim().toLowerCase();
      let any = false;
      $$('.reg-sec', dlg).forEach(sec => {
        let vis = 0;
        $$('.reg-item', sec).forEach(it => { const show = !q || it.dataset.text.includes(q); it.hidden = !show; if (show) vis++; });
        sec.hidden = !!q && !vis && !!$('.reg-item', sec); if (vis) any = true;
      });
      $('.reg-empty', dlg).hidden = !q || any;
    };
    const md = $('#reg-md', dlg); if (md) md.onclick = () => download('reglament-' + R.version + '.md', reglamentMarkdown(), 'text/markdown');
    $('#reg-search', dlg).focus();
    if (focusId) { const it = $('#ri-' + CSS.escape(focusId), dlg); if (it) { it.scrollIntoView({ block: 'center' }); it.classList.add('flash'); } }
  }
  function reglamentMarkdown() {
    const R = REGLAMENT;
    return `# ${R.title}\n\nРедакція ${R.version} від ${R.date}. Статус: ${R.status}.\n\n` +
      R.sections.map(s => `## ${s.id}. ${s.title}\n\n` + s.items.map(([id, t]) => `**${id}.** ${t}`).join('\n\n')).join('\n\n') + '\n';
  }

  /* ---------- Форма пропозицій (внизу кожної сторінки) ---------- */
  function proposalFooter() {
    const mine = Store.all('proposals').filter(p => p.uid === state.user.id);
    const st = { new: 'нова', review: 'на розгляді', accepted: 'прийнята', rejected: 'відхилена' };
    return `
      <footer class="foot" id="proposal">
        <div class="wrap foot-in">
          <div class="foot-intro">
            <div class="eyebrow">Регламент 13.1</div>
            <h2>Пропозиція змін до регламенту</h2>
            <p class="muted">Бачите, що правило заважає працювати або чогось бракує — напишіть. Керівник відділу розгляне пропозицію протягом 7 днів.</p>
            ${mine.length ? `<ul class="my-props">${mine.slice(-3).reverse().map(p => `<li><span class="pill pill-${p.status}">${st[p.status]}</span> п. ${esc(p.section)} — ${esc(p.text.slice(0, 70))}${p.text.length > 70 ? '…' : ''}${p.comment ? `<br><span class="muted">Відповідь: ${esc(p.comment)}</span>` : ''}</li>`).join('')}</ul>` : ''}
          </div>
          <form class="foot-form" id="prop-form">
            <label class="field"><span>Пункт регламенту</span>
              <select id="prop-section" required>
                <option value="new">Новий пункт</option>
                ${REGLAMENT.sections.map(s => `<optgroup label="${s.id}. ${esc(s.title)}">${s.items.map(([id, t]) => `<option value="${id}">${id} — ${esc(t.slice(0, 60))}…</option>`).join('')}</optgroup>`).join('')}
              </select></label>
            <label class="field"><span>Що змінити</span><textarea id="prop-text" rows="3" required minlength="10" placeholder="Нове формулювання або що саме додати"></textarea></label>
            <label class="field"><span>Чому це важливо</span><textarea id="prop-reason" rows="2" placeholder="Випадок з практики, цифри, ризик"></textarea></label>
            <div class="row-end"><button class="btn btn-ghost" type="button" id="prop-view">Відкрити пункт</button><button class="btn btn-primary" type="submit">Надіслати пропозицію</button></div>
          </form>
        </div>
      </footer>`;
  }
  function bindProposalForm() {
    const f = $('#prop-form'); if (!f) return;
    $('#prop-view').onclick = () => openReglament($('#prop-section').value === 'new' ? null : $('#prop-section').value);
    f.addEventListener('submit', e => {
      e.preventDefault();
      const text = $('#prop-text').value.trim();
      if (text.length < 10) { toast('Опишіть пропозицію хоча б одним реченням', 'crit'); return; }
      Store.put('proposals', { uid: state.user.id, ts: Date.now(), section: $('#prop-section').value, text, reason: $('#prop-reason').value.trim(), status: 'new', comment: '' });
      toast('Пропозицію надіслано керівнику відділу', 'good');
      rerender();
    });
  }

  /* ================= КОНСУЛЬТАНТ ================= */
  function newDraft() {
    const last = Store.all('requests').filter(q => q.uid === state.user.id).sort((a, b) => b.ts - a.ts)[0];
    return { ch: last ? last.ch : 'sig', pr: 'high', type: null, prod: last ? last.prod : D.products[0], frt: '', dur: '', out: 'ok', back: false, note: '', rate: null, swStart: null };
  }

  function viewDuty(main) {
    const u = state.user, sh = openShift(u.id);
    if (!sh) {
      const last = Store.all('shifts').filter(s => s.uid === u.id && s.end).sort((a, b) => b.start - a.start)[0];
      const lastReq = last ? Store.all('requests').filter(q => q.sid === last.id) : [];
      main.innerHTML = `
        <section class="duty-off card">
          <div class="eyebrow">${dmy(Date.now())}</div>
          <h1>Ви не на чергуванні</h1>
          <p class="muted">Коли заступаєте на зміну — натисніть кнопку. Час початку зафіксується автоматично (регламент 3.4).</p>
          <button class="btn btn-primary btn-xl" id="start-shift" type="button">Заступити на чергування</button>
          ${last ? `<div class="last-shift"><span class="muted">Остання зміна:</span> ${dmy(last.start)}, ${hm(last.start)}–${hm(last.end)} · ${lastReq.length} звернень${last.handover ? `<br><span class="muted">Нотатка передачі:</span> ${esc(last.handover)}` : ''}</div>` : ''}
        </section>
        ${handoverFromOthers()}`;
      $('#start-shift').onclick = () => {
        Store.put('shifts', { uid: u.id, start: Date.now(), end: null, fatigue: null, handover: '' });
        state.draft = newDraft(); toast('Чергування розпочато', 'good'); rerender();
      };
      return;
    }
    if (!state.draft) state.draft = newDraft();
    const d = state.draft;
    const reqs = Store.all('requests').filter(q => q.sid === sh.id).sort((a, b) => b.ts - a.ts);
    const frtMed = A.median(reqs.map(q => q.frt));
    const okN = reqs.filter(q => q.out === 'ok').length;
    const chip = (name, list, cur) => list.map(x => `<button type="button" class="chip${cur === x.id ? ' on' : ''}" data-f="${name}" data-v="${x.id}">${esc(x.label)}${x.hint ? `<small>${x.hint}</small>` : ''}</button>`).join('');

    main.innerHTML = `
      <section class="duty-bar">
        <div class="duty-status"><span class="live-dot" aria-hidden="true"></span><div><b>На чергуванні з ${hm(sh.start)}</b><span class="muted" data-since="${sh.start}">${dur(Date.now() - sh.start)}</span></div></div>
        <div class="duty-nums">
          <div><span class="n">${reqs.length}</span><span class="l">звернень</span></div>
          <div><span class="n">${reqs.length ? sec(frtMed) : '—'}</span><span class="l">медіана відповіді</span></div>
          <div><span class="n">${reqs.length ? pct(okN / reqs.length) : '—'}</span><span class="l">вирішено</span></div>
        </div>
        <button class="btn btn-ghost" id="end-shift" type="button">Здати зміну</button>
      </section>

      ${state.endingShift ? `
      <form class="card end-card" id="end-form">
        <h2>Здача зміни</h2>
        <div class="field"><span>Як ви почуваєтесь після зміни? <small class="muted">Бачить лише керівник, для планування ротації (7.4)</small></span>
          <div class="chips" id="fatigue">${[1, 2, 3, 4, 5].map(v => `<button type="button" class="chip" data-fat="${v}">${v}<small>${['виснажений', 'дуже втомлений', 'втомлений', 'нормально', 'бадьорий'][v - 1]}</small></button>`).join('')}</div></div>
        <label class="field"><span>Нотатка передачі зміни</span><textarea id="handover" rows="3" placeholder="Незакриті звернення, нові типові проблеми, на що звернути увагу"></textarea></label>
        <div class="row-end"><button class="btn btn-ghost" type="button" id="end-cancel">Скасувати</button><button class="btn btn-primary" type="submit">Здати зміну о ${hm(Date.now())}</button></div>
      </form>` : ''}

      <div class="duty-grid">
        <form class="card req-form" id="req-form" novalidate>
          <div class="card-head"><h2>Нове звернення</h2><span class="muted">${reqs.length + 1}-е за зміну</span></div>

          <div class="stopwatch">
            <div class="sw-display" id="sw-display">${d.swStart ? '0 с' : (d.frt !== '' ? d.frt + ' с' : '— с')}</div>
            <div class="sw-btns">
              <button type="button" class="btn ${d.swStart ? 'btn-ghost' : 'btn-primary'}" id="sw-start">${d.swStart ? 'Скинути' : 'Отримав повідомлення'}</button>
              <button type="button" class="btn btn-amber" id="sw-stop" ${d.swStart ? '' : 'disabled'}>Відповів</button>
            </div>
            <label class="field sw-manual"><span>або вручну, с</span><input id="f-frt" type="number" min="0" max="86400" inputmode="numeric" value="${esc(d.frt)}"></label>
          </div>

          <div class="field"><span>Канал</span><div class="chips">${chip('ch', D.channels, d.ch)}</div></div>
          <div class="field"><span>Пріоритет</span><div class="chips chips-3">${chip('pr', D.priorities, d.pr)}</div></div>
          <div class="field"><span>Тип звернення</span><div class="chips chips-grid">${chip('type', D.types.map(t => ({ id: t.id, label: t.short })), d.type)}</div></div>
          <div class="field-row">
            <label class="field"><span>Виріб</span><select id="f-prod">${D.products.map(p => `<option${p === d.prod ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select></label>
            <label class="field"><span>Тривалість обробки, хв</span><input id="f-dur" type="number" min="1" max="600" inputmode="numeric" value="${esc(d.dur)}" placeholder="напр. 12"></label>
          </div>
          <div class="field"><span>Результат</span><div class="chips">${chip('out', D.outcomes, d.out)}</div></div>
          <label class="toggle"><input type="checkbox" id="f-back" ${d.back ? 'checked' : ''}><span>Техніку повернуто в стрій <small class="muted">виріб, що не працював, виконує завдання (6.3)</small></span></label>
          <label class="field"><span>Висновок <small class="muted">причина і що допомогло · без координат, частин і позивних (8.1)</small></span>
            <textarea id="f-note" rows="3" placeholder="Напр.: збився біндинг ELRS після заміни приймача, перев'язали за 3 хв">${esc(d.note)}</textarea></label>
          <p class="opsec-warn" id="opsec-warn" hidden></p>
          <div class="field"><span>Оцінка оператора, якщо дав <small class="muted">необов'язково</small></span><div class="chips chips-5">${[1, 2, 3, 4, 5].map(v => `<button type="button" class="chip${d.rate === v ? ' on' : ''}" data-f="rate" data-v="${v}">${v} ★</button>`).join('')}</div></div>
          <button class="btn btn-primary btn-block btn-xl" type="submit">Зберегти звернення</button>
        </form>

        <section class="card today">
          <div class="card-head"><h2>За цю зміну</h2><span class="muted">${reqs.length}</span></div>
          ${reqs.length ? `<ul class="req-list">${reqs.map(q => reqRow(q, true)).join('')}</ul>` : '<p class="empty">Звернень ще немає. Перше збережене звернення з\'явиться тут.</p>'}
        </section>
      </div>`;

    bindDuty(sh);
  }

  function reqRow(q, editable) {
    const pr = { crit: 'crit', high: 'warn', norm: 'info' }[q.pr];
    const out = { ok: 'good', esc: 'warn', rma: 'crit', wait: 'info' }[q.out];
    const slow = q.frt > (D.priorities.find(p => p.id === q.pr) || {}).sla;
    return `<li class="req">
      <div class="req-top"><span class="req-time">${hm(q.ts)}</span><span class="pill pill-${pr}">${D.label('priorities', q.pr)}</span><b>${D.label('types', q.type)}</b><span class="muted">${D.label('channels', q.ch)} · ${esc(q.prod)}</span></div>
      <div class="req-meta"><span class="${slow ? 'bad' : ''}">відповідь ${sec(q.frt)}</span><span>${q.dur} хв</span><span class="pill pill-${out}">${D.label('outcomes', q.out)}</span>${q.back ? '<span class="pill pill-good">в строю</span>' : ''}${q.rate ? `<span>${'★'.repeat(q.rate)}</span>` : ''}</div>
      ${q.note ? `<p class="req-note">${esc(q.note)}</p>` : ''}
      ${editable ? `<button class="link danger" type="button" data-del="${q.id}">Видалити</button>` : ''}
    </li>`;
  }

  const OPSEC = [
    [/\b\d{1,2}[.,]\d{4,}/, 'схоже на координати'],
    [/\b\d{2}\s?[A-Z]{1,3}\s?\d{3,}/i, 'схоже на координати MGRS'],
    [/в\s?\/\s?ч|\bвч\s?\d|\bА\s?\d{4}\b|\bA\s?\d{4}\b/i, 'схоже на номер військової частини'],
    [/координат|бригад[аиі]\s*\d|батальйон\s*\d/i, 'згадка про координати або підрозділ'],
    [/\+?380\d{9}|\b0\d{9}\b/, 'схоже на номер телефону']
  ];
  function opsecCheck(text) { const hit = OPSEC.find(([re]) => re.test(text)); return hit ? hit[1] : null; }

  function bindDuty(sh) {
    const d = state.draft;
    $('#end-shift').onclick = () => { state.endingShift = true; rerender(); setTimeout(() => $('#end-form') && $('#end-form').scrollIntoView({ behavior: 'smooth', block: 'center' }), 50); };
    const ef = $('#end-form');
    if (ef) {
      let fat = null;
      $$('[data-fat]', ef).forEach(b => b.onclick = () => { fat = +b.dataset.fat; $$('[data-fat]', ef).forEach(x => x.classList.toggle('on', x === b)); });
      $('#end-cancel').onclick = () => { state.endingShift = false; rerender(); };
      ef.onsubmit = e => {
        e.preventDefault();
        if (!fat) { toast('Оцініть, як почуваєтесь — це займе секунду', 'crit'); return; }
        Object.assign(sh, { end: Date.now(), fatigue: fat, handover: $('#handover').value.trim() });
        Store.put('shifts', sh);
        state.endingShift = false; state.draft = null;
        toast('Зміну здано. Дякуємо за роботу!', 'good'); rerender();
      };
    }
    $$('.req-form .chip[data-f]').forEach(b => b.onclick = () => {
      const f = b.dataset.f; let v = b.dataset.v; if (f === 'rate') v = d.rate === +v ? null : +v;
      d[f] = v;
      $$(`.req-form .chip[data-f="${f}"]`).forEach(x => x.classList.toggle('on', String(d[f]) === x.dataset.v));
      if (f === 'out' && v !== 'ok') { d.back = false; $('#f-back').checked = false; }
    });
    $('#f-frt').oninput = e => { d.frt = e.target.value; $('#sw-display').textContent = (d.frt || '—') + ' с'; };
    $('#f-dur').oninput = e => d.dur = e.target.value;
    $('#f-prod').onchange = e => d.prod = e.target.value;
    $('#f-back').onchange = e => d.back = e.target.checked;
    $('#f-note').oninput = e => { d.note = e.target.value; const w = opsecCheck(d.note); $('#opsec-warn').hidden = !w; if (w) $('#opsec-warn').textContent = `ОПСЕК: ${w}. Приберіть це з висновку (регламент 8.1).`; };
    $('#sw-start').onclick = () => {
      if (d.swStart) { d.swStart = null; d.frt = ''; } else { d.swStart = Date.now(); d.frt = ''; }
      rerender();
    };
    $('#sw-stop').onclick = () => {
      if (!d.swStart) return;
      d.frt = String(Math.round((Date.now() - d.swStart) / 1000)); d.swStart = null;
      if (!d.dur) d.dur = '';
      rerender();
    };
    $('#req-form').onsubmit = e => {
      e.preventDefault();
      const errs = [];
      if (d.frt === '' || isNaN(+d.frt)) errs.push('час першої відповіді');
      if (!d.type) errs.push('тип звернення');
      if (!d.dur || +d.dur < 1) errs.push('тривалість обробки');
      if ((d.note || '').trim().length < 10) errs.push('висновок (1–3 речення)');
      if (errs.length) { toast('Заповніть: ' + errs.join(', '), 'crit'); return; }
      const w = opsecCheck(d.note); if (w) { toast('ОПСЕК: ' + w + '. Виправте висновок', 'crit'); return; }
      Store.put('requests', {
        uid: state.user.id, sid: sh.id, ts: Date.now(), ch: d.ch, type: d.type, pr: d.pr, prod: d.prod,
        frt: Math.round(+d.frt), dur: Math.round(+d.dur), out: d.out, back: !!d.back, rate: d.rate, note: d.note.trim()
      });
      state.draft = newDraft();
      toast('Звернення збережено', 'good'); rerender();
    };
    $$('[data-del]').forEach(b => b.onclick = () => {
      if (b.dataset.armed) { Store.remove('requests', b.dataset.del); toast('Звернення видалено'); rerender(); return; }
      b.dataset.armed = '1'; b.textContent = 'Натисніть ще раз, щоб видалити';
      setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = 'Видалити'; } }, 3000);
    });
  }

  function handoverFromOthers() {
    const notes = Store.all('shifts').filter(s => s.end && s.handover && s.end > Date.now() - A.DAY).sort((a, b) => b.end - a.end).slice(0, 3);
    if (!notes.length) return '';
    return `<section class="card"><h2>Нотатки передачі за добу</h2><ul class="notes">${notes.map(s => `<li><b>${esc(userName(s.uid))}</b> <span class="muted">${dm(s.end)} ${hm(s.end)}</span><p>${esc(s.handover)}</p></li>`).join('')}</ul></section>`;
  }

  function viewMine(main) {
    const r = rg(), now = Date.now();
    const T = A.team(Store.db, r, now);
    const me = T.find(t => t.u.id === state.user.id);
    const all = A.kpi(Store.all('requests'), Store.all('shifts'), r.start, r.end, now);
    const k = me.k;
    const fin = A.finance(Store.db, r, now);
    const myBonus = (fin.bonuses.find(b => b.t.u.id === state.user.id) || {}).bonus || 0;
    const ranked = T.filter(t => t.score != null).sort((a, b) => b.score - a.score);
    const place = ranked.findIndex(t => t.u.id === state.user.id) + 1;
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Особисті показники</div><h1>${esc(state.user.name)}</h1></div>${periodPicker()}</div>
      <section class="score-card card">
        <div class="score-ring" style="--v:${me.score || 0}"><span>${me.score != null ? me.score : '—'}</span><small>з 100</small></div>
        <div><h2>Інтегральний показник</h2>
          <p class="muted">Швидкість відповіді 30% · вирішені 30% · продуктивність 20% · оцінки операторів 10% · дисципліна обліку 10% (регламент 11.1).</p>
          <p>${place ? `${place}-е місце з ${ranked.length} у відділі.` : ''} ${me.scorePrev != null ? delta(me.score, me.scorePrev, 'up', v => v + ' б.') + ' до попереднього періоду' : ''}</p>
          ${myBonus ? `<p>Орієнтовна премія за період: <b>${money(myBonus)}</b></p>` : (me.score != null ? '<p class="muted">Премія нараховується з показника 60 і вище (11.2).</p>' : '')}
        </div>
      </section>
      <div class="tiles">
        ${tile('Звернень', num(k.count), `${num(k.perHour, 2)} на годину · по відділу ${num(all.perHour, 2)}`)}
        ${tile('Медіана першої відповіді', k.count ? sec(k.frtMed) : '—', `по відділу ${sec(all.frtMed)} · ціль ${Store.settings().targetFrtSec} с`)}
        ${tile('Вирішено', k.count ? pct(k.resolve) : '—', `по відділу ${pct(all.resolve)}`)}
        ${tile('Повернуто в стрій', num(k.back), 'одиниць техніки')}
        ${tile('Чергувань', num(k.shifts), `${num(k.hours)} год · нічних ${me.nights}`)}
        ${tile('Оцінка операторів', k.ratingN ? num(k.rating, 1) + ' ★' : '—', `${k.ratingN} відгуків`)}
      </div>
      <div class="grid-2">
        <section class="card"><h2>Мої звернення по днях</h2><div id="ch-my-daily"></div></section>
        <section class="card"><h2>Типи звернень</h2><div id="ch-my-types"></div></section>
      </div>`;
    const days = A.daily({ requests: Store.all('requests').filter(q => q.uid === state.user.id) }, r);
    Charts.line($('#ch-my-daily'), days.map(x => ({ y: x.n, label: dm(x.t) })), { name: 'Звернень', aria: 'Кількість моїх звернень по днях' });
    const types = A.groupBy(k.R, 'type', D.types).sort((a, b) => b.n - a.n);
    Charts.bars($('#ch-my-types'), types.map(t => ({ label: t.label, value: t.n, tip: `<b>${t.label}</b><span>${t.n} звернень · вирішено ${pct(t.resolve)} · відповідь ${sec(t.frt)}</span>` })));
    bindPeriod();
  }

  function viewHistory(main) {
    const mine = Store.all('requests').filter(q => q.uid === state.user.id).sort((a, b) => b.ts - a.ts).slice(0, 150);
    let lastDay = '';
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Останні 150</div><h1>Мої звернення</h1></div></div>
      <section class="card">${mine.length ? `<ul class="req-list">${mine.map(q => { const day = dmy(q.ts); const head = day !== lastDay ? `<li class="day-sep">${day}</li>` : ''; lastDay = day; return head + reqRow(q, false); }).join('')}</ul>` : '<p class="empty">Тут з\'являться ваші звернення після першого чергування.</p>'}</section>`;
  }

  /* ================= КЕРІВНИК ================= */
  function bindPeriod() {
    $$('[data-period]').forEach(b => b.onclick = () => { state.period = +b.dataset.period; ls.set('dss.period', state.period); rerender(); });
  }

  function viewOverview(main) {
    const r = rg(), now = Date.now(), S = Store.settings();
    const k = A.kpi(Store.all('requests'), Store.all('shifts'), r.start, r.end, now);
    const kp = A.kpi(Store.all('requests'), Store.all('shifts'), r.prevStart, r.prevEnd, now);
    const onDuty = Store.all('shifts').filter(s => !s.end).map(s => ({ s, u: Store.byId('users', s.uid) })).filter(x => x.u);
    const recs = A.recommendations(Store.db, r, now);
    const fin = A.finance(Store.db, r, now);
    const today = A.kpi(Store.all('requests'), Store.all('shifts'), new Date().setHours(0, 0, 0, 0), now, now);
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Стан відділу · останні ${state.period} днів</div><h1>Огляд</h1></div>${periodPicker()}</div>

      <section class="now card">
        <div class="now-l"><span class="live-dot"></span><div><b>Зараз на чергуванні: ${onDuty.length}</b><span class="muted">${onDuty.map(x => esc(x.u.name.split(' ')[0]) + ' з ' + hm(x.s.start)).join(' · ') || 'нікого'}</span></div></div>
        <div class="now-r"><span>Сьогодні: <b>${today.count}</b> звернень</span><span>медіана відповіді <b>${today.count ? sec(today.frtMed) : '—'}</b></span><span>критичних <b>${today.crit}</b></span>${onDuty.length < 2 ? '<span class="pill pill-crit">! менше двох на зміні (3.2)</span>' : ''}</div>
      </section>

      <div class="tiles tiles-hero">
        ${tile('Звернень з фронту', num(k.count), delta(k.count, kp.count, 'up', v => num(v)) + ` · ${num(k.count / state.period, 0)} на добу`)}
        ${tile('Медіана першої відповіді', sec(k.frtMed), `${statusPill(k.frtMed <= S.targetFrtSec, 'ціль ' + S.targetFrtSec + ' с', 'ціль ' + S.targetFrtSec + ' с')} ${delta(k.frtMed, kp.frtMed, 'down', v => Math.round(v) + ' с')}`)}
        ${tile('Вирішено на першій лінії', pct(k.resolve), `${statusPill(k.resolve >= S.targetResolve, 'ціль ' + pct(S.targetResolve), 'ціль ' + pct(S.targetResolve))} ${delta(k.resolve * 100, kp.resolve * 100, 'up', v => v.toFixed(1) + ' п.п.')}`)}
        ${tile('Критичні за 30 с', pct(k.critSla), `${num(k.crit)} критичних звернень ${statusPill(k.critSla >= 0.9, 'норма', 'нижче 90%')}`)}
        ${tile('Техніки повернуто в стрій', num(k.back), `≈ ${money(fin.effect)} умовного ефекту`)}
        ${tile('Вартість одного звернення', money(fin.costPerReq), `витрати за період ${money(fin.total)}`)}
      </div>

      <div class="grid-2">
        <section class="card"><div class="card-head"><h2>Звернення по днях</h2><span class="muted">шт. на добу</span></div><div id="ch-daily"></div></section>
        <section class="card"><div class="card-head"><h2>Медіана першої відповіді</h2><span class="muted">секунд, по днях</span></div><div id="ch-frt"></div></section>
        <section class="card"><div class="card-head"><h2>Типи звернень</h2><span class="muted">кількість · частка вирішених</span></div><div id="ch-types"></div></section>
        <section class="card"><div class="card-head"><h2>Канали зв'язку</h2><span class="muted">частка звернень · медіана відповіді</span></div><div id="ch-ch"></div>
          <h3 class="sub">Пріоритети</h3><div id="ch-pr"></div></section>
      </div>

      <section class="card">
        <div class="card-head"><h2>Головні рекомендації</h2><a href="#recs" class="link">Усі ${recs.length} →</a></div>
        <div class="recs recs-compact">${recs.slice(0, 4).map(recCard).join('')}</div>
      </section>`;

    const days = A.daily(Store.db, r);
    Charts.line($('#ch-daily'), days.map((x, i) => ({ y: x.n, label: dm(x.t), tip: i === days.length - 1 ? 'Сьогодні (неповна доба)' : dmy(x.t) })), { name: 'Звернень', aria: 'Звернення по днях' });
    Charts.line($('#ch-frt'), days.map(x => ({ y: x.frt, label: dm(x.t) })), { name: 'Медіана', color: 'var(--s2)', fmt: v => Math.round(v) + ' с', target: S.targetFrtSec, targetLabel: 'ціль ' + S.targetFrtSec + ' с', aria: 'Медіана часу першої відповіді' });
    const types = A.groupBy(k.R, 'type', D.types).sort((a, b) => b.n - a.n);
    Charts.bars($('#ch-types'), types.map(t => ({ label: t.label, value: t.n, text: `${num(t.n)} · ${pct(t.resolve)}`, tip: `<b>${t.label}</b><span>${num(t.n)} звернень (${pct(t.n / (k.count || 1))})</span><span>вирішено ${pct(t.resolve)} · відповідь ${sec(t.frt)}</span>` })));
    const chans = A.groupBy(k.R, 'ch', D.channels);
    Charts.stack($('#ch-ch'), chans.map((c, i) => ({ label: c.label, value: c.n, color: COLORS[i], extra: sec(c.frt) })), { fmt: v => num(v) + ' звернень' });
    const prs = A.groupBy(k.R, 'pr', D.priorities);
    Charts.stack($('#ch-pr'), prs.map((c, i) => ({ label: c.label, value: c.n, color: ['var(--crit)', 'var(--warn)', 'var(--s1)'][i], extra: sec(c.frt) })), { fmt: v => num(v) + ' звернень' });
    bindPeriod();
  }

  function recCard(x) {
    return `<article class="rec rec-${x.lvl}"><div class="rec-top"><span class="pill pill-${x.lvl}">${LVL[x.lvl]}</span><span class="rec-area">${x.area}</span></div><h3>${esc(x.title)}</h3><p class="rec-why">${esc(x.why)}</p><p class="rec-act"><b>Дія:</b> ${esc(x.act)}</p></article>`;
  }

  function viewTeam(main) {
    const r = rg(), now = Date.now(), S = Store.settings();
    const T = A.team(Store.db, r, now).filter(t => t.u.active || t.k.count);
    const sorters = {
      name: t => t.u.name, count: t => t.k.count, perHour: t => t.k.perHour, frt: t => t.k.frtMed, res: t => t.k.resolve,
      rating: t => t.k.rating, fat: t => t.fatigue || 0, score: t => t.score || 0, hours: t => t.k.hours
    };
    const { k: sk, dir } = state.teamSort;
    T.sort((a, b) => { const x = sorters[sk](a), y = sorters[sk](b); return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    const th = (key, label, cls) => `<th class="${cls || ''}"><button type="button" data-sort="${key}" class="${sk === key ? 'on' : ''}">${label}${sk === key ? (dir > 0 ? ' ↑' : ' ↓') : ''}</button></th>`;
    const daysOf = uid => A.daily({ requests: Store.all('requests').filter(q => q.uid === uid) }, A.range(14, now)).map(d => d.n);
    const all = A.kpi(Store.all('requests'), Store.all('shifts'), r.start, r.end, now);
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">${T.filter(t => t.u.active).length} активних консультантів</div><h1>Команда</h1></div>${periodPicker()}</div>
      <section class="card table-card">
        <div class="table-scroll"><table class="tbl">
          <thead><tr>${th('name', 'Консультант', 'l')}${th('score', 'Показник')}${th('count', 'Звернень')}${th('hours', 'Годин')}${th('perHour', 'На год')}${th('frt', 'Відповідь, мед.')}${th('res', 'Вирішено')}${th('rating', 'Оцінка')}${th('fat', 'Самопочуття')}<th>14 днів</th></tr></thead>
          <tbody>${T.map(t => {
            const k = t.k;
            const slow = k.frtMed > S.targetFrtSec * 1.4;
            return `<tr data-member="${t.u.id}" tabindex="0">
              <td class="l"><span class="who"><span class="avatar">${initials(t.u.name)}</span><span><b>${esc(t.u.name)}</b><small class="muted">${t.onDuty ? '<span class="live-dot sm"></span>на зміні' : (t.u.active ? `${k.shifts} змін · нічних ${t.nights}` : 'звільнений')}</small></span></span></td>
              <td><span class="score-bar"><i style="width:${t.score || 0}%" class="${t.score >= 75 ? 'good' : t.score >= 60 ? '' : 'bad'}"></i></span><b>${t.score != null ? t.score : '—'}</b> ${t.scorePrev != null ? delta(t.score, t.scorePrev, 'up', v => v) : ''}</td>
              <td>${num(k.count)}</td><td>${num(k.hours)}</td><td>${num(k.perHour, 2)}</td>
              <td class="${slow ? 'bad' : ''}">${k.count ? sec(k.frtMed) : '—'}</td>
              <td class="${k.resolve < S.targetResolve - 0.1 ? 'bad' : ''}">${k.count ? pct(k.resolve) : '—'}</td>
              <td>${k.ratingN ? num(k.rating, 1) + ' ★' : '—'}</td>
              <td>${t.fatigue != null ? `<span class="pill pill-${t.fatigue <= 2.3 ? 'crit' : t.fatigue <= 3 ? 'warn' : 'good'}">${num(t.fatigue, 1)} / 5</span>` : '—'}</td>
              <td>${Charts.spark(daysOf(t.u.id))}</td></tr>`;
          }).join('')}</tbody>
          <tfoot><tr><td class="l"><b>Відділ</b></td><td></td><td>${num(all.count)}</td><td>${num(all.hours)}</td><td>${num(all.perHour, 2)}</td><td>${sec(all.frtMed)}</td><td>${pct(all.resolve)}</td><td>${all.ratingN ? num(all.rating, 1) + ' ★' : '—'}</td><td></td><td></td></tr></tfoot>
        </table></div>
        <p class="hint">Натисніть на рядок, щоб відкрити картку консультанта. Самопочуття — середня самооцінка після змін (1 — виснажений, 5 — бадьорий).</p>
      </section>`;
    $$('[data-sort]').forEach(b => b.onclick = () => { const key = b.dataset.sort; state.teamSort = { k: key, dir: state.teamSort.k === key ? -state.teamSort.dir : (key === 'name' || key === 'frt' ? 1 : -1) }; rerender(); });
    $$('[data-member]').forEach(tr => { const open = () => memberModal(tr.dataset.member); tr.onclick = open; tr.onkeydown = e => { if (e.key === 'Enter') open(); }; });
    bindPeriod();
  }

  function modal(html) {
    let m = $('#modal');
    if (!m) { m = document.createElement('div'); m.id = 'modal'; m.className = 'modal'; document.body.appendChild(m); }
    m.innerHTML = `<div class="drawer-scrim" data-close></div><div class="modal-panel" role="dialog" aria-modal="true">${html}</div>`;
    m.hidden = false; document.body.classList.add('no-scroll');
    const close = () => { m.hidden = true; document.body.classList.remove('no-scroll'); };
    $$('[data-close]', m).forEach(b => b.onclick = close);
    m.onkeydown = e => { if (e.key === 'Escape') close(); };
    const f = $('button, input', m); if (f) f.focus();
    return m;
  }

  function memberModal(uid) {
    const r = rg(), now = Date.now();
    const t = A.team(Store.db, r, now).find(x => x.u.id === uid);
    const k = t.k;
    const types = A.groupBy(k.R, 'type', D.types).filter(x => x.n).sort((a, b) => b.n - a.n);
    const notes = k.R.slice().sort((a, b) => b.ts - a.ts).slice(0, 6);
    const shifts = k.S.slice().sort((a, b) => b.start - a.start).slice(0, 6);
    modal(`
      <div class="drawer-head"><div><div class="eyebrow">Картка консультанта · ${state.period} днів</div><h2>${esc(t.u.name)}</h2><span class="muted">У відділі з ${dmy(t.u.hiredAt)} · ставка ${money(t.u.rate)}/год</span></div><button class="icon-btn" data-close type="button" aria-label="Закрити">✕</button></div>
      <div class="tiles tiles-sm">
        ${tile('Показник', t.score != null ? t.score : '—', t.scorePrev != null ? delta(t.score, t.scorePrev, 'up', v => v + ' б.') : '')}
        ${tile('Звернень', num(k.count), num(k.perHour, 2) + ' на год')}
        ${tile('Відповідь', k.count ? sec(k.frtMed) : '—', 'p90 ' + sec(k.frtP90))}
        ${tile('Вирішено', k.count ? pct(k.resolve) : '—', 'ескалацій ' + pct(k.escalate))}
        ${tile('Нарахування', money(t.pay), num(k.hours) + ' год')}
        ${tile('Вартість звернення', k.count ? money(t.costPerReq) : '—', '')}
      </div>
      <h3 class="sub">Типи звернень</h3><div id="m-types"></div>
      <div class="grid-2 tight">
        <div><h3 class="sub">Останні зміни</h3><ul class="notes">${shifts.map(s => `<li><b>${dmy(s.start)}</b> ${hm(s.start)}–${s.end ? hm(s.end) : 'зараз'} ${s.fatigue ? `<span class="pill pill-${s.fatigue <= 2 ? 'crit' : s.fatigue <= 3 ? 'warn' : 'good'}">самопочуття ${s.fatigue}</span>` : ''}${s.handover ? `<p>${esc(s.handover)}</p>` : ''}</li>`).join('')}</ul></div>
        <div><h3 class="sub">Останні висновки</h3><ul class="notes">${notes.map(q => `<li><b>${D.label('types', q.type)}</b> <span class="muted">${dm(q.ts)} · ${esc(q.prod)}</span><p>${esc(q.note)}</p></li>`).join('')}</ul></div>
      </div>`);
    Charts.bars($('#m-types'), types.map(x => ({ label: x.label, value: x.n, text: `${x.n} · ${pct(x.resolve)}` })));
  }

  function viewLoad(main) {
    const r = rg(), now = Date.now(), S = Store.settings();
    const L = A.load(Store.db, r, now);
    const U = users('consultant');
    const active = U.filter(u => u.active);
    const newbies = active.filter(u => now - new Date(u.hiredAt) < 60 * A.DAY);
    const left = U.filter(u => !u.active);
    const tenure = A.avg(active.map(u => (now - new Date(u.hiredAt)) / A.DAY / 30.4));
    const gapHours = L.hours.filter(x => x.have + 0.25 < x.need);
    const T = A.team(Store.db, r, now).filter(t => t.u.active);
    const tired = T.filter(t => t.fatigue != null && t.fatigue <= 2.3);
    const recs = A.recommendations(Store.db, r, now).filter(x => ['Графік', 'Штат', 'Люди', 'Команда'].includes(x.area));
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Прогноз за моделлю Ерланга C</div><h1>Навантаження і штат</h1></div>${periodPicker()}</div>
      <div class="tiles">
        ${tile('Активних консультантів', num(active.length), `${newbies.length} нових за 60 днів · ${left.length} звільнено`)}
        ${tile('Потрібно ставок', num(L.fteNeed, 1), statusPill(L.fteNeed <= active.length + 0.5, 'штату достатньо', `не вистачає ${num(Math.max(0, L.fteNeed - active.length), 1)}`))}
        ${tile('Годин на людину', num(L.hoursPerHead), `на місяць · норма ${S.fteHoursMonth}`, { cls: L.hoursPerHead > S.fteHoursMonth * 1.1 ? 'tile-warn' : '' })}
        ${tile('Годин з недопокриттям', num(gapHours.length), gapHours.length ? A.spans(gapHours.map(x => x.h)).join(', ') : 'покриття відповідає попиту')}
        ${tile('Середній стаж', num(tenure, 1) + ' міс', '')}
        ${tile('Ризик вигорання', num(tired.length), tired.map(t => esc(t.u.name.split(' ')[0])).join(', ') || 'немає')}
      </div>
      <section class="card">
        <div class="card-head"><h2>Потрібно і є консультантів по годинах доби</h2><span class="muted">середнє за ${state.period} днів</span></div>
        <div id="ch-need"></div>
        <ul class="legend"><li><i style="background:var(--s1)"></i>є на зміні</li><li><i style="background:var(--crit)"></i>менше, ніж потрібно</li><li><i class="line-key"></i>потрібно для ${pct(S.slaShare)} відповідей за ${S.slaSec} с</li></ul>
      </section>
      <section class="card">
        <div class="card-head"><h2>Коли пишуть з фронту</h2><span class="muted">звернень на годину, середнє</span></div>
        <div id="ch-heat"></div>
      </section>
      <section class="card"><h2>Рекомендації по графіку та штату</h2><div class="recs">${recs.map(recCard).join('') || '<p class="empty">Зауважень немає.</p>'}</div></section>
      <section class="card method"><h3>Як рахується потреба</h3><p class="muted">Для кожної години доби беремо середню кількість звернень і середню тривалість обробки. Модель Ерланга C показує, скільки консультантів потрібно, щоб ${pct(S.slaShare)} звернень отримали першу відповідь за ${S.slaSec} секунд; мінімум — двоє (регламент 3.2). Сума людино-годин на добу × 30,4 дня ділиться на ${S.fteHoursMonth} год на ставку з урахуванням ${pct(S.shrinkage)} на перерви, навчання і хвороби. Параметри змінюються в «Налаштуваннях».</p></section>`;
    Charts.needHave($('#ch-need'), L.hours);
    Charts.heat($('#ch-heat'), L.heat);
    bindPeriod();
  }

  function viewFinance(main) {
    const r = rg(), now = Date.now(), S = Store.settings();
    const F = A.finance(Store.db, r, now);
    const M = A.monthly(Store.db, now);
    const months = ['січ', 'лют', 'бер', 'кві', 'тра', 'чер', 'лип', 'сер', 'вер', 'жов', 'лис', 'гру'];
    const mName = m => months[+m.slice(5) - 1] + ' ' + m.slice(0, 4);
    const curM = new Date().toISOString().slice(0, 7);
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Фінансова ефективність</div><h1>Фінанси</h1></div>${periodPicker()}</div>
      <div class="tiles tiles-hero">
        ${tile('Витрати відділу', money(F.total), `за ${state.period} днів · ${money(F.total / F.months)} на місяць`)}
        ${tile('Вартість звернення', money(F.costPerReq), `вирішеного — ${money(F.costPerResolved)}`)}
        ${tile('Година цілодобового покриття', money(F.costPerHourCoverage), 'усі витрати / години доби')}
        ${tile('Повернуто в стрій', num(F.back), `× ${money(S.avgUnitCost)} середня вартість виробу`)}
        ${tile('Умовний економічний ефект', money(F.effect), 'вартість техніки, що знову працює')}
        ${tile('Окупність', '×' + num(F.roi, 1), 'ефект / витрати', { cls: 'tile-good' })}
      </div>
      <div class="grid-2">
        <section class="card"><div class="card-head"><h2>Структура витрат</h2><span class="muted">${state.period} днів</span></div><div id="ch-cost"></div></section>
        <section class="card"><div class="card-head"><h2>Розподіл премій</h2><span class="muted">фонд ${S.bonusPoolPct}% від ФОП · ${money(F.bonus)}</span></div>
          <div class="table-scroll"><table class="tbl tbl-sm"><thead><tr><th class="l">Консультант</th><th>Показник</th><th>Нараховано</th><th>Премія</th></tr></thead>
          <tbody>${F.bonuses.filter(b => b.t.k.count).sort((a, b) => b.bonus - a.bonus).map(b => `<tr><td class="l">${esc(b.t.u.name)}</td><td>${b.t.score}</td><td>${money(b.t.pay)}</td><td>${b.bonus ? '<b>' + money(b.bonus) + '</b>' : '<span class="muted">нижче 60</span>'}</td></tr>`).join('')}</tbody></table></div></section>
      </div>
      <section class="card table-card">
        <div class="card-head"><h2>Фінансовий звіт по місяцях</h2>${inFrame ? '' : '<button class="btn btn-ghost" id="fin-csv" type="button">Експорт CSV</button>'}</div>
        <div class="table-scroll"><table class="tbl">
          <thead><tr><th class="l">Місяць</th><th>Годин</th><th>ФОП</th><th>Премії</th><th>ЄСВ ${S.taxPct}%</th><th>Накладні</th><th>Разом</th><th>Звернень</th><th>Вартість звернення</th><th>Повернуто</th><th>Ефект</th></tr></thead>
          <tbody>${M.map(m => `<tr><td class="l"><b>${mName(m.m)}</b>${m.m === curM ? ' <small class="muted">поточний</small>' : ''}</td><td>${num(m.hours)}</td><td>${money(m.payroll)}</td><td>${money(m.bonus)}</td><td>${money(m.tax)}</td><td>${money(m.overhead)}</td><td><b>${money(m.total)}</b></td><td>${num(m.req)}</td><td>${money(m.cpr)}</td><td>${num(m.back)}</td><td>${money(m.effect)}</td></tr>`).join('')}</tbody>
        </table></div>
        <p class="hint">Накладні витрати (зв'язок, робочі пристрої, ПЗ, приміщення) — ${money(S.overheadMonth)} на місяць, нараховуються повністю і для неповних місяців. Ставки консультантів — у розділі «Персонал», параметри — у «Налаштуваннях».</p>
      </section>
      <section class="card method"><h3>Методика економічного ефекту</h3><p class="muted">Ефект рахується лише за зверненнями з позначкою «Техніку повернуто в стрій» (регламент 6.3): виріб не працював, а після допомоги консультанта виконує завдання. Кожне таке звернення множиться на середню вартість виробу (${money(S.avgUnitCost)}). Це консервативна оцінка: вона не враховує вартість виконаних бойових завдань і збережений час логістики ремонту.</p></section>`;
    Charts.bars($('#ch-cost'), [
      { label: 'ФОП', value: F.payroll, color: 'var(--s1)' },
      { label: 'Премії', value: F.bonus, color: 'var(--s3)' },
      { label: 'ЄСВ', value: F.tax, color: 'var(--s7)' },
      { label: 'Накладні', value: F.overhead, color: 'var(--s2)' }
    ].map(x => Object.assign(x, { text: money(x.value) + ' · ' + pct(x.value / F.total) })));
    const csv = $('#fin-csv');
    if (csv) csv.onclick = () => {
      const rows = [['Місяць', 'Годин', 'ФОП', 'Премії', 'ЄСВ', 'Накладні', 'Разом', 'Звернень', 'Вартість звернення', 'Повернуто в стрій', 'Ефект']].concat(M.map(m => [m.m, m.hours.toFixed(1), m.payroll.toFixed(0), m.bonus.toFixed(0), m.tax.toFixed(0), m.overhead, m.total.toFixed(0), m.req, m.cpr.toFixed(0), m.back, m.effect]));
      download('finansovyi-zvit.csv', '﻿' + rows.map(r => r.join(';')).join('\n'), 'text/csv');
    };
    bindPeriod();
  }

  function viewRecs(main) {
    const recs = A.recommendations(Store.db, rg(), Date.now());
    const cnt = l => recs.filter(x => x.lvl === l).length;
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Автоматичний аналіз даних усіх консультантів</div><h1>Рекомендації</h1></div>${periodPicker()}</div>
      <p class="summary-line"><span class="pill pill-crit">${cnt('crit')} критичних</span><span class="pill pill-warn">${cnt('warn')} уваги</span><span class="pill pill-info">${cnt('info')} до відома</span><span class="pill pill-good">${cnt('good')} позитивних</span></p>
      <div class="recs">${recs.map(recCard).join('') || '<p class="empty">За обраний період зауважень немає.</p>'}</div>
      <section class="card method"><h3>Звідки беруться рекомендації</h3><p class="muted">Система перевіряє дані за 10 правилами: покриття годин, достатність штату, частку типових звернень, повторювані дефекти виробів (регламент 9.3), ескалації по виробах, швидкість окремих консультантів, кандидатів у наставники, самопочуття, швидкість каналів і виконання стандарту 30 секунд для критичних звернень. Кожна рекомендація містить цифри, на яких вона ґрунтується, і конкретну дію.</p></section>`;
    bindPeriod();
  }

  function viewProposals(main) {
    const st = { new: 'Нова', review: 'На розгляді', accepted: 'Прийнята', rejected: 'Відхилена' };
    const P = Store.all('proposals').slice().sort((a, b) => b.ts - a.ts);
    const f = state.propFilter;
    const list = P.filter(p => f === 'all' || (f === 'open' ? (p.status === 'new' || p.status === 'review') : p.status === f));
    const findText = id => { const it = reglamentItems().find(x => x.id === id); return it ? it.text : null; };
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Регламент 13.2 · розгляд протягом 7 днів</div><h1>Пропозиції змін до регламенту</h1></div>
        <div class="seg" role="group">${[['open', 'Відкриті'], ['accepted', 'Прийняті'], ['rejected', 'Відхилені'], ['all', 'Усі']].map(([k, l]) => `<button type="button" data-pf="${k}" class="${f === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
      <div class="props">${list.map(p => {
        const cur = findText(p.section);
        const overdue = (p.status === 'new') && Date.now() - p.ts > 7 * A.DAY;
        return `<article class="card prop">
          <div class="prop-top"><span class="pill pill-${p.status}">${st[p.status]}</span>${overdue ? '<span class="pill pill-crit">! понад 7 днів</span>' : ''}<b>${p.section === 'new' ? 'Новий пункт' : 'Пункт ' + esc(p.section)}</b><span class="muted">${esc(userName(p.uid))} · ${dmy(p.ts)}</span></div>
          ${cur ? `<blockquote>${esc(cur)}</blockquote>` : ''}
          <p class="prop-text">${esc(p.text)}</p>
          ${p.reason ? `<p class="muted"><b>Обґрунтування:</b> ${esc(p.reason)}</p>` : ''}
          <div class="prop-act">
            <input type="text" id="pc-${p.id}" placeholder="Коментар автору" value="${esc(p.comment)}" aria-label="Коментар">
            <button class="btn btn-good" type="button" data-ps="accepted" data-id="${p.id}">Прийняти</button>
            <button class="btn btn-ghost" type="button" data-ps="review" data-id="${p.id}">На розгляд</button>
            <button class="btn btn-ghost danger" type="button" data-ps="rejected" data-id="${p.id}">Відхилити</button>
          </div></article>`;
      }).join('') || '<p class="empty">Пропозицій у цьому статусі немає. Нові пропозиції надходять з форми внизу кожної сторінки.</p>'}</div>`;
    $$('[data-pf]').forEach(b => b.onclick = () => { state.propFilter = b.dataset.pf; rerender(); });
    $$('[data-ps]').forEach(b => b.onclick = () => {
      const p = Store.byId('proposals', b.dataset.id);
      p.status = b.dataset.ps; p.comment = $('#pc-' + p.id).value.trim(); p.decidedAt = Date.now();
      Store.put('proposals', p); toast('Статус: ' + st[p.status].toLowerCase()); rerender();
    });
  }

  function reportData() {
    const r = rg(), now = Date.now(), S = Store.settings();
    const k = A.kpi(Store.all('requests'), Store.all('shifts'), r.start, r.end, now);
    const kp = A.kpi(Store.all('requests'), Store.all('shifts'), r.prevStart, r.prevEnd, now);
    const F = A.finance(Store.db, r, now), L = A.load(Store.db, r, now);
    const recs = A.recommendations(Store.db, r, now);
    const T = A.team(Store.db, r, now).filter(t => t.u.active && t.score != null).sort((a, b) => b.score - a.score);
    const P = Store.all('proposals');
    return { r, k, kp, F, L, recs, T, P, S };
  }

  function viewReport(main) {
    const { r, k, kp, F, L, recs, T, P, S } = reportData();
    const ch = (a, b) => b ? (a >= b ? '+' : '−') + Math.abs(Math.round((a / b - 1) * 100)) + '%' : '';
    const text = reportText();
    main.innerHTML = `
      <div class="page-head no-print"><div><div class="eyebrow">Готово для погодження</div><h1>Звіт керівництву</h1></div>
        <div class="row-end">${periodPicker()}<button class="btn btn-ghost" id="rep-copy" type="button">Копіювати текст</button>${inFrame ? '' : '<button class="btn btn-primary" id="rep-print" type="button">Друк / PDF</button>'}</div></div>
      <article class="report card">
        <header class="rep-head">
          <div><div class="eyebrow">${esc(DSS_CONFIG.company)} · ${esc(DSS_CONFIG.department)}</div>
          <h1>Звіт про ефективність відділу підтримки</h1>
          <p class="muted">Період: ${dmy(r.start)} — ${dmy(r.end)} (${state.period} днів). Сформовано ${dmy(Date.now())} системою обліку ефективності.</p></div>
          <div class="mark big">${logoSvg()}</div>
        </header>
        <section><h2>1. Головне</h2>
          <div class="tiles tiles-report">
            ${tile('Звернень з фронту', num(k.count), ch(k.count, kp.count) + ' до попереднього періоду')}
            ${tile('Медіана першої відповіді', sec(k.frtMed), 'ціль ' + S.targetFrtSec + ' с')}
            ${tile('Вирішено на першій лінії', pct(k.resolve), 'ціль ' + pct(S.targetResolve))}
            ${tile('Техніки повернуто в стрій', num(k.back), '≈ ' + money(F.effect))}
            ${tile('Витрати відділу', money(F.total), money(F.costPerReq) + ' за звернення')}
            ${tile('Окупність', '×' + num(F.roi, 1), 'умовний ефект / витрати')}
          </div>
        </section>
        <section><h2>2. Висновки</h2><ul class="rep-list">
          <li>Відділ працює цілодобово з ${L.active} консультантами; за період оброблено ${num(k.count)} звернень (${num(k.count / state.period)} на добу), з них ${num(k.crit)} критичних.</li>
          <li>Стандарт першої відповіді для критичних звернень (30 с) виконано у ${pct(k.critSla)} випадків${k.critSla < 0.9 ? ' — нижче цільових 90%' : ''}.</li>
          <li>Для виконання стандарту в пікові години (світанок і вечір) потрібно ${num(L.fteNeed, 1)} ставки; зараз консультанти працюють у середньому ${num(L.hoursPerHead)} год на місяць при нормі ${S.fteHoursMonth}.</li>
          <li>Кожна гривня витрат відділу повертає ≈ ${num(F.roi, 1)} грн у вигляді техніки, яка знову виконує завдання.</li>
        </ul></section>
        <section><h2>3. Що пропонується зробити</h2><ol class="rep-list">${recs.filter(x => x.lvl !== 'good').slice(0, 6).map(x => `<li><b>${esc(x.title)}.</b> ${esc(x.act)}</li>`).join('')}</ol></section>
        <section><h2>4. Команда</h2><p>Найвищі показники: ${T.slice(0, 3).map(t => `${esc(t.u.name)} (${t.score})`).join(', ')}. Потребують підтримки: ${T.slice(-2).map(t => `${esc(t.u.name)} (${t.score})`).join(', ')}. Преміальний фонд — ${money(F.bonus)} (${S.bonusPoolPct}% ФОП), розподіляється пропорційно показнику.</p></section>
        <section><h2>5. Регламент</h2><p>Діє генеральний регламент, редакція ${REGLAMENT.version} (${REGLAMENT.sections.length} розділів, ${reglamentItems().length} пунктів), доступний з кожної сторінки системи. Від працівників надійшло ${P.length} пропозицій змін: прийнято ${P.filter(p => p.status === 'accepted').length}, на розгляді ${P.filter(p => p.status === 'new' || p.status === 'review').length}.</p></section>
        <section><h2>6. Що потрібно погодити</h2><ol class="rep-list">
          <li>Затвердити систему обліку як основне джерело даних про роботу відділу (регламент 1.5).</li>
          <li>Затвердити генеральний регламент у редакції ${REGLAMENT.version}.</li>
          <li>Затвердити преміальну модель за інтегральним показником (регламент 11.1–11.2).</li>
          ${L.fteNeed > L.active + 0.5 ? `<li>Погодити розширення штату на ${Math.ceil(L.fteNeed - L.active)} консультанта(ів).</li>` : ''}
        </ol></section>
      </article>
      <textarea class="sr-only" id="rep-text" aria-hidden="true" tabindex="-1">${esc(text)}</textarea>`;
    $('#rep-copy').onclick = () => copyText(text);
    const pr = $('#rep-print'); if (pr) pr.onclick = () => window.print();
    bindPeriod();
  }
  function reportText() {
    const { r, k, F, L, recs, S } = reportData();
    return [
      `Звіт про ефективність: ${DSS_CONFIG.department}`,
      `Період: ${dmy(r.start)} — ${dmy(r.end)}`,
      '',
      `Звернень: ${num(k.count)} (${num(k.count / state.period)} на добу), критичних: ${num(k.crit)}`,
      `Медіана першої відповіді: ${sec(k.frtMed)} (ціль ${S.targetFrtSec} с); критичні за 30 с: ${pct(k.critSla)}`,
      `Вирішено на першій лінії: ${pct(k.resolve)}; ескальовано: ${pct(k.escalate)}`,
      `Техніки повернуто в стрій: ${num(k.back)} (≈ ${money(F.effect)})`,
      `Витрати: ${money(F.total)}; вартість звернення: ${money(F.costPerReq)}; окупність ×${num(F.roi, 1)}`,
      `Штат: ${L.active} активних; потрібно ${num(L.fteNeed, 1)} ставки`,
      '',
      'Рекомендації:',
      ...recs.filter(x => x.lvl !== 'good').slice(0, 6).map((x, i) => `${i + 1}. ${x.title}. ${x.act}`)
    ].join('\n');
  }

  function viewStaff(main) {
    const U = users().slice().sort((a, b) => (b.active - a.active) || (a.role === 'head' ? -1 : 1) - (b.role === 'head' ? -1 : 1) || a.name.localeCompare(b.name));
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Облікові записи та ставки</div><h1>Персонал</h1></div></div>
      <div class="grid-2 staff-grid">
        <section class="card table-card"><div class="table-scroll"><table class="tbl">
          <thead><tr><th class="l">Працівник</th><th>Роль</th><th>Ставка, ${Store.settings().currency}/год</th><th>З</th><th>Статус</th><th></th></tr></thead>
          <tbody>${U.map(u => `<tr>
            <td class="l"><span class="who"><span class="avatar">${initials(u.name)}</span><b>${esc(u.name)}</b></span></td>
            <td>${u.role === 'head' ? 'Керівник' : 'Консультант'}</td>
            <td>${u.role === 'head' ? '—' : `<input class="rate-in" type="number" min="0" step="10" value="${u.rate}" data-rate="${u.id}" aria-label="Ставка">`}</td>
            <td>${dmy(u.hiredAt)}</td>
            <td>${u.active ? '<span class="pill pill-good">активний</span>' : `<span class="pill pill-info">звільнений${u.leftAt ? ' ' + dmy(u.leftAt) : ''}</span>`}</td>
            <td class="nowrap">${u.id === state.user.id ? '' : `<button class="link" type="button" data-pin="${u.id}">Новий PIN</button> <button class="link ${u.active ? 'danger' : ''}" type="button" data-toggle="${u.id}">${u.active ? 'Закрити доступ' : 'Відновити'}</button>`}</td>
          </tr>`).join('')}</tbody></table></div>
          <p class="hint">Закриття доступу в день звільнення — вимога регламенту 8.5. Дані звільненого працівника залишаються у звітах.</p>
        </section>
        <form class="card" id="add-user">
          <h2>Додати працівника</h2>
          <label class="field"><span>Ім'я та прізвище</span><input id="nu-name" required placeholder="Напр. Ольга Петренко"></label>
          <div class="field-row">
            <label class="field"><span>Роль</span><select id="nu-role"><option value="consultant">Консультант</option><option value="head">Керівник</option></select></label>
            <label class="field"><span>Ставка, ${Store.settings().currency}/год</span><input id="nu-rate" type="number" min="0" step="10" value="200"></label>
          </div>
          <div class="field-row">
            <label class="field"><span>PIN (4–8 цифр)</span><input id="nu-pin" inputmode="numeric" pattern="[0-9]{4,8}" required></label>
            <label class="field"><span>Дата прийому</span><input id="nu-date" type="date" value="${new Date().toISOString().slice(0, 10)}"></label>
          </div>
          <button class="btn btn-primary btn-block" type="submit">Додати</button>
        </form>
      </div>`;
    $$('[data-rate]').forEach(i => i.onchange = () => { const u = Store.byId('users', i.dataset.rate); u.rate = +i.value || 0; Store.put('users', u); toast('Ставку збережено: ' + u.name); });
    $$('[data-toggle]').forEach(b => b.onclick = () => {
      const u = Store.byId('users', b.dataset.toggle);
      u.active = !u.active; u.leftAt = u.active ? undefined : new Date().toISOString().slice(0, 10);
      const sh = openShift(u.id); if (!u.active && sh) { sh.end = Date.now(); Store.put('shifts', sh); }
      Store.put('users', u); toast(u.active ? 'Доступ відновлено' : 'Доступ закрито'); rerender();
    });
    $$('[data-pin]').forEach(b => b.onclick = () => {
      const u = Store.byId('users', b.dataset.pin);
      u.pin = String(Math.floor(1000 + Math.random() * 9000)); Store.put('users', u);
      b.outerHTML = `<span class="pin-show">PIN: <b>${u.pin}</b> — передайте особисто</span>`;
    });
    $('#add-user').onsubmit = e => {
      e.preventDefault();
      const pin = $('#nu-pin').value.trim();
      if (!/^\d{4,8}$/.test(pin)) { toast('PIN має містити від 4 до 8 цифр', 'crit'); return; }
      Store.put('users', { name: $('#nu-name').value.trim(), role: $('#nu-role').value, rate: +$('#nu-rate').value || 0, pin, active: true, hiredAt: $('#nu-date').value });
      toast('Працівника додано', 'good'); rerender();
    };
  }

  function viewSettings(main) {
    const S = Store.settings();
    const f = (id, label, val, hint, attrs) => `<label class="field"><span>${label}${hint ? ` <small class="muted">${hint}</small>` : ''}</span><input id="st-${id}" type="number" value="${val}" ${attrs || ''}></label>`;
    main.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Цілі, фінансові параметри, дані</div><h1>Налаштування</h1></div></div>
      <form class="grid-2" id="settings-form">
        <section class="card"><h2>Цільові показники</h2>
          ${f('targetFrtSec', 'Медіана першої відповіді, с', S.targetFrtSec, 'регламент 5.6', 'min="5" max="600"')}
          ${f('targetResolve', 'Частка вирішених, %', Math.round(S.targetResolve * 100), '', 'min="0" max="100"')}
          ${f('targetEscalate', 'Максимум ескалацій, %', Math.round(S.targetEscalate * 100), '', 'min="0" max="100"')}
          <div class="field-row">${f('slaSec', 'Відповідь за, с', S.slaSec, 'для розрахунку штату', 'min="5"')}${f('slaShare', 'Частка звернень, %', Math.round(S.slaShare * 100), '', 'min="50" max="99"')}</div>
        </section>
        <section class="card"><h2>Штат і фінанси</h2>
          <div class="field-row">${f('fteHoursMonth', 'Годин на ставку на місяць', S.fteHoursMonth, '', 'min="40"')}${f('shrinkage', 'Втрати часу, %', Math.round(S.shrinkage * 100), 'перерви, навчання', 'min="0" max="60"')}</div>
          <div class="field-row">${f('overheadMonth', 'Накладні витрати на місяць', S.overheadMonth, S.currency, 'min="0" step="1000"')}${f('taxPct', 'ЄСВ, %', S.taxPct, '', 'min="0" max="50"')}</div>
          <div class="field-row">${f('bonusPoolPct', 'Преміальний фонд, % ФОП', S.bonusPoolPct, '', 'min="0" max="100"')}${f('avgUnitCost', 'Середня вартість виробу', S.avgUnitCost, S.currency, 'min="0" step="1000"')}</div>
          <button class="btn btn-primary" type="submit">Зберегти налаштування</button>
        </section>
      </form>
      <section class="card"><h2>Дані</h2>
        <p class="muted">${Store.db.demo ? 'Зараз у системі демонстраційні дані: 8 тижнів роботи вигаданого відділу з 12 консультантів. Перед реальним запуском почніть з чистої бази.' : 'Система працює з реальними даними.'} Збережено: ${num(Store.all('requests').length)} звернень, ${num(Store.all('shifts').length)} змін, ${Store.all('users').length} працівників.</p>
        <div class="row-wrap">
          ${inFrame ? '' : '<button class="btn btn-ghost" type="button" id="exp-json">Резервна копія (JSON)</button><button class="btn btn-ghost" type="button" id="exp-csv">Звернення (CSV)</button>'}
          <label class="btn btn-ghost file-btn">Відновити з копії<input type="file" id="imp-json" accept="application/json,.json"></label>
          <button class="btn btn-ghost" type="button" id="reset-demo">Повернути демо-дані</button>
          <button class="btn btn-ghost danger" type="button" id="reset-empty">Почати з чистої бази</button>
        </div>
        <div id="confirm-zone"></div>
      </section>`;
    $('#settings-form').onsubmit = e => {
      e.preventDefault();
      const v = id => +$('#st-' + id).value;
      Store.setSettings({
        targetFrtSec: v('targetFrtSec'), targetResolve: v('targetResolve') / 100, targetEscalate: v('targetEscalate') / 100,
        slaSec: v('slaSec'), slaShare: v('slaShare') / 100, fteHoursMonth: v('fteHoursMonth'), shrinkage: v('shrinkage') / 100,
        overheadMonth: v('overheadMonth'), taxPct: v('taxPct'), bonusPoolPct: v('bonusPoolPct'), avgUnitCost: v('avgUnitCost')
      });
      toast('Налаштування збережено', 'good');
    };
    const ej = $('#exp-json'); if (ej) ej.onclick = () => download('dss-backup-' + new Date().toISOString().slice(0, 10) + '.json', JSON.stringify(Store.db), 'application/json');
    const ec = $('#exp-csv'); if (ec) ec.onclick = () => {
      const rows = [['Дата', 'Час', 'Консультант', 'Канал', 'Тип', 'Пріоритет', 'Виріб', 'Перша відповідь, с', 'Обробка, хв', 'Результат', 'В строю', 'Оцінка', 'Висновок']]
        .concat(Store.all('requests').slice().sort((a, b) => a.ts - b.ts).map(q => [dmy(q.ts), hm(q.ts), userName(q.uid), D.label('channels', q.ch), D.label('types', q.type), D.label('priorities', q.pr), q.prod, q.frt, q.dur, D.label('outcomes', q.out), q.back ? 'так' : '', q.rate || '', '"' + (q.note || '').replace(/"/g, '""') + '"']));
      download('zvernennia.csv', '﻿' + rows.map(r => r.join(';')).join('\n'), 'text/csv');
    };
    $('#imp-json').onchange = e => {
      const file = e.target.files[0]; if (!file) return;
      const rd = new FileReader();
      rd.onload = () => {
        try {
          const d = JSON.parse(rd.result);
          if (!Array.isArray(d.users) || !Array.isArray(d.requests)) throw new Error('format');
          Store.replaceAll(d).then(() => { toast('Дані відновлено', 'good'); rerender(); });
        } catch (err) { toast('Файл не схожий на резервну копію системи', 'crit'); }
      };
      rd.readAsText(file);
    };
    const confirmZone = (msg, action) => {
      $('#confirm-zone').innerHTML = `<div class="confirm"><p>${msg}</p><div class="row-end"><button class="btn btn-ghost" type="button" id="cz-no">Скасувати</button><button class="btn btn-primary danger-bg" type="button" id="cz-yes">Так, виконати</button></div></div>`;
      $('#cz-no').onclick = () => { $('#confirm-zone').innerHTML = ''; };
      $('#cz-yes').onclick = action;
    };
    $('#reset-demo').onclick = () => confirmZone('Поточні дані буде замінено демонстраційними. Продовжити?', () => Store.reset(true).then(() => { ls.set('dss.session', 'head'); toast('Демо-дані відновлено'); rerender(); }));
    $('#reset-empty').onclick = () => confirmZone('Усі звернення, зміни, працівники та пропозиції буде видалено. Залишиться один обліковий запис керівника з PIN 0000 — змініть його в «Персоналі». Зробіть резервну копію, якщо дані потрібні.', () => Store.reset(false).then(() => { ls.set('dss.session', 'head'); toast('Створено чисту базу'); rerender(); }));
  }

  /* ---------- Таймери ---------- */
  setInterval(() => {
    $$('[data-since]').forEach(e => e.textContent = dur(Date.now() - +e.dataset.since));
    if (state.draft && state.draft.swStart) { const d = $('#sw-display'); if (d) d.textContent = Math.round((Date.now() - state.draft.swStart) / 1000) + ' с'; }
  }, 1000);
  let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => { if (state.user && !$('#req-form')) rerender(); }, 250); });

  /* ---------- Старт ---------- */
  applyTheme();
  Store.init().then(() => {
    addEventListener('hashchange', () => { state.endingShift = false; route(); scrollTo(0, 0); });
    route();
  });
})();
