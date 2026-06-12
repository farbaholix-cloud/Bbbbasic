// Renders parsed schedule data into beautiful UI

const DAY_NAMES = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
const MONTH_NAMES = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

function timeProgress(startStr, endStr) {
  const now = new Date();
  const nowMins = now.getHours() * 60 + now.getMinutes();
  const s = startStr.split(':'); const e = endStr.split(':');
  const startMins = parseInt(s[0]) * 60 + parseInt(s[1]);
  const endMins = parseInt(e[0]) * 60 + parseInt(e[1]);
  if (nowMins < startMins || nowMins > endMins) return null;
  return Math.round(((nowMins - startMins) / (endMins - startMins)) * 100);
}

function isToday(date) {
  if (!date) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

function isWeekend(date) {
  if (!date) return false;
  const d = date.getDay();
  return d === 0 || d === 6;
}

function isFuture(date) {
  if (!date) return false;
  const now = new Date(); now.setHours(0,0,0,0);
  return date >= now;
}

function shiftCardHTML(shift) {
  const today = isToday(shift.date);
  const weekend = isWeekend(shift.date);
  const future = isFuture(shift.date);
  const date = shift.date;
  const dayNum = date ? date.getDate() : '?';
  const dayName = date ? DAY_NAMES[date.getDay()] : '';

  if (shift.isOff || (!shift.start && !shift.end)) {
    const cls = 'shift-card' + (weekend ? ' shift-weekend' : ' shift-off') + (today ? ' shift-today' : '');
    return `<div class="${cls}"><div class="shift-date"><span class="shift-day-num">${dayNum}</span><span class="shift-day-name">${dayName}</span></div><div class="shift-body shift-body-off"><span class="shift-off-label">Выходной</span></div></div>`;
  }

  if (shift.isAbsent && shift.absence) {
    return `<div class="shift-card shift-absent${today ? ' shift-today' : ''}"><div class="shift-date"><span class="shift-day-num">${dayNum}</span><span class="shift-day-name">${dayName}</span></div><div class="shift-body"><div class="shift-times"><span class="shift-time-badge">${shift.start || '—'} – ${shift.end || '—'}</span></div><div class="shift-absence-label">Отсутствие: ${shift.absence}</div></div></div>`;
  }

  const progress = (today && shift.start && shift.end) ? timeProgress(shift.start, shift.end) : null;
  const wH = shift.workMins != null ? Math.floor(shift.workMins / 60) : null;
  const wM = shift.workMins != null ? shift.workMins % 60 : null;
  const workLabel = wH != null ? (wH + 'ч' + (wM > 0 ? ' ' + wM + 'м' : '')) : '';
  const pauseLabel = (shift.pause1Start && shift.pause1End) ? `${shift.pause1Start} – ${shift.pause1End}` : shift.pause1Start ? `с ${shift.pause1Start}` : '';
  const locationBadge = shift.location ? `<span class="shift-location">${shift.location}</span>` : '';
  const overtimeBadge = shift.overtime && shift.overtime !== '0:00' && shift.overtime !== ''
    ? `<span class="shift-overtime ${parseFloat(shift.overtime) >= 0 ? 'ot-plus' : 'ot-minus'}">${shift.overtime}</span>` : '';
  const progressBar = progress != null ? `<div class="shift-progress"><div class="shift-progress-fill" style="width:${progress}%"></div></div>` : '';
  const stateClass = today ? 'shift-today' : (future ? '' : 'shift-past');

  return `
    <div class="shift-card ${stateClass}${weekend ? ' shift-weekend' : ''}">
      <div class="shift-date"><span class="shift-day-num">${dayNum}</span><span class="shift-day-name">${dayName}</span></div>
      <div class="shift-body">
        ${progressBar}
        <div class="shift-times">
          <span class="shift-time-start">${shift.start}</span>
          <span class="shift-time-arrow">→</span>
          <span class="shift-time-end">${shift.end}</span>
          ${workLabel ? `<span class="shift-duration">${workLabel}</span>` : ''}
        </div>
        ${pauseLabel ? `<div class="shift-pause"><span class="pause-icon">☕</span> Перерыв: ${pauseLabel}</div>` : ''}
        <div class="shift-meta">${locationBadge}${overtimeBadge}</div>
      </div>
    </div>`;
}

function renderSchedule(data, container) {
  if (!data || !data.shifts || data.shifts.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>Нет данных для отображения</p></div>';
    return;
  }
  const { shifts, year, month, name } = data;
  shifts.sort((a, b) => a.date - b.date);

  const displayYear = year ?? shifts[0]?.date?.getFullYear();
  const displayMonth = month ?? shifts[0]?.date?.getMonth();
  const monthLabel = displayMonth != null ? MONTH_NAMES[displayMonth] : '';
  const titleText = [name, monthLabel, displayYear].filter(Boolean).join(' · ');

  const workedShifts = shifts.filter(s => s.workMins > 0);
  const totalWorkMins = workedShifts.reduce((s, sh) => s + (sh.workMins || 0), 0);
  const totalShifts = workedShifts.length;
  const totalH = Math.floor(totalWorkMins / 60);
  const totalM = totalWorkMins % 60;
  const statsHTML = totalShifts > 0 ? `
    <div class="stats-bar">
      <div class="stat-item"><span class="stat-value">${totalShifts}</span><span class="stat-label">смен</span></div>
      <div class="stat-item"><span class="stat-value">${totalH}ч${totalM > 0 ? ' ' + totalM + 'м' : ''}</span><span class="stat-label">итого</span></div>
      <div class="stat-item"><span class="stat-value">${totalShifts > 0 ? Math.round(totalWorkMins / totalShifts / 60 * 10) / 10 : 0}ч</span><span class="stat-label">средняя</span></div>
    </div>` : '';

  container.innerHTML = `
    <div class="schedule-header">
      <h2 class="schedule-title">${titleText || 'Расписание'}</h2>
      ${statsHTML}
    </div>
    <div class="shifts-list">${shifts.map(shiftCardHTML).join('')}</div>`;

  setTimeout(() => {
    const todayCard = container.querySelector('.shift-today');
    if (todayCard) todayCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 100);
}

window.ScheduleRenderer = { renderSchedule };