# Inspire: база, бот и пульт танцевального коллектива

База на 110 танцоров: финансы, CRM заказчиков, переписка с танцорами через Telegram, файлы проектов,
утренняя сводка в JPEG размером с экран iPhone и веб-пульт в стиле iOS с доступом по IP.

Инструкция для руководителя: [ИНСТРУКЦИЯ_РУКОВОДИТЕЛЯ.md](ИНСТРУКЦИЯ_РУКОВОДИТЕЛЯ.md).

## Файлы

| Файл | Назначение |
|---|---|
| `db.py` | схема SQLite: танцоры, заказчики, проекты, операции, контакты, составы, репетиции, посещаемость, сообщения, файлы |
| `bot.py` | Telegram-бот (руководитель и танцоры) + ежедневная сводка по расписанию |
| `dashboard.py` | веб-пульт, IP-фильтр + ключ доступа, JSON API для форм, отправка в Telegram |
| `web/index.html` | интерфейс пульта (Chart.js) |
| `summary.py` | сводка: статистика, цитата дня, «этот день в истории» → JPEG 1179×2556 |
| `stats.py`, `content.py` | расчёт показателей; цитаты и календарь событий танца и искусства |
| `import_dancers.py` | импорт реального списка танцоров из CSV |
| `seed_demo.py` | демо-база (110 танцоров, 2,5 года истории), только для показа |
| `build_preview.py` | статичное демо пульта без сервера |
| `deploy/` | systemd-сервисы и ночной бэкап |

## Запуск на сервере (VPS с Ubuntu, от 5 €/мес)

```bash
sudo mkdir -p /opt/inspire && sudo cp -r . /opt/inspire && cd /opt/inspire
pip install -r requirements.txt
python -m playwright install --with-deps chromium
cp .env.example .env && nano .env          # токен бота, ваш Telegram ID, ключ пульта
python import_dancers.py dancers.csv       # ваш список (или python seed_demo.py для демо)
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl enable --now inspire-bot inspire-dashboard
sudo ufw allow 8080/tcp
```

Пульт: `http://IP-сервера:8080/?key=<DASH_KEY>`. Если нужен HTTPS и домен, поставьте перед ним Caddy
(`caddy reverse-proxy --from inspire.example.de --to :8080`).

## Проверено

- демо-база генерируется (110 танцоров, ~360 проектов, ~1100 операций, ~10 тыс. отметок посещаемости);
- сводка рендерится в JPEG 1179×2556;
- пульт: доступ без ключа и с чужого IP → 403, с ключом → 200; формы пишут в базу; неверная сумма → понятная ошибка;
- бот импортируется и собирается с job-queue; привязка платежа к проекту по имени заказчика работает.

С живым Telegram бот не запускался: для этого нужен токен от @BotFather.
