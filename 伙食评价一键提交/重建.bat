@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  一键重建（清缓存构建 + 强制重建容器）
echo ============================================
echo.
echo [1/3] 构建镜像...
docker compose -f docker-compose.lan.yml build --no-cache
if errorlevel 1 (
  echo.
  echo [X] 构建失败，看上面的报错
  pause
  exit /b 1
)
echo.
echo [2/3] 重建容器...
docker compose -f docker-compose.lan.yml up -d --force-recreate
echo.
echo [3/3] 验证版本...
timeout /t 2 >nul
docker exec hqhs-eval grep VERSION /app/web/server.py
echo.
echo ============================================
echo  完成。刷新浏览器看标题旁的版本号
echo ============================================
pause
