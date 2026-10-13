@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在准备公考与求职日历，请稍候……
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo 安装未完成，请检查网络后重新双击本文件。
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
