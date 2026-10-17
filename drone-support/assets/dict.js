/* Довідники: значення, які консультант обирає у формі звернення. */
window.DICT = {
  channels: [
    { id: 'sig', label: 'Signal' },
    { id: 'tg', label: 'Telegram' },
    { id: 'wa', label: 'WhatsApp' },
    { id: 'tel', label: 'Телефон' }
  ],
  types: [
    { id: 'fw', label: 'Налаштування і прошивка', short: 'Прошивка' },
    { id: 'vid', label: 'Відеозв\'язок (VTX, камера)', short: 'Відео' },
    { id: 'rc', label: 'Керування і радіоканал', short: 'Радіоканал' },
    { id: 'pwr', label: 'Живлення і АКБ', short: 'Живлення' },
    { id: 'dmg', label: 'Пошкодження і ремонт', short: 'Ремонт' },
    { id: 'pay', label: 'Корисне навантаження і скид', short: 'Скид' },
    { id: 'edu', label: 'Навчання оператора', short: 'Навчання' },
    { id: 'log', label: 'Логістика і заміна', short: 'Логістика' }
  ],
  priorities: [
    { id: 'crit', label: 'Критичний', hint: 'завдання зараз', sla: 30 },
    { id: 'high', label: 'Високий', hint: 'не працює', sla: 60 },
    { id: 'norm', label: 'Звичайний', hint: 'консультація', sla: 300 }
  ],
  outcomes: [
    { id: 'ok', label: 'Вирішено' },
    { id: 'esc', label: 'Ескальовано' },
    { id: 'rma', label: 'У ремонт' },
    { id: 'wait', label: 'Чекає оператора' }
  ],
  products: [
    'FPV «Шершень-7»', 'FPV «Шершень-10»', 'Нічний FPV «Сова-10»',
    'Розвідник «Крило-2»', 'Бомбер «Гекса-6»', 'Наземна станція НСК-3', 'Ретранслятор «Вежа»'
  ],
  label(list, id) { const x = this[list].find(i => i.id === id); return x ? (x.short || x.label) : id; }
};
