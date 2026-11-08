@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  安装依赖（只需要做一次）
echo ========================================
python --version >nul 2>&1
if errorlevel 1 (
  echo [X] 没找到 Python。请先去 https://www.python.org/downloads/ 安装，
  echo     安装时务必勾选 "Add Python to PATH"。
  pause
  exit /b 1
)
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests cryptography pyyaml
echo.
echo [OK] 安装完成。下一步：双击 2-导入名单.bat
pause
