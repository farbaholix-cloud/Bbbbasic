/*
 * Шар даних. Інтерфейс у UI синхронний (читання з кешу в пам'яті),
 * запис іде в адаптер асинхронно. Щоб підключити сервер, достатньо
 * адаптера з методами load() і save(collection, record | {id, _deleted}).
 *
 * Колекції: users, shifts, requests, proposals; settings — один об'єкт.
 */
(function () {
  const KEY = 'dss.v1';
  const COLLECTIONS = ['users', 'shifts', 'requests', 'proposals'];

  const LocalAdapter = {
    load() {
      try { return Promise.resolve(JSON.parse(localStorage.getItem(KEY)) || null); }
      catch (e) { return Promise.resolve(null); }
    },
    saveAll(db) {
      try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (e) { console.warn('Не вдалося зберегти дані', e); }
      return Promise.resolve();
    },
    save(db) { return this.saveAll(db); }
  };

  // Приклад серверного адаптера: GET {apiBase}/db, PUT {apiBase}/{collection}/{id}, DELETE …
  const RestAdapter = {
    async load() {
      const r = await fetch(DSS_CONFIG.apiBase + '/db', { credentials: 'include' });
      return r.ok ? r.json() : null;
    },
    async saveAll(db) {
      await fetch(DSS_CONFIG.apiBase + '/db', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(db)
      });
    },
    async save(db, collection, record) {
      if (!collection) return this.saveAll(db);
      const url = DSS_CONFIG.apiBase + '/' + collection + (record.id ? '/' + record.id : '');
      await fetch(url, {
        method: record._deleted ? 'DELETE' : 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(record)
      });
    }
  };

  const adapter = (window.DSS_CONFIG && DSS_CONFIG.storage === 'rest') ? RestAdapter : LocalAdapter;
  let db = null;

  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  const Store = {
    async init() {
      db = await adapter.load();
      if (!db) {
        db = (DSS_CONFIG.seedDemo && window.DSS_SEED) ? DSS_SEED.build() : Store.emptyDb();
        await adapter.saveAll(db);
      }
      COLLECTIONS.forEach(c => { db[c] = db[c] || []; });
      db.settings = Object.assign(Store.defaultSettings(), db.settings || {});
    },
    emptyDb() {
      return {
        demo: false,
        users: [{ id: 'head', name: 'Керівник відділу', role: 'head', pin: '0000', rate: 0, active: true, hiredAt: new Date().toISOString().slice(0, 10) }],
        shifts: [], requests: [], proposals: [], settings: Store.defaultSettings()
      };
    },
    defaultSettings() {
      return {
        targetFrtSec: 45,          // медіана першої відповіді, с
        slaSec: 60,                // межа «відповіли вчасно» для розрахунку штату
        slaShare: 0.9,             // частка звернень, на які відповідаємо в межах slaSec
        targetResolve: 0.8,
        targetEscalate: 0.15,
        shiftHours: 12,
        fteHoursMonth: 168,        // годин на одну ставку на місяць
        shrinkage: 0.15,           // перерви, навчання, хвороби
        overheadMonth: 85000,      // зв'язок, техніка, ПЗ, оренда, грн/міс
        bonusPoolPct: 15,          // преміальний фонд, % від ФОП
        taxPct: 22,                // ЄСВ, %
        avgUnitCost: 25000,        // середня вартість виробу, що повертаємо в стрій, грн
        currency: 'грн'
      };
    },
    get db() { return db; },
    all(c) { return db[c]; },
    byId(c, id) { return db[c].find(x => x.id === id); },
    settings() { return db.settings; },
    put(c, rec) {
      if (!rec.id) rec.id = uid();
      const i = db[c].findIndex(x => x.id === rec.id);
      if (i >= 0) db[c][i] = rec; else db[c].push(rec);
      adapter.save(db, c, rec);
      return rec;
    },
    remove(c, id) {
      db[c] = db[c].filter(x => x.id !== id);
      adapter.save(db, c, { id, _deleted: true });
    },
    setSettings(patch) {
      Object.assign(db.settings, patch);
      adapter.save(db, 'settings', Object.assign({ id: 'main' }, db.settings));
    },
    replaceAll(newDb) { db = newDb; return adapter.saveAll(db); },
    reset(withDemo) {
      db = withDemo ? DSS_SEED.build() : Store.emptyDb();
      return adapter.saveAll(db);
    },
    uid
  };

  window.Store = Store;
})();
