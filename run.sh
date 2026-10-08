#!/bin/bash
export TZ=Europe/Warsaw
set -a
source /opt/dolnoslaskie_news/.env
set +a
# Single-instance: don't start a new run while the previous run is still active.
# Hard-stop a wedged run so one network/API failure cannot hold the lock indefinitely.
# Normal runs finish well below this limit; timeout is the last-resort watchdog.
flock -n /tmp/dolnoslaskie_news.lock bash -lc '
  start=$(date +%s)
  timeout --signal=TERM --kill-after=30s 15m \
    /opt/dolnoslaskie_news/venv/bin/python /opt/dolnoslaskie_news/main.py >> /opt/dolnoslaskie_news/bot.log 2>&1
  rc=$?
  dur=$(( $(date +%s) - start ))
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    echo "$(date "+%Y-%m-%d %H:%M:%S,%3N") ERROR main.py exceeded 15-minute watchdog; process was terminated" >> /opt/dolnoslaskie_news/bot.log
  elif [ "$rc" -ne 0 ]; then
    echo "$(date "+%Y-%m-%d %H:%M:%S,%3N") ERROR main.py exited with status $rc after ${dur}s" >> /opt/dolnoslaskie_news/bot.log
  fi
  if [ "$dur" -gt 300 ]; then
    sleep 300
  fi
'
