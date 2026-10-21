#!/bin/bash
set -euo pipefail
export TZ=Europe/Warsaw
set -a
source /opt/dolnoslaskie_news/.env
set +a
# Separate from the collection lock: a slow scraper cannot block the daily brief.
flock -n /tmp/dolnoslaskie_news_digest.lock \
  timeout --signal=TERM --kill-after=30s 5m \
  /opt/dolnoslaskie_news/venv/bin/python /opt/dolnoslaskie_news/main.py --mode digest \
  >> /opt/dolnoslaskie_news/bot.log 2>&1
