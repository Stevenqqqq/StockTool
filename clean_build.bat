@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo Removing build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist release\staging rmdir /s /q release\staging

echo Staging clean complete. The official release\StockTool folder was preserved.
exit /b 0
