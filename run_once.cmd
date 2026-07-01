@echo off
cd /d "%~dp0"
python news_alert.py --once
pause
