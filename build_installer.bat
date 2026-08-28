@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "STAGING_DIR=release\staging-sprint18.2.2\StockTool"
set "OUTPUT_DIR=artifacts\sprint18.2.2\installer"

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found: %PYTHON%
    exit /b 1
)

if not exist "%STAGING_DIR%\StockTool.exe" (
    echo ERROR: Sprint 18.2.2 staging EXE not found: %STAGING_DIR%\StockTool.exe
    echo Build it first with STOCK_TOOL_STAGING_PARENT=release\staging-sprint18.2.2 build_exe.bat
    exit /b 1
)

"%PYTHON%" -c "from pathlib import Path; from stock_tool.installer_build import build_unsigned_internal_test_installer; result=build_unsigned_internal_test_installer(project_root=Path('.'), staging_directory=Path(r'%STAGING_DIR%'), output_directory=Path(r'%OUTPUT_DIR%'), disable_shell_integration=True); print(result.installer_path); print(result.manifest_path)"
exit /b %ERRORLEVEL%
