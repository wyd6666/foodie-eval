@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python scripts\manage_accounts.py list
echo.
echo 想顺便验证密码对不对？按任意键继续（需要能连上服务器）
pause >nul
python scripts\manage_accounts.py check
echo.
pause
