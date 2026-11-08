@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0run.py" --start-game
if errorlevel 1 pause
