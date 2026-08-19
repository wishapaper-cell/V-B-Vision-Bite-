@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 健康饮食 v2

echo.
echo   正在启动健康饮食 v2，请稍候...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"

if errorlevel 1 (
    echo.
    echo   应用启动失败，请检查项目文件是否完整。
    echo.
    pause
)
