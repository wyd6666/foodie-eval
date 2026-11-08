@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  导入名单（账号=密码=姓名）
echo ========================================
set /p FILE=请输入名单文件名（直接回车用 账号密码.txt）:
if "%FILE%"=="" set FILE=账号密码.txt
if not exist "%FILE%" (
  echo [X] 找不到文件: %FILE%
  pause
  exit /b 1
)
python scripts\import_accounts.py "%FILE%"
echo.
echo [OK] 已生成 accounts.json。下一步：双击 3-预演.bat
pause
