@echo off
rem Dev server for the PC. Uses the project's own Python environment
rem (.venv, made by setup_venv.bat) when it exists, so packages installed
rem for other projects cannot break this one, and the development copy of
rem the database (data\market_data.dev.db, made by scripts\make_dev_db.py)
rem when it exists, so other people's accounts are not on this machine.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "data\market_data.dev.db" (
  set "LEDGERLINE_DB=market_data.dev.db"
  echo Using the development database: data\market_data.dev.db
) else (
  echo Using data\market_data.db
)
cd backend
"%PY%" -m uvicorn app.main:app --reload --port 8000
