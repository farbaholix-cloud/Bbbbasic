/*
 * Аналітика: KPI, інтегральний показник, розрахунок штату (Erlang C),
 * фінанси та рекомендації. Усі функції чисті: на вхід дані, на вихід числа.
 */
(function () {
  const HOUR = 36e5, DAY = 864e5;

  const median = a => { if (!a.length) return 0; const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const pct = (a, p) => { if (!a.length) return 0; const s = a.slice().sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
  const sum = a => a.reduce((x, y) => x + y, 0);
  const avg = a => a.length ? sum(a) / a.length : 0;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  function range(days, now) {
    now = now || Date.now();
    const end = now, start = now - days * DAY;
    return { start, end, days, prevStart: start - days * DAY, prevEnd: start };
  }
  const inR = (t, a, b) => t >= a && t < b;
  const shiftHours = (s, a, b, now) => {
    const st = Math.max(s.start, a), en = Math.min(s.end || now, b);
    return Math.max(0, en - st) / HOUR;
  };

  function kpi(reqs, shifts, a, b, now) {
    const R = reqs.filter(q => inR(q.ts, a, b));
    const S = shifts.filter(s => s.start < b && (s.end || now) > a);
    const hours = sum(S.map(s => shiftHours(s, a, b, now)));
    const frts = R.map(q => q.frt);
    const rates = R.filter(q => q.rate).map(q => q.rate);
    const n = R.length || 1;
    return {
      count: R.length,
      frtMed: median(frts), frtP90: pct(frts, 0.9),
      resolve: R.filter(q => q.out === 'ok').length / n,
      escalate: R.filter(q => q.out === 'esc').length / n,
      rma: R.filter(q => q.out === 'rma').length,
      crit: R.filter(q => q.pr === 'crit').length,
      critSla: R.filter(q => q.pr === 'crit').length ? R.filter(q => q.pr === 'crit' && q.frt <= 30).length / R.filter(q => q.pr === 'crit').length : 1,
      back: R.filter(q => q.back).length,
      durAvg: avg(R.map(q => q.dur)),
      rating: avg(rates), ratingN: rates.length,
      hours, shifts: S.length,
      perHour: hours ? R.length / hours : 0,
      util: hours ? sum(R.map(q => q.dur)) / 60 / hours : 0,
      R, S
    };
  }

  // Інтегральний показник консультанта (розділ 11.1 регламенту)
  function score(k, target) {
    if (!k.count) return null;
    const sFrt = clamp(100 * (1 - (k.frtMed - target.frt * 0.5) / (target.frt * 2)), 0, 100);
    const sRes = clamp((k.resolve - 0.5) / 0.45 * 100, 0, 100);
    const sProd = clamp(k.perHour / 1.6 * 100, 0, 100);
    const sRate = k.ratingN ? clamp((k.rating - 2.5) / 2.5 * 100, 0, 100) : 70;
    const logged = k.R.filter(q => q.note && q.note.length > 10).length / k.count;
    const sDisc = clamp(logged * 100, 0, 100);
    return Math.round(sFrt * 0.3 + sRes * 0.3 + sProd * 0.2 + sRate * 0.1 + sDisc * 0.1);
  }

  function team(db, rg, now) {
    const set = db.settings;
    const target = { frt: set.targetFrtSec };
    return db.users.filter(u => u.role === 'consultant').map(u => {
      const reqs = db.requests.filter(q => q.uid === u.id), sh = db.shifts.filter(s => s.uid === u.id);
      const k = kpi(reqs, sh, rg.start, rg.end, now);
      const kp = kpi(reqs, sh, rg.prevStart, rg.prevEnd, now);
      const nights = k.S.filter(s => new Date(s.start).getHours() >= 18).length;
      const fat = k.S.filter(s => s.fatigue).map(s => s.fatigue);
      const pay = k.hours * u.rate;
      return {
        u, k, kp, score: score(k, target), scorePrev: score(kp, target),
        nights, nightShare: k.shifts ? nights / k.shifts : 0,
        fatigue: fat.length ? avg(fat) : null, pay,
        costPerReq: k.count ? pay / k.count : 0,
        onDuty: sh.some(s => !s.end)
      };
    });
  }

  // Erlang C: скільки консультантів потрібно, щоб slaShare звернень отримали відповідь за slaSec
  function erlangAgents(lambdaPerHour, ahtMin, slaSec, slaShare) {
    if (lambdaPerHour <= 0) return 1;
    const A = lambdaPerHour * ahtMin / 60;  // навантаження в ерлангах
    for (let N = Math.max(1, Math.ceil(A)); N < 60; N++) {
      let term = 1, s = 1;
      for (let k = 1; k < N; k++) { term *= A / k; s += term; }
      const last = term * A / N;
      const pw = (last * N / (N - A)) / (s + last * N / (N - A));
      if (N <= A) continue;
      const sl = 1 - pw * Math.exp(-(N - A) * slaSec / (ahtMin * 60));
      if (sl >= slaShare) return N;
    }
    return 60;
  }

  // Навантаження: середня кількість звернень на годину доби + потреба і фактична присутність
  function load(db, rg, now) {
    const set = db.settings;
    const R = db.requests.filter(q => inR(q.ts, rg.start, rg.end));
    const heat = Array.from({ length: 7 }, () => new Array(24).fill(0));
    const byHour = new Array(24).fill(0), durByHour = Array.from({ length: 24 }, () => []);
    R.forEach(q => { const d = new Date(q.ts); heat[(d.getDay() + 6) % 7][d.getHours()]++; byHour[d.getHours()]++; durByHour[d.getHours()].push(q.dur); });
    const weeks = rg.days / 7;
    const staffed = new Array(24).fill(0);
    db.shifts.forEach(s => {
      for (let t = Math.max(s.start, rg.start); t < Math.min(s.end || now, rg.end); t += HOUR) staffed[new Date(t).getHours()] += 1;
    });
    const hours = byHour.map((n, h) => {
      const lam = n / rg.days;
      const aht = avg(durByHour[h]) || 10;
      return {
        h, lam, aht,
        need: erlangAgents(lam, aht, set.slaSec, set.slaShare),
        have: staffed[h] / rg.days
      };
    });
    hours.forEach(x => { x.need = Math.max(2, x.need); });  // регламент 3.2: не менше двох
    const needHoursDay = sum(hours.map(x => x.need));
    const fteNeed = needHoursDay * 30.4 / (set.fteHoursMonth * (1 - set.shrinkage));
    const active = db.users.filter(u => u.role === 'consultant' && u.active).length;
    const hoursPerHead = active ? sum(staffed) / rg.days * 30.4 / active : 0;
    return { heat: heat.map(r => r.map(v => v / weeks)), hours, fteNeed, active, hoursPerHead };
  }

  function finance(db, rg, now) {
    const set = db.settings;
    const T = team(db, rg, now);
    const payroll = sum(T.map(t => t.pay));
    const months = rg.days / 30.4;
    const bonus = payroll * set.bonusPoolPct / 100;
    const tax = (payroll + bonus) * set.taxPct / 100;
    const overhead = set.overheadMonth * months;
    const total = payroll + bonus + tax + overhead;
    const k = kpi(db.requests, db.shifts, rg.start, rg.end, now);
    const resolved = k.R.filter(q => q.out === 'ok').length;
    const effect = k.back * set.avgUnitCost;
    // розподіл премії (11.2): пропорційно показнику серед тих, у кого 60+
    const elig = T.filter(t => t.score >= 60 && t.k.count);
    const sScore = sum(elig.map(t => t.score));
    const bonuses = T.map(t => ({ t, bonus: elig.includes(t) ? bonus * t.score / sScore : 0 }));
    return {
      payroll, bonus, tax, overhead, total, months,
      costPerReq: k.count ? total / k.count : 0,
      costPerResolved: resolved ? total / resolved : 0,
      costPerHourCoverage: total / (rg.days * 24),
      effect, roi: total ? effect / total : 0, back: k.back, count: k.count, bonuses
    };
  }

  function monthly(db, now) {
    const set = db.settings;
    const map = {};
    const key = t => { const d = new Date(t); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); };
    const rate = Object.fromEntries(db.users.map(u => [u.id, u.rate]));
    db.shifts.forEach(s => {
      const m = map[key(s.start)] = map[key(s.start)] || { m: key(s.start), hours: 0, payroll: 0, req: 0, ok: 0, back: 0 };
      const h = ((s.end || now) - s.start) / HOUR;
      m.hours += h; m.payroll += h * (rate[s.uid] || 0);
    });
    db.requests.forEach(q => {
      const m = map[key(q.ts)] = map[key(q.ts)] || { m: key(q.ts), hours: 0, payroll: 0, req: 0, ok: 0, back: 0 };
      m.req++; if (q.out === 'ok') m.ok++; if (q.back) m.back++;
    });
    return Object.values(map).sort((a, b) => a.m < b.m ? -1 : 1).map(m => {
      const bonus = m.payroll * set.bonusPoolPct / 100;
      const tax = (m.payroll + bonus) * set.taxPct / 100;
      const total = m.payroll + bonus + tax + set.overheadMonth;
      return Object.assign(m, { bonus, tax, overhead: set.overheadMonth, total, cpr: m.req ? total / m.req : 0, effect: m.back * set.avgUnitCost });
    });
  }

  function daily(db, rg) {
    const days = [];
    const d0 = new Date(rg.start); d0.setHours(0, 0, 0, 0);
    for (let t = d0.getTime(); t < rg.end; t += DAY) days.push({ t, n: 0, frts: [], ok: 0 });
    db.requests.forEach(q => {
      if (q.ts < d0.getTime() || q.ts >= rg.end) return;
      const i = Math.floor((q.ts - d0.getTime()) / DAY); const d = days[i]; if (!d) return;
      d.n++; d.frts.push(q.frt); if (q.out === 'ok') d.ok++;
    });
    return days.map(d => ({ t: d.t, n: d.n, frt: median(d.frts), ok: d.n ? d.ok / d.n : 0 }));
  }

  function groupBy(R, field, list) {
    return list.map(x => {
      const g = R.filter(q => q[field] === (x.id || x));
      return {
        id: x.id || x, label: x.short || x.label || x, n: g.length,
        frt: median(g.map(q => q.frt)),
        resolve: g.length ? g.filter(q => q.out === 'ok').length / g.length : 0,
        esc: g.length ? g.filter(q => q.out === 'esc' || q.out === 'rma').length / g.length : 0
      };
    });
  }

  // [4,5,6,21,22] → ['04:00–07:00', '21:00–23:00']
  function spans(hours) {
    const hh = h => String(h % 24).padStart(2, '0') + ':00', out = [];
    hours.forEach(h => { const last = out[out.length - 1]; if (last && last[1] === h) last[1] = h + 1; else out.push([h, h + 1]); });
    return out.map(([a, b]) => hh(a) + '–' + hh(b));
  }

  /* Рекомендації: правила над даними. Кожна має рівень, обґрунтування цифрами та дію. */
  function recommendations(db, rg, now) {
    const set = db.settings, out = [];
    const k = kpi(db.requests, db.shifts, rg.start, rg.end, now);
    const kp = kpi(db.requests, db.shifts, rg.prevStart, rg.prevEnd, now);
    const T = team(db, rg, now).filter(t => t.u.active && t.k.count >= 15);
    const L = load(db, rg, now);
    const types = groupBy(k.R, 'type', DICT.types).sort((a, b) => b.n - a.n);
    const prods = groupBy(k.R, 'prod', DICT.products);
    const f = (x, d) => x.toFixed(d == null ? 0 : d);
    const p = x => Math.round(x * 100) + '%';

    // 1. Покриття годин
    const gaps = L.hours.filter(x => x.have + 0.25 < x.need);
    if (gaps.length) {
      const worst = gaps.slice().sort((a, b) => (b.need - b.have) - (a.need - a.have))[0];
      const frtGap = median(k.R.filter(q => gaps.some(g => g.h === new Date(q.ts).getHours())).map(q => q.frt));
      out.push({ lvl: 'crit', area: 'Графік', title: 'Недостатнє покриття у пікові години',
        why: `У ${gaps.length} год. доби консультантів менше, ніж потрібно для відповіді за ${set.slaSec} с. Найбільший розрив о ${worst.h}:00: потрібно ${worst.need}, фактично ${f(worst.have, 1)}. Медіана першої відповіді в ці години — ${f(frtGap)} с.`,
        act: `Посилити години ${spans(gaps.map(g => g.h)).join(', ')}: зсунути початок однієї денної зміни на 04:00 або додати пікову зміну на ці години.` });
    }
    // 2. Штат
    if (L.fteNeed > L.active + 0.5) {
      out.push({ lvl: 'warn', area: 'Штат', title: 'Потрібне розширення штату',
        why: `За поточного навантаження та вимоги ${p(set.slaShare)} відповідей за ${set.slaSec} с потрібно ${f(L.fteNeed, 1)} ставки з урахуванням ${p(set.shrinkage)} на перерви, навчання і хвороби. Активних консультантів: ${L.active}, у середньому ${f(L.hoursPerHead)} год на людину на місяць.`,
        act: `Найняти ${Math.ceil(L.fteNeed - L.active)} консультанта(ів). Кількість звернень за період зросла на ${p(kp.count ? k.count / kp.count - 1 : 0)} порівняно з попереднім.` });
    } else if (L.fteNeed < L.active - 1.5) {
      out.push({ lvl: 'info', area: 'Штат', title: 'Є резерв штату',
        why: `Потрібно ${f(L.fteNeed, 1)} ставки, активних консультантів ${L.active}.`, act: 'Перевести частину годин у навчання, базу знань і роботу з повторюваними дефектами.' });
    }
    // 3. Найчастіший тип
    const top = types[0];
    if (top && top.n / (k.count || 1) > 0.2) {
      out.push({ lvl: 'warn', area: 'Процес', title: `«${top.label}» — ${p(top.n / k.count)} усіх звернень`,
        why: `${top.n} звернень за період, медіана першої відповіді ${f(top.frt)} с, вирішено ${p(top.resolve)}. Це найбільший резерв економії часу.`,
        act: 'Підготувати покрокову інструкцію і відео (регламент 12.2), передати у виробництво пропозицію постачати вироби з передналаштованим профілем і QR-кодом на інструкцію.' });
    }
    // 4. Повторюваний дефект виробу
    const recent = db.requests.filter(q => q.ts >= now - 7 * DAY);
    const combo = {};
    recent.forEach(q => { if (q.out !== 'ok') { const key = q.prod + '|' + q.type; combo[key] = (combo[key] || 0) + 1; } });
    Object.entries(combo).filter(([, n]) => n >= 5).sort((a, b) => b[1] - a[1]).slice(0, 2).forEach(([key, n]) => {
      const [prod, type] = key.split('|');
      out.push({ lvl: 'crit', area: 'Виробництво', title: `Повторюваний дефект: ${prod}`,
        why: `${n} невирішених на місці звернень типу «${DICT.label('types', type)}» за останні 7 днів (поріг регламенту 9.3 — 5).`,
        act: 'Протягом 48 годин передати звіт з висновками консультантів у виробництво і R&D; до відповіді — окрема інструкція для всіх змін.' });
    });
    // 5. Ескалації по виробах
    const escProd = prods.filter(x => x.n >= 30 && x.esc > set.targetEscalate * 1.5).sort((a, b) => b.esc - a.esc)[0];
    if (escProd) out.push({ lvl: 'warn', area: 'Навчання', title: `Висока частка ескалацій: ${escProd.label}`,
      why: `${p(escProd.esc)} звернень по цьому виробу ескалюються або йдуть у ремонт (ціль — не більше ${p(set.targetEscalate)}).`,
      act: 'Провести 2-годинне навчання консультантів по цьому виробу з інженером другої лінії; додати дерево діагностики в базу знань.' });
    // 6. Повільні консультанти та наставники
    const frtTeam = k.frtMed;
    T.filter(t => t.k.frtMed > Math.max(set.targetFrtSec * 1.4, frtTeam * 1.5)).forEach(t => {
      out.push({ lvl: 'warn', area: 'Команда', title: `Коучинг: ${t.u.name}`,
        why: `Медіана першої відповіді ${f(t.k.frtMed)} с проти ${f(frtTeam)} с по відділу; вирішено ${p(t.k.resolve)}.`,
        act: 'Дві зміни в парі з наставником, розбір 5 звернень, шаблони перших відповідей. Повторна оцінка через 2 тижні.' });
    });
    const best = T.slice().sort((a, b) => b.score - a.score)[0];
    if (best && best.score >= 75) out.push({ lvl: 'good', area: 'Команда', title: `Наставник: ${best.u.name}`,
      why: `Найвищий інтегральний показник у відділі — ${best.score}. Медіана відповіді ${f(best.k.frtMed)} с, вирішено ${p(best.k.resolve)}.`,
      act: 'Призначити наставником для нових консультантів і кандидатом на посаду старшого зміни (регламент 11.4).' });
    // 7. Втома
    T.filter(t => t.fatigue != null && t.fatigue <= 2.3).forEach(t => {
      out.push({ lvl: 'crit', area: 'Люди', title: `Ризик вигорання: ${t.u.name}`,
        why: `Середня самооцінка втоми ${f(t.fatigue, 1)} з 5; нічних змін — ${p(t.nightShare)} від усіх (${t.nights}).`,
        act: 'Зменшити кількість нічних змін, надати додатковий вихідний, запропонувати зустріч із психологом (регламент 10.3).' });
    });
    // 8. Канали
    const chans = groupBy(k.R, 'ch', DICT.channels);
    const slowCh = chans.filter(c => c.n > 50).sort((a, b) => b.frt - a.frt)[0];
    if (slowCh && slowCh.frt > frtTeam * 1.2) out.push({ lvl: 'info', area: 'Канали', title: `Найповільніший канал — ${slowCh.label}`,
      why: `Медіана першої відповіді ${f(slowCh.frt)} с проти ${f(frtTeam)} с загалом.`,
      act: 'Вивести всі канали в один робочий інтерфейс або закріпити за каналом відповідального на зміні.' });
    // 9. Критичні SLA
    if (k.critSla < 0.9) out.push({ lvl: 'crit', area: 'Якість', title: 'Критичні звернення: стандарт 30 с не виконується',
      why: `Лише ${p(k.critSla)} критичних звернень отримали першу відповідь за 30 секунд (регламент 5.1).`,
      act: 'Ввести позначку «КРИТИЧНО» першим словом у повідомленні оператора та окремий звуковий сигнал на робочих пристроях.' });
    // 10. Тренд
    if (kp.count && k.frtMed > kp.frtMed * 1.15) out.push({ lvl: 'warn', area: 'Якість', title: 'Час відповіді погіршується',
      why: `Медіана першої відповіді зросла з ${f(kp.frtMed)} до ${f(k.frtMed)} с порівняно з попереднім періодом.`, act: 'Перевірити графік у пікові години і кількість одночасних діалогів на консультанта.' });

    const order = { crit: 0, warn: 1, info: 2, good: 3 };
    return out.sort((a, b) => order[a.lvl] - order[b.lvl]);
  }

  window.Analytics = { kpi, team, load, finance, monthly, daily, groupBy, recommendations, spans, range, median, sum, avg, erlangAgents, HOUR, DAY };
})();
