@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set /p FILE=名单文件名（直接回车用 账号密码.txt）:
if "%FILE%"=="" set FILE=账号密码.txt
python scripts\import_accounts.py "%FILE%" --check
pause
