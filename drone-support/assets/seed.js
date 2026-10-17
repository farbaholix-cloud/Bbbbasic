/*
 * Демо-дані: 8 тижнів роботи відділу з 12 консультантів.
 * Генеруються детерміновано (той самий результат при кожному скиданні),
 * відносно поточної дати. У реальному розгортанні: seedDemo: false.
 */
(function () {
  function rng(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  const STAFF = [
    // skill: frt — базовий час відповіді (с), res — імовірність вирішити, spd — множник тривалості
    { id: 'u01', name: 'Олена Коваль', rate: 260, frt: 22, res: 0.9, spd: 0.85, fat: 4, hired: 540 },
    { id: 'u02', name: 'Андрій Мельник', rate: 240, frt: 30, res: 0.86, spd: 0.9, fat: 4, hired: 470 },
    { id: 'u03', name: 'Ірина Бондар', rate: 240, frt: 28, res: 0.84, spd: 1.0, fat: 3.6, hired: 410 },
    { id: 'u04', name: 'Максим Ткаченко', rate: 220, frt: 38, res: 0.8, spd: 1.0, fat: 3.8, hired: 330 },
    { id: 'u05', name: 'Софія Шевчук', rate: 220, frt: 33, res: 0.82, spd: 0.95, fat: 4.2, hired: 300 },
    { id: 'u06', name: 'Дмитро Кравець', rate: 230, frt: 36, res: 0.79, spd: 1.05, fat: 1.9, hired: 380, nights: true },
    { id: 'u07', name: 'Юлія Олійник', rate: 210, frt: 35, res: 0.8, spd: 1.0, fat: 3.9, hired: 240 },
    { id: 'u08', name: 'Тарас Лисенко', rate: 210, frt: 72, res: 0.68, spd: 1.25, fat: 3.4, hired: 200 },
    { id: 'u09', name: 'Марія Савчук', rate: 200, frt: 40, res: 0.78, spd: 1.05, fat: 3.7, hired: 150 },
    { id: 'u10', name: 'Богдан Руденко', rate: 200, frt: 44, res: 0.75, spd: 1.1, fat: 3.5, hired: 120 },
    { id: 'u11', name: 'Катерина Мороз', rate: 190, frt: 48, res: 0.72, spd: 1.15, fat: 4.1, hired: 45 },
    { id: 'u12', name: 'Віктор Поліщук', rate: 200, frt: 42, res: 0.76, spd: 1.1, fat: 3.5, hired: 260, left: 20 }
  ];

  // Інтенсивність звернень по годинах доби (світанок і сутінки — пік бойової роботи)
  const HOURLY = [2.2, 1.8, 1.6, 2, 3.6, 5.8, 6.4, 5.2, 4, 3.4, 3.2, 3, 3, 2.9, 3, 3.3, 3.8, 4.4, 5.2, 5.6, 4.8, 4, 3.2, 2.6];
  const TYPE_W = { fw: 27, vid: 16, rc: 15, pwr: 10, dmg: 9, pay: 7, edu: 9, log: 7 };
  const TYPE_DUR = { fw: 14, vid: 10, rc: 12, pwr: 6, dmg: 18, pay: 9, edu: 22, log: 5 };
  const TYPE_DIFF = { fw: 0.02, vid: -0.06, rc: -0.02, pwr: 0.08, dmg: -0.3, pay: 0.02, edu: 0.1, log: 0.08 };
  const PROD_W = [26, 18, 9, 16, 12, 12, 7];
  const CH_W = { sig: 38, tg: 34, wa: 22, tel: 6 };
  const NOTES = {
    fw: ['Збилися налаштування після оновлення конфігуратора, відновили профіль із бази знань.', 'Невірна версія прошивки польотного контролера, перепрошили за інструкцією.', 'Не збережено калібрування акселерометра, провели калібрування разом з оператором.'],
    vid: ['Зміщена частота VTX через конфлікт каналів, переналаштували сітку частот.', 'Окислений роз\'єм камери, оператор зачистив контакти — картинка є.', 'Перегрів VTX на землі, рекомендовано не тримати увімкненим без обдуву.'],
    rc: ['Збився біндинг ELRS після заміни приймача, перев\'язали за 3 хв.', 'Невірний режим перемикача арму на апаратурі, виправили мапінг каналів.', 'Слабкий сигнал через розташування антени, показали правильне кріплення.'],
    pwr: ['АКБ розбалансована, рекомендовано режим балансування на зарядці.', 'Просідання напруги на холоді, порадили утеплення АКБ перед вильотом.'],
    dmg: ['Пошкоджено промінь рами після жорсткої посадки, оформлено відправку в ремонт.', 'Згорів регулятор обертів, заміна на місці з ремкомплекту.'],
    pay: ['Не спрацьовував скид, невірний канал сервоприводу — перепризначили.', 'Підказали налаштування затримки скиду під нову вагу.'],
    edu: ['Навчання новому режиму польоту, надіслано відео з бази знань.', 'Пояснили порядок передпольотної перевірки для нового екіпажу.'],
    log: ['Оформлено заміну пульта за гарантією, передано номер звернення.', 'Уточнено строки поставки запчастин.']
  };

  function pick(r, weights) {
    const keys = Object.keys(weights); let total = 0;
    keys.forEach(k => total += weights[k]);
    let x = r() * total;
    for (const k of keys) { x -= weights[k]; if (x <= 0) return k; }
    return keys[keys.length - 1];
  }
  function poisson(r, l) { let L = Math.exp(-l), k = 0, p = 1; do { k++; p *= r(); } while (p > L); return k - 1; }
  function lognorm(r, mean, sigma) {
    const u = Math.max(1e-9, r()), v = r();
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    return mean * Math.exp(sigma * z - sigma * sigma / 2);
  }

  function build() {
    const r = rng(20261017);
    const DAY = 864e5, HOUR = 36e5;
    const now = Date.now();
    const today = new Date(now); today.setHours(0, 0, 0, 0);
    const DAYS = 56;
    const start0 = today.getTime() - (DAYS - 1) * DAY;

    const users = [{ id: 'head', name: 'Керівник відділу', role: 'head', pin: '0000', rate: 0, active: true, hiredAt: iso(today.getTime() - 700 * DAY) }];
    STAFF.forEach(s => users.push({
      id: s.id, name: s.name, role: 'consultant', pin: '1111', rate: s.rate,
      active: !s.left, hiredAt: iso(today.getTime() - s.hired * DAY),
      leftAt: s.left ? iso(today.getTime() - s.left * DAY) : undefined
    }));

    const shifts = [], requests = [], prevNight = {};
    let rot = 0;
    for (let d = 0; d < DAYS; d++) {
      const dayStart = start0 + d * DAY;
      const daysAgo = DAYS - 1 - d;
      const pool = STAFF.filter(s => (s.hired > daysAgo) && !(s.left && daysAgo < s.left));
      const weekend = new Date(dayStart).getDay() % 6 === 0;
      const nDay = weekend ? 3 : 4, nNight = 2;
      const nightPref = pool.filter(s => s.nights);
      const others = pool.filter(s => !s.nights);
      const take = (n, list) => { const out = []; for (let i = 0; i < n && list.length; i++) out.push(list[(rot + i) % list.length]); rot += n; return out; };
      const night = take(nNight - nightPref.length, others).concat(d % 7 < 5 ? nightPref : []);
      while (night.length < nNight) night.push(take(1, others)[0]);
      const day = take(nDay, others.filter(s => !night.includes(s)));

      const mk = (list, sh, len) => list.map(s => {
        const st = dayStart + sh * HOUR + Math.round((r() - 0.6) * 8) * 60e3;
        const en = st + len * HOUR + Math.round(r() * 15) * 60e3;
        const open = en > now;
        const shift = {
          id: 'sh' + shifts.length, uid: s.id, start: st, end: open ? null : en,
          fatigue: open ? null : Math.max(1, Math.min(5, Math.round(s.fat + (r() - 0.5) * 1.6 - (sh === 20 ? 0.4 : 0)))),
          handover: open ? '' : (r() < 0.25 ? 'Незакритих звернень немає. Повторюється проблема з відео на «Крило-2».' : '')
        };
        if (st < now) shifts.push(shift);
        return { s, shift, st, en };
      });
      const onDay = mk(day, 8, 12), onNight = mk(night, 20, 12);

      const trend = 0.85 + 0.3 * d / DAYS;  // зростання поставок
      for (let h = 0; h < 24; h++) {
        const t0 = dayStart + h * HOUR;
        if (t0 > now) break;
        const lam = HOURLY[h] * trend * (weekend ? 0.92 : 1);
        const n = poisson(r, lam);
        const agents = (h >= 8 && h < 20) ? onDay : (h < 8 ? (prevNight[d] || onNight) : onNight);
        if (!agents.length) continue;
        for (let k = 0; k < n; k++) {
          const ts = t0 + Math.floor(r() * HOUR);
          if (ts > now) continue;
          const a = agents[Math.floor(r() * agents.length)];
          if (!a.shift || ts < a.st) continue;
          const s = a.s;
          let type = pick(r, TYPE_W);
          let prod = DICT.products[+pick(r, Object.assign({}, PROD_W))];
          // Дефект відео на «Крило-2» в останні три тижні
          if (daysAgo < 21 && r() < 0.12) { type = 'vid'; prod = 'Розвідник «Крило-2»'; }
          const pr = r() < 0.18 ? 'crit' : (r() < 0.45 ? 'high' : 'norm');
          const load = n / agents.length;
          const nightF = (h < 8 || h >= 20) ? 1.25 : 1;
          const prF = pr === 'crit' ? 0.6 : pr === 'high' ? 0.85 : 1.6;
          const frt = Math.round(Math.max(4, lognorm(r, s.frt * nightF * prF * (0.8 + load * 0.15), 0.55)));
          const dur = Math.max(1, Math.round(lognorm(r, TYPE_DUR[type] * s.spd, 0.45)));
          const p = r(), pOk = Math.min(0.97, s.res + TYPE_DIFF[type]);
          let out = p < pOk ? 'ok' : (type === 'dmg' && r() < 0.6 ? 'rma' : (r() < 0.82 ? 'esc' : 'wait'));
          if (daysAgo < 21 && prod === 'Розвідник «Крило-2»' && type === 'vid' && r() < 0.35) out = 'esc';
          const back = out === 'ok' && pr !== 'norm' && type !== 'edu' && type !== 'log' && r() < 0.55;
          const notes = NOTES[type];
          requests.push({
            id: 'rq' + requests.length, uid: s.id, sid: a.shift.id, ts,
            ch: pick(r, CH_W), type, pr, prod, frt, dur, out, back,
            rate: r() < 0.55 ? Math.max(1, Math.min(5, Math.round(3.4 + s.res * 2 - r() * 1.2))) : null,
            note: notes[Math.floor(r() * notes.length)]
          });
        }
      }
      prevNight[d + 1] = onNight;
    }

    const proposals = [
      { id: 'pr1', uid: 'u01', ts: now - 9 * DAY, section: '5.1', text: 'Додати окремий стандарт для нічних FPV: перша відповідь до 20 секунд, бо вікно для завдання коротке.', reason: 'У нічних критичних зверненнях оператор часто вже на позиції, кожна хвилина — зірване завдання.', status: 'review', comment: 'Перевіримо на даних за місяць.' },
      { id: 'pr2', uid: 'u06', ts: now - 6 * DAY, section: '3.3', text: 'Обмежити нічні зміни до двох поспіль для тих, хто працює понад рік.', reason: 'Після третьої ночі поспіль помітно падає концентрація.', status: 'new', comment: '' },
      { id: 'pr3', uid: 'u03', ts: now - 20 * DAY, section: '4.4', text: 'Очищати робочі чати щодня, а не щотижня.', reason: 'ОПСЕК: у разі втрати пристрою менше даних потрапить до ворога.', status: 'accepted', comment: 'Прийнято, увійде в редакцію 1.1.' },
      { id: 'pr4', uid: 'u08', ts: now - 3 * DAY, section: '7.2', text: 'Зробити поле «Висновок» необов\'язковим для звернень типу «Логістика».', reason: 'Висновок там зазвичай не потрібен, це забирає час.', status: 'new', comment: '' }
    ];

    return { demo: true, users, shifts, requests, proposals, settings: Store.defaultSettings() };
  }
  function iso(t) { return new Date(t).toISOString().slice(0, 10); }

  window.DSS_SEED = { build };
})();
