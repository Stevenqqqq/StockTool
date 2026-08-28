@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "RELEASE_DIR=release\StockTool"
set "STAGING_DIR=release\staging\StockTool"

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found: %PYTHON%
    exit /b 1
)

if not exist "%STAGING_DIR%\StockTool.exe" (
    echo ERROR: Staging EXE not found: %STAGING_DIR%\StockTool.exe
    echo Run build_exe.bat and complete release verification first.
    exit /b 1
)

if not exist "%RELEASE_DIR%\StockTool.exe" (
    echo ERROR: Formal release EXE not found: %RELEASE_DIR%\StockTool.exe
    echo Promotion was not run because there is no formal release to preserve.
    exit /b 1
)

for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd-HHmmss')"') do set "STAMP=%%I"
if "%STAMP%"=="" (
    echo ERROR: Could not create a release timestamp. Promotion was not run.
    exit /b 1
)

set "ROLLBACK_DIR=release\rollback\StockTool-pre-sprint12-release-%STAMP%"
set "PROMOTION_HOLD=release\promotion-hold\StockTool-pre-sprint12-release-%STAMP%"

if exist "%ROLLBACK_DIR%" (
    echo ERROR: Rollback destination already exists: %ROLLBACK_DIR%
    echo Promotion was not run and no existing backup was overwritten.
    exit /b 1
)

if exist "%PROMOTION_HOLD%" (
    echo ERROR: Promotion hold destination already exists: %PROMOTION_HOLD%
    echo Promotion was not run and no existing backup was overwritten.
    exit /b 1
)

echo Validating required public assets in staging before promotion...
"%PYTHON%" -c "from pathlib import Path; from stock_tool.release_assets import validate_release_distribution; validate_release_distribution(Path(r'%STAGING_DIR%'))"
if errorlevel 1 (
    echo ERROR: Staging release is missing a required public asset. Promotion was not run.
    exit /b 1
)

echo Validating required public assets in the current formal release...
"%PYTHON%" -c "from pathlib import Path; from stock_tool.release_assets import validate_release_distribution; validate_release_distribution(Path(r'%RELEASE_DIR%'))"
if errorlevel 1 (
    echo ERROR: Formal release is missing a required public asset. Promotion was not run.
    exit /b 1
)

for /f %%I in ('%PYTHON% scripts\print_file_sha256.py "%RELEASE_DIR%\StockTool.exe"') do set "FORMAL_HASH=%%I"
for /f %%I in ('%PYTHON% scripts\print_file_sha256.py "%STAGING_DIR%\StockTool.exe"') do set "STAGING_HASH=%%I"
if "%FORMAL_HASH%"=="" (
    echo ERROR: Could not calculate the current formal EXE hash. Promotion was not run.
    exit /b 1
)
if "%STAGING_HASH%"=="" (
    echo ERROR: Could not calculate the staging EXE hash. Promotion was not run.
    exit /b 1
)

echo Creating rollback-first backup: %ROLLBACK_DIR%
robocopy "%RELEASE_DIR%" "%ROLLBACK_DIR%" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 >nul
set "ROBOCOPY_EXIT=%ERRORLEVEL%"
if %ROBOCOPY_EXIT% GEQ 8 (
    echo ERROR: Rollback backup copy failed with robocopy exit code %ROBOCOPY_EXIT%.
    echo Promotion was not run.
    exit /b 1
)

echo Verifying rollback backup assets and executable hash...
"%PYTHON%" -c "from pathlib import Path; from stock_tool.release_assets import validate_release_distribution; validate_release_distribution(Path(r'%ROLLBACK_DIR%'))"
if errorlevel 1 (
    echo ERROR: Rollback backup is incomplete. Promotion was not run.
    exit /b 1
)
for /f %%I in ('%PYTHON% scripts\print_file_sha256.py "%ROLLBACK_DIR%\StockTool.exe"') do set "ROLLBACK_HASH=%%I"
if /I not "%FORMAL_HASH%"=="%ROLLBACK_HASH%" (
    echo ERROR: Rollback EXE hash does not match the current formal EXE. Promotion was not run.
    exit /b 1
)

echo Safely migrating legacy release user data before promotion...
"%PYTHON%" -c "from pathlib import Path; from stock_tool.runtime_paths import prepare_release_user_data_migration; result = prepare_release_user_data_migration(legacy_root=Path(r'%RELEASE_DIR%')); print(f'Legacy user-data manifest: {result.manifest_path}')"
if errorlevel 1 (
    echo ERROR: Legacy user-data migration failed, was invalid, or could not be validated. Promotion was not run.
    exit /b 1
)

if not exist "release\promotion-hold" mkdir "release\promotion-hold"
if errorlevel 1 (
    echo ERROR: Could not create the promotion hold directory. Promotion was not run.
    exit /b 1
)

echo Moving current formal release to a non-destructive promotion hold...
move "%RELEASE_DIR%" "%PROMOTION_HOLD%"
if errorlevel 1 (
    echo ERROR: Could not move the current formal release into the promotion hold.
    echo The rollback backup remains available and promotion was not run.
    exit /b 1
)

echo Promoting the verified staging release...
move "%STAGING_DIR%" "%RELEASE_DIR%"
if errorlevel 1 (
    echo ERROR: Could not promote staging. Restoring the original formal release.
    move "%PROMOTION_HOLD%" "%RELEASE_DIR%"
    exit /b 1
)

