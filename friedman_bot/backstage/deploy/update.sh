#!/bin/sh
# Обновление Backstage на сервере: свежий код из git + перезапуск сервисов.
# Запуск: sudo /opt/backstage/friedman_bot/backstage/deploy/update.sh
set -e
cd /opt/backstage
sudo -u backstage git pull --ff-only
sudo -u backstage /opt/backstage/venv/bin/pip install -q -r friedman_bot/backstage/requirements.txt
systemctl restart backstage backstage-telegram
systemctl --no-pager status backstage | head -5
