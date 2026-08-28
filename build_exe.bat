@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "RELEASE_PARENT=release"
set "RELEASE_DIR=release\StockTool"
set "STAGING_PARENT=release\staging"
set "STAGING_DIR=release\staging\StockTool"
if not "%STOCK_TOOL_STAGING_PARENT%"=="" (
    set "STAGING_PARENT=%STOCK_TOOL_STAGING_PARENT%"
    set "STAGING_DIR=!STAGING_PARENT!\StockTool"
)

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found: %PYTHON%
    echo Create it first with: py -3.11 -m venv .venv
    exit /b 1
)

echo Validating required public release source assets...
"%PYTHON%" -m stock_tool.release_assets --validate-source
if errorlevel 1 exit /b 1

echo Installing project build dependencies...
"%PYTHON%" -m pip install --constraint "requirements\stocktool-runtime-constraints.txt" -e ".[dev]"
if errorlevel 1 exit /b 1

echo Stopping any running StockTool.exe from previous builds...
taskkill /IM StockTool.exe /F /T >nul 2>nul
"%PYTHON%" -c "import time; time.sleep(2)"

echo Cleaning previous staging build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%STAGING_PARENT%" rmdir /s /q "%STAGING_PARENT%"

echo Building versioned StockTool payload with PyInstaller onedir...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --distpath "%STAGING_PARENT%\payload-build" ^
    --workpath "build\pyinstaller" ^
    StockTool.spec
if errorlevel 1 exit /b 1

echo Building stable StockTool.exe authority entry...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --distpath "%STAGING_DIR%" ^
    --workpath "build\stable-launcher" ^
    StableLauncher.spec
if errorlevel 1 exit /b 1

if not exist "%STAGING_PARENT%\payload-build\StockToolPayload\StockToolPayload.exe" (
    echo ERROR: versioned payload build output is missing.
    exit /b 1
)

move /y "%STAGING_PARENT%\payload-build\StockToolPayload" "%STAGING_DIR%\Payload" >nul
if errorlevel 1 exit /b 1

echo Copying allowlisted public assets to staging...
if not exist "%STAGING_DIR%" (
    echo ERROR: PyInstaller staging output folder not found: %STAGING_DIR%
    exit /b 1
)

"%PYTHON%" -m stock_tool.release_assets --copy-payload-and-validate "%STAGING_DIR%\Payload"
if errorlevel 1 exit /b 1

echo Creating verified side-by-side payload copy for stable-entry smoke testing...
"%PYTHON%" -c "from stock_tool import __version__; print(__version__)" > "build\canonical-version.txt"
if errorlevel 1 exit /b 1
set /p CANONICAL_VERSION=<"build\canonical-version.txt"
if "%CANONICAL_VERSION%"=="" (
    echo ERROR: Canonical package version is missing.
    exit /b 1
)
"%PYTHON%" -c "from pathlib import Path; import shutil, sys; stage=Path(sys.argv[1]); version=sys.argv[2]; source=stage/'Payload'; target=stage/'versions'/version; shutil.copytree(source, target, dirs_exist_ok=False)" "%STAGING_DIR%" "%CANONICAL_VERSION%"
if errorlevel 1 exit /b 1
"%STAGING_DIR%\StockTool.exe" --activate-version "%CANONICAL_VERSION%"
if errorlevel 1 exit /b 1

echo Runtime user data is stored outside the release folder under %%LOCALAPPDATA%%\StockTool.

echo.
echo Staging build completed:
echo %CD%\%STAGING_DIR%\StockTool.exe
echo Verify the staging package, then run publish_release.bat to replace the official release.
exit /b 0
