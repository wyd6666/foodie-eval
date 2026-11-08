@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo  伙食评价 · 网页版
echo  浏览器会自动打开 http://127.0.0.1:8080
echo  用完直接关掉这个窗口即可
echo ========================================
start /b python web\server.py
timeout /t 2 >nul
start "" http://127.0.0.1:8080
echo.
echo 服务运行中...（关掉本窗口 = 停止服务）
pause >nul
