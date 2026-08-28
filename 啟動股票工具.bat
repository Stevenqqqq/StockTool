@echo off
setlocal

cd /d "%~dp0"

if not exist "%~dp0StockTool.exe" (
    echo ERROR: StockTool.exe not found in %~dp0
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = @(8501, 8502); foreach ($port in $ports) { try { $response = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:' + $port + '/_stcore/health') -TimeoutSec 1; if ($response.Content -match 'ok') { Start-Process ('http://localhost:' + $port); exit 0 } } catch {} }; exit 1"
if %ERRORLEVEL%==0 exit /b 0

start "" "%~dp0StockTool.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = @(8501, 8502); $opened = $false; for ($i = 0; $i -lt 45 -and -not $opened; $i++) { foreach ($port in $ports) { try { $response = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:' + $port + '/_stcore/health') -TimeoutSec 1; if ($response.Content -match 'ok') { Start-Process ('http://localhost:' + $port); $opened = $true; break } } catch {} } Start-Sleep -Seconds 1 }; if (-not $opened) { Start-Process 'http://localhost:8501' }"

endlocal
