#!/bin/bash
export TZ=Europe/Warsaw
set -a
source /opt/dolnoslaskie_news/.env
set +a
# Single-instance: don't start a new run while the previous run is still active.
# If a run takes >5 minutes, keep a 5-minute break before allowing the next run.
flock -n /tmp/dolnoslaskie_news.lock bash -lc '
  start=$(date +%s)
  /opt/dolnoslaskie_news/venv/bin/python /opt/dolnoslaskie_news/main.py >> /opt/dolnoslaskie_news/bot.log 2>&1
  dur=$(( $(date +%s) - start ))
  if [ "$dur" -gt 300 ]; then
    sleep 300
  fi
'
