@echo off
cd /d "%~dp0"
python news_alert.py --loop --interval 600
pause
