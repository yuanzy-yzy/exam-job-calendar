@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\公考求职日历.exe" (
  start "" "dist\公考求职日历.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b 0
)
start "" pythonw "main.py"
