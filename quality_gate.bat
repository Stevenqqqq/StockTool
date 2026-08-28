@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Python venv not found: %PYTHON%
    exit /b 1
)
"%PYTHON%" -m stock_tool.quality_gate
exit /b %ERRORLEVEL%
