@echo off
cd /d "%~dp0"
py -3.10 -m venv .venv
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" tools\prepare_data.py
if errorlevel 1 goto failed
echo Python setup complete. See README.md for game setup.
pause
exit /b 0
:failed
echo Setup failed. Install 64-bit Python 3.10 and check the error above.
pause
exit /b 1
