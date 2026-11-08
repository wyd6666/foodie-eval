@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  往名单里加人（可以一次加多个）
echo ========================================
echo 格式： 姓名 账号 密码      （三者之间用空格隔开）
echo 加完一个人按回车继续，直接再回车结束
echo.
python scripts\manage_accounts.py add
echo.
pause
