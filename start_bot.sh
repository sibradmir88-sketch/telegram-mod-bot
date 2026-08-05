#!/bin/bash
# Старт/keepalive telegram-mod-bot. Используется crontab'ом.
cd /home/radmir/telegram-mod-bot || exit 1
if ! pgrep -f "venv/bin/python bot.py" > /dev/null; then
  nohup ./venv/bin/python bot.py >> bot.log 2>&1 &
fi
