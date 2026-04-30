@echo off
setlocal
cd /d "%~dp0"
title Chinese Input Helper Launcher

echo ========================================
echo  Chinese Input Helper v7.6.4
echo  Safe launcher - ASCII only
echo  Hotkey: Ctrl + Shift + Z
echo  Logs: translation provider success enabled
echo ========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYCMD=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYCMD=python"
    ) else (
        echo Python was not found.
        echo Please install Python 3 first.
        pause
        exit /b 1
    )
)

echo Python command: %PYCMD%
echo Checking dependencies...
%PYCMD% -c "import pystray, PIL" >nul 2>nul
if not %errorlevel%==0 (
    echo Installing dependencies: pystray pillow
    %PYCMD% -m pip install pystray pillow
)

echo Starting app...
echo ========================================
%PYCMD% chinese_input_helper_deepseek_ai.py

echo.
echo App exited. Press any key to close.
pause >nul
