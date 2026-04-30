@echo off
setlocal
cd /d "%~dp0"
title Build Chinese Input Helper EXE

set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PY_CMD=py"
if "%PY_CMD%"=="" (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 set "PY_CMD=python"
)
if "%PY_CMD%"=="" (
    echo [ERROR] Python was not found.
    pause
    exit /b 1
)

%PY_CMD% -m pip install pyinstaller pystray pillow
%PY_CMD% -m PyInstaller --noconfirm --onefile --windowed --name ChineseInputHelper chinese_input_helper_deepseek_ai.py

echo.
echo Build finished. Check the dist folder.
pause
endlocal
