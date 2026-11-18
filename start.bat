@echo off
rem Double-click to run the review app on this computer.
cd /d "%~dp0"
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY ( python -c "import sys" >nul 2>&1 && set PY=python )
if not defined PY (
  echo Python is not installed on this computer.
  echo.
  echo Open PowerShell and run:   winget install Python.Python.3.12
  echo Then close this window and double-click start.bat again.
  echo.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe %PY% -m venv .venv
echo Installing requirements...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if not exist state\sync.db (
  echo First run: reading the website and the CRM. Nothing is written.
  .venv\Scripts\python.exe pipeline.py
)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"
echo.
echo Review app: http://127.0.0.1:5000   (close this window to stop it)
.venv\Scripts\python.exe app.py
pause