echo Validating required public assets after promotion...
"%PYTHON%" -c "from pathlib import Path; from stock_tool.release_assets import validate_release_distribution; validate_release_distribution(Path(r'%RELEASE_DIR%'))"
if errorlevel 1 goto :restore_previous_release

for /f %%I in ('%PYTHON% scripts\print_file_sha256.py "%RELEASE_DIR%\StockTool.exe"') do set "PROMOTED_HASH=%%I"
if /I not "%STAGING_HASH%"=="%PROMOTED_HASH%" goto :restore_previous_release

call :run_post_promotion_smoke
if errorlevel 1 goto :restore_previous_release

echo Release promotion completed:
echo Formal EXE: %CD%\%RELEASE_DIR%\StockTool.exe
echo Formal SHA-256: %PROMOTED_HASH%
echo Rollback backup: %CD%\%ROLLBACK_DIR%
exit /b 0

:restore_previous_release
echo ERROR: Promotion validation failed. Restoring the original formal release.
if exist "%RELEASE_DIR%\StockTool.exe" (
    if exist "%STAGING_DIR%" (
        echo ERROR: Cannot preserve the failed candidate because staging already exists.
        echo The original formal release remains in %PROMOTION_HOLD%.
        exit /b 1
    )
    move "%RELEASE_DIR%" "%STAGING_DIR%"
    if errorlevel 1 (
        echo ERROR: Could not move the failed candidate back to staging.
        echo The original formal release remains in %PROMOTION_HOLD%.
        exit /b 1
    )
)
if not exist "%PROMOTION_HOLD%\StockTool.exe" (
    echo ERROR: Promotion hold is missing. Manual recovery from %ROLLBACK_DIR% is required.
    exit /b 1
)
move "%PROMOTION_HOLD%" "%RELEASE_DIR%"
if errorlevel 1 (
    echo ERROR: Automatic restoration failed. Manual recovery from %ROLLBACK_DIR% is required.
    exit /b 1
)
"%PYTHON%" -c "from pathlib import Path; from stock_tool.release_assets import validate_release_distribution; validate_release_distribution(Path(r'%RELEASE_DIR%'))"
if errorlevel 1 (
    echo ERROR: Restored release did not pass public asset validation. Manual recovery from %ROLLBACK_DIR% is required.
    exit /b 1
)
echo Original formal release restored.
exit /b 1

:run_post_promotion_smoke
set "SMOKE_RUNTIME=%TEMP%\stocktool-publish-smoke-%STAMP%"
set "SMOKE_PID="
if exist "%SMOKE_RUNTIME%" (
    echo ERROR: Isolated smoke runtime already exists: %SMOKE_RUNTIME%
    exit /b 1
)
mkdir "%SMOKE_RUNTIME%"
if errorlevel 1 exit /b 1

for /f %%I in ('powershell -NoProfile -Command "$env:STOCK_TOOL_USER_DATA_DIR='%SMOKE_RUNTIME%'; $env:BROWSER='false'; (Start-Process -FilePath '%RELEASE_DIR%\StockTool.exe' -PassThru).Id"') do set "SMOKE_PID=%%I"
if "%SMOKE_PID%"=="" goto :smoke_failure

setlocal EnableDelayedExpansion
set "SMOKE_OK=0"
for /l %%I in (1,1,90) do (
    curl.exe --noproxy "*" --silent --show-error --max-time 2 http://localhost:8501/_stcore/health | findstr /r /x "ok" >nul
    if not errorlevel 1 set "SMOKE_OK=1"
    if "!SMOKE_OK!"=="1" goto :smoke_ready
    timeout /t 1 >nul
)
:smoke_ready
endlocal & set "SMOKE_OK=%SMOKE_OK%"
if not "%SMOKE_OK%"=="1" goto :smoke_failure

curl.exe --noproxy "*" --silent --show-error --max-time 5 -o nul -w "%%{http_code}" http://localhost:8501/ | findstr /r /x "200" >nul
if errorlevel 1 goto :smoke_failure

powershell -NoProfile -Command "$root=[IO.Path]::GetFullPath('%SMOKE_RUNTIME%'); foreach($relative in 'reports','logs','data\cache'){ $path=Join-Path $root $relative; [IO.Directory]::CreateDirectory($path)|Out-Null; [IO.File]::WriteAllText((Join-Path $path 'publish_smoke_probe.txt'),'ok') }"
if errorlevel 1 goto :smoke_failure

call :stop_smoke_process
powershell -NoProfile -Command "$listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8501,8502 }); if($listeners.Count -ne 0){ exit 1 }"
if errorlevel 1 goto :smoke_cleanup_failure
powershell -NoProfile -Command "if(Test-Path -LiteralPath '%SMOKE_RUNTIME%'){[IO.Directory]::Delete('%SMOKE_RUNTIME%',$true)}"
if errorlevel 1 exit /b 1
exit /b 0

:smoke_failure
call :stop_smoke_process
:smoke_cleanup_failure
powershell -NoProfile -Command "if(Test-Path -LiteralPath '%SMOKE_RUNTIME%'){[IO.Directory]::Delete('%SMOKE_RUNTIME%',$true)}"
exit /b 1

:stop_smoke_process
if not "%SMOKE_PID%"=="" taskkill /PID %SMOKE_PID% /T /F >nul 2>nul
timeout /t 2 >nul
exit /b 0
