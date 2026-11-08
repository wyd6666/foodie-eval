@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python scripts\hqhs_batch.py -a accounts.json --status
pause
