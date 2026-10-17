/*
 * Мінімальний сервер без залежностей (Node.js 18+): роздає інтерфейс і зберігає
 * спільну базу для всієї команди у backend/data/db.json.
 *
 *   DSS_USER=support DSS_PASS=довгий-пароль PORT=8080 node backend/server.js
 *
 * Потім у assets/config.js: storage: 'rest', seedDemo: false.
 * Вхід у браузері захищено HTTP Basic (DSS_USER / DSS_PASS); працюйте лише через HTTPS.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DATA = path.join(__dirname, 'data');
const DB_FILE = path.join(DATA, 'db.json');
const PORT = +process.env.PORT || 8080;
const USER = process.env.DSS_USER, PASS = process.env.DSS_PASS;
const COLLECTIONS = ['users', 'shifts', 'requests', 'proposals'];
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png' };

fs.mkdirSync(DATA, { recursive: true });
let db = fs.existsSync(DB_FILE) ? JSON.parse(fs.readFileSync(DB_FILE, 'utf8')) : null;
let timer = null;
function persist() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const tmp = DB_FILE + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(db));
    fs.renameSync(tmp, DB_FILE);
  }, 300);
}

function authorized(req) {
  if (!USER) return true;
  const h = req.headers.authorization || '';
  const [u, p] = Buffer.from(h.replace(/^Basic /, ''), 'base64').toString().split(':');
  return u === USER && p === PASS;
}
function body(req) {
  return new Promise((res, rej) => {
    let s = ''; req.on('data', c => { s += c; if (s.length > 50e6) req.destroy(); });
    req.on('end', () => { try { res(s ? JSON.parse(s) : null); } catch (e) { rej(e); } });
  });
}
function send(res, code, data) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(data === undefined ? '' : JSON.stringify(data));
}

http.createServer(async (req, res) => {
  if (!authorized(req)) { res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="DSS"' }); return res.end(); }
  const url = new URL(req.url, 'http://x');
  try {
    if (url.pathname.startsWith('/api/')) {
      const [, , col, id] = url.pathname.split('/');
      if (col === 'db') {
        if (req.method === 'GET') return send(res, 200, db);
        if (req.method === 'PUT') { db = await body(req); persist(); return send(res, 204); }
      }
      if (!db) return send(res, 409, { error: 'База ще не створена' });
      if (col === 'settings' && req.method === 'PUT') { const s = await body(req); delete s.id; db.settings = s; persist(); return send(res, 204); }
      if (COLLECTIONS.includes(col) && id) {
        const list = db[col] = db[col] || [];
        const i = list.findIndex(x => x.id === id);
        if (req.method === 'DELETE') { if (i >= 0) list.splice(i, 1); persist(); return send(res, 204); }
        if (req.method === 'PUT') { const rec = await body(req); if (i >= 0) list[i] = rec; else list.push(rec); persist(); return send(res, 204); }
      }
      return send(res, 404, { error: 'Невідомий запит' });
    }
    let file = path.normalize(path.join(ROOT, decodeURIComponent(url.pathname)));
    if (!file.startsWith(ROOT) || file.startsWith(path.join(ROOT, 'backend'))) { res.writeHead(403); return res.end(); }
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file)) { res.writeHead(404); return res.end('Не знайдено'); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  } catch (e) {
    console.error(e); send(res, 500, { error: 'Помилка сервера' });
  }
}).listen(PORT, () => console.log(`Система обліку: http://localhost:${PORT}`));
