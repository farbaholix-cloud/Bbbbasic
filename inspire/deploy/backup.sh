#!/bin/sh
# Ежедневная копия базы (cron: 30 3 * * * /opt/inspire/deploy/backup.sh)
cd /opt/inspire && mkdir -p backups && sqlite3 inspire.db ".backup backups/inspire_$(date +%F).db" && find backups -name '*.db' -mtime +30 -delete
