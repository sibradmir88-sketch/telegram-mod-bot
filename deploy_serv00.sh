#!/bin/bash
# Деплой telegram-mod-bot на serv00.com (запускать ПО SSH на сервере serv00)
set -e

echo "=== 1/5 Клонируем репозиторий ==="
cd ~
if [ -d modbot ]; then
  git -C modbot pull --ff-only
else
  git clone https://github.com/sibradmir88-sketch/telegram-mod-bot.git modbot
fi
cd ~/modbot

echo "=== 2/5 Создаём виртуальное окружение ==="
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

echo "=== 3/5 Создаём .env (если нет) ==="
if [ ! -f .env ]; then
  cat > .env <<'ENV'
BOT_TOKEN=СЮДА_ТОКЕН
ADMIN_IDS=8587090554
ADMIN_USERNAMES=desacratio
ENV
  echo "Создан .env — ЗАМЕНИТЕ BOT_TOKEN на актуальный!"
else
  echo ".env уже существует, не трогаем"
fi

echo "=== 4/5 Перезапускаем бота ==="
pkill -f "venv/bin/python bot.py" 2>/dev/null || true
sleep 1
nohup ./venv/bin/python bot.py >> ~/modbot/bot.log 2>&1 &
sleep 3

echo "=== 5/5 Проверяем ==="
if pgrep -f "venv/bin/python bot.py" > /dev/null; then
  echo "БОТ ЗАПУЩЕН OK (pid $(pgrep -f 'venv/bin/python bot.py'))"
else
  echo "ВНИМАНИЕ: процесс не запущен, смотрим лог:"
fi
echo "--- bot.log (последние 20 строк) ---"
tail -n 20 ~/modbot/bot.log || true
