@echo off
REM ABAP Atlas - one-click runner for Windows.
REM   run.bat                 -> set up, run the pipeline on the newest ZIP in data\input, show stats
REM   run.bat search "query"  -> any atlas command, e.g. run.bat search "vendor ageing report"
REM   run.bat watch           -> automation: process every ZIP dropped into data\input
REM   run.bat ui              -> start the web app at http://localhost:8080
REM Prefers Python 3.12 (needed only for the optional MiniLM model); any Python 3.10+ works for the core.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" not found. Install Python from python.org and tick "Add to PATH".
  exit /b 1
)

set PYVER=
py -3.12 -c "import sys" >nul 2>nul && set PYVER=-3.12
if "%PYVER%"=="" (
  py -3 -c "import sys" >nul 2>nul && set PYVER=-3
)
if "%PYVER%"=="" (
  echo No Python 3 found. Install Python 3.12 from https://www.python.org/downloads/
  exit /b 1
)
if not "%PYVER%"=="-3.12" (
  echo Note: using the default Python 3 ^(not 3.12^). Core features work; the optional
  echo MiniLM meaning model needs 3.12. Install 3.12 later and delete .venv to switch.
)

REM (dependency check happens after activation below)
if not exist .venv (
  echo Creating virtual environment...
  py %PYVER% -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -e .
  if errorlevel 1 (
    echo Install failed. Check the error above ^(usually network/proxy^).
    exit /b 1
  )
) else (
  call .venv\Scripts\activate.bat
  python -c "import docx, pypdf, nicegui, sqlalchemy, typer" >nul 2>nul
  if errorlevel 1 (
    echo Installing missing packages...
    python -m pip install --quiet -e .
  )
)

if "%~1"=="" (
  atlas run --system DEV
  atlas stats
) else (
  atlas %*
)
endlocal
