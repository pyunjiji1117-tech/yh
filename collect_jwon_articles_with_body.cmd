@echo off
cd /d "%~dp0"
python collect_einfomax_writer.py --include-body --confirm-ai-use-rights --max-articles 500 --max-pages 25 --delay 0.25 --output-dir data\einfomax_writer_latest500
pause
