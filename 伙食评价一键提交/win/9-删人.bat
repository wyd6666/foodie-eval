@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo 当前名单：
python scripts\manage_accounts.py list
echo.
set /p WHO=要删除谁的姓名或账号（多个用逗号隔开）:
if "%WHO%"=="" (
  echo 没输入，取消。
  pause
  exit /b 0
)
python scripts\manage_accounts.py del "%WHO%"
echo.
echo 删错了不要紧：accounts.json.bak 是删除前的备份，改个名字复制回去就恢复了。
pause
