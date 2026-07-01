@echo off
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
"%PYTHON_EXE%" telegram_diagnostics.py
set "EXIT_CODE=%errorlevel%"
pause
exit /b %EXIT_CODE%
