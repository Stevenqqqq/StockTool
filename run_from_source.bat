@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found: %PYTHON%
    echo Create it first with: py -3.11 -m venv .venv
    exit /b 1
)

"%PYTHON%" launcher.py
exit /b %ERRORLEVEL%
