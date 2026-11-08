@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  预演（只登录和算分，不会真的提交）
echo ========================================
python scripts\hqhs_batch.py -a accounts.json --dry-run
echo.
pause
