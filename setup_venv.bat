@echo off
rem Give Ledgerline its own Python environment (.venv) with the exact,
rem tested versions from backend\requirements.txt. Packages installed for
rem other projects (streamlit, ...) can then no longer break it.
rem Run once, and again after changing a version in requirements.txt.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo == creating .venv
  python -m venv .venv || goto :fail
)
rem A new venv ships an old pip that does not trust the Windows certificate
rem store, so behind a TLS-inspecting proxy it cannot reach PyPI. Fetch a
rem current pip with the system pip, install it into the venv offline.
echo == updating pip inside .venv
python -m pip download pip -d "%TEMP%\ll-wheels" -q || goto :fail
".venv\Scripts\python.exe" -m pip install -q --no-index --find-links "%TEMP%\ll-wheels" --upgrade pip || goto :fail
echo == installing pinned packages
".venv\Scripts\python.exe" -m pip install -q -r backend\requirements-dev.txt || goto :fail
".venv\Scripts\python.exe" -m pip check
echo.
echo Done. run.bat now uses .venv automatically.
exit /b 0
:fail
echo.
echo Setup failed - see the message above.
exit /b 1
