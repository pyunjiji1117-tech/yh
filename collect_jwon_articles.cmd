@echo off
cd /d "%~dp0"
python collect_einfomax_writer.py --max-articles 100 --max-pages 5 --delay 1.0
pause
