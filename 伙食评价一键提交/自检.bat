@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在收集环境信息，请稍等...
echo.
python scripts\selfcheck.py %*
echo.
echo ================================================
echo  把上面整段内容复制发给维护者
echo ================================================
pause
