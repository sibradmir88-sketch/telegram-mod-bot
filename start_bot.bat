@echo off
chcp 65001 >nul
title desacratio Helper Bot
cd /d "%~dp0"
echo Запуск бота... (закрыть окно = остановить бота)
venv-win\Scripts\python.exe bot.py
echo.
echo Бот остановлен.
pause
