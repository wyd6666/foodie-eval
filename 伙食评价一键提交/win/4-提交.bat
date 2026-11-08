@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  真的提交（每人一次）
echo ========================================
echo 确认名单和服务器地址都没问题？按任意键开始，Ctrl+C 取消。
pause >nul
python scripts\hqhs_batch.py -a accounts.json
echo.
pause
