// Parses work schedule tables (CSV/TSV, ATOSS format and similar)

const MONTH_MAP = {
  januar:0, februar:1, märz:2, april:3, mai:4, juni:5,
  juli:6, august:7, september:8, oktober:9, november:10, dezember:11,
  january:0, february:1, march:2, june:5, july:6, august:7,
  september:8, october:9, november:10, december:11,
  январь:0, февраль:1, март:2, апрель:3, май:4, июнь:5,
  июль:6, август:7, сентябрь:8, октябрь:9, ноябрь:10, декабрь:11
};

function detectDelimiter(text) {
  const sample = text.slice(0, 2000);
  const counts = { '\t': 0, ';': 0, ',': 0, '|': 0 };
  for (const ch of sample) if (ch in counts) counts[ch]++;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
}

function parseTime(str) {
  if (!str) return null;
  str = str.trim().replace(',', '.');
  const m = str.match(/^(\d{1,2})[.:h](\d{2})$/);
  if (!m) return null;
  return m[1].padStart(2, '0') + ':' + m[2];
}

function parseDate(str, contextYear, contextMonth) {
  if (!str) return null;
  str = str.trim();
  let m = str.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$/);
  if (m) {
    const y = m[3].length === 2 ? 2000 + parseInt(m[3]) : parseInt(m[3]);
    return new Date(y, parseInt(m[2]) - 1, parseInt(m[1]));
  }
  m = str.match(/^(\d{1,2})\.(\d{1,2})\.?$/);
  if (m && contextYear != null && contextMonth != null) {
    return new Date(contextYear, contextMonth, parseInt(m[1]));
  }
  m = str.match(/^[A-Za-zЀ-ӿ]{2,3}\.?\s+(\d{1,2})\.(\d{1,2})\.(\d{2,4})$/);
  if (m) {
    const y = m[3].length === 2 ? 2000 + parseInt(m[3]) : parseInt(m[3]);
    return new Date(y, parseInt(m[2]) - 1, parseInt(m[1]));
  }
  m = str.match(/^(\d{1,2})$/);
  if (m && contextYear != null && contextMonth != null) {
    return new Date(contextYear, contextMonth, parseInt(m[1]));
  }
  return null;
}

function extractMetaFromText(text) {
  let year = null, month = null, name = null;
  const monthYearMatch = text.match(/([Ѐ-ӿA-Za-z]+)\s+(\d{4})/);
  if (monthYearMatch) {
    const mName = monthYearMatch[1].toLowerCase();
    if (mName in MONTH_MAP) { month = MONTH_MAP[mName]; year = parseInt(monthYearMatch[2]); }
  }
  const nameMatch = text.match(/^([A-ZА-Я][a-zа-я]+ [A-ZА-Я][a-zа-я]+)/m);
  if (nameMatch) name = nameMatch[1];
  return { year, month, name };
}

function minutesFromTime(t) {
  if (!t) return null;
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}

function calcDuration(start, end) {
  if (!start || !end) return null;
  let diff = minutesFromTime(end) - minutesFromTime(start);
  if (diff < 0) diff += 24 * 60;
  return diff;
}

function calcBreakMinutes(p1start, p1end) {
  if (!p1start || !p1end) return 0;
  const d = minutesFromTime(p1end) - minutesFromTime(p1start);
  return d > 0 ? d : 0;
}

function parseSchedule(text) {
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const { year, month, name } = extractMetaFromText(text);
  const delim = detectDelimiter(text);
  const lines = text.split('\n').filter(l => l.trim());

  const shifts = [];
  let headerRow = null;
  let headerIdx = {};

  const knownCols = ['tag','von','bis','pause','abw','vkst','arbeitsplatz','azx','datum','start','end','break','day','date','время','начало','конец','перерыв','день'];

  for (let i = 0; i < lines.length; i++) {
    const cells = lines[i].split(delim).map(c => c.trim().replace(/^["']|["']$/g, ''));

    if (!headerRow) {
      const lower = cells.map(c => c.toLowerCase());
      const matches = lower.filter(c => knownCols.some(k => c.includes(k))).length;
      if (matches >= 2) {
        headerRow = lower;
        lower.forEach((c, idx) => {
          if (c.includes('tag') || c.includes('day') || c.includes('день') || c.includes('datum') || c.includes('date')) headerIdx.day = idx;
          if (c.includes('von') || c.includes('start') || c.includes('начало') || c === 'от') headerIdx.start = idx;
          if (c.includes('bis') || c.includes('end') || c.includes('конец') || c === 'до') headerIdx.end = idx;
          if (c.includes('pause') || c.includes('перерыв') || c.includes('break')) {
            if (!('pause1' in headerIdx)) headerIdx.pause1 = idx;
            else if (!('pause1end' in headerIdx) && idx > headerIdx.pause1) headerIdx.pause1end = idx;
          }
          if (c.includes('arbeitsplatz') || c.includes('место') || c.includes('location')) headerIdx.location = idx;
          if (c.includes('abw')) headerIdx.absence = idx;
          if (c.includes('azx') || c.includes('overtime') || c.includes('сверх')) headerIdx.overtime = idx;
        });
        continue;
      }
    }

    if (!headerRow) continue;

    const dayRaw = cells[headerIdx.day ?? 0];
    if (!dayRaw || dayRaw.length < 1) continue;

    const lowerDay = dayRaw.toLowerCase();
    if (['tag','day','день','дата','date','summe','итого','total'].some(s => lowerDay.includes(s))) continue;

    const startTime = parseTime(cells[headerIdx.start]);
    const endTime = parseTime(cells[headerIdx.end]);

    if (!startTime && !endTime) {
      const date = parseDate(dayRaw, year, month);
      if (!date) continue;
      shifts.push({ date, dayLabel: dayRaw, isOff: true });
      continue;
    }

    const date = parseDate(dayRaw, year, month);
    if (!date) continue;

    const p1start = parseTime(cells[headerIdx.pause1]);
    const p1end = parseTime(cells[headerIdx.pause1end]);
    const absence = headerIdx.absence != null ? (cells[headerIdx.absence] || '').trim() : '';
    const location = headerIdx.location != null ? (cells[headerIdx.location] || '').trim() : '';
    const overtime = headerIdx.overtime != null ? (cells[headerIdx.overtime] || '').trim() : '';

    const totalMins = calcDuration(startTime, endTime);
    const breakMins = calcBreakMinutes(p1start, p1end);
    const workMins = totalMins != null ? totalMins - breakMins : null;

    shifts.push({
      date, dayLabel: dayRaw,
      start: startTime, end: endTime,
      pause1Start: p1start, pause1End: p1end,
      absence: absence || null,
      location: location || null,
      overtime: overtime || null,
      totalMins, breakMins, workMins,
      isOff: false,
      isAbsent: !!absence
    });
  }

  return { shifts, year, month, name };
}

window.ScheduleParser = { parseSchedule };