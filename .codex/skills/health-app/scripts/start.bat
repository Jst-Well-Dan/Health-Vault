@echo off
chcp 65001 >nul
title 家庭健康档案 Web 服务

set "PROJECT_ROOT=%~dp0..\..\..\.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

if "%HEALTH_APP_PASSWORD%"=="" (
    echo 请先设置 HEALTH_APP_PASSWORD（家庭共享密码）。
    exit /b 1
)

set "HEALTH_HOST=0.0.0.0"
echo 正在启动家庭健康档案 Web 服务...
cd /d "%PROJECT_ROOT%"
call npm run start
pause
