@echo off
chcp 65001 >nul
cd /d "%~dp0"
python build_exe.py
if errorlevel 1 (
  echo 打包失败。
  pause
  exit /b 1
)
echo.
echo 打包完成：dist\公考求职日历.exe
pause
