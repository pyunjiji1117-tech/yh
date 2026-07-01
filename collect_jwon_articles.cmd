@echo off
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
"%PYTHON_EXE%" collect_einfomax_writer.py --max-articles 100 --max-pages 5 --delay 1.0
pause
