#!/bin/bash
# Sunday 18:00 Europe/Warsaw, e.g.:
#   CRON_TZ=Europe/Warsaw
#   0 18 * * 0 /opt/german_news/run_weekly_announce.sh
set -a
source /opt/german_news/.env
set +a
/opt/german_news/venv/bin/python /opt/german_news/weekly_announce.py >> /opt/german_news/bot.log 2>&1
