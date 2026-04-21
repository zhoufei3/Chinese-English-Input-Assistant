@echo off
cd /d "%~dp0"

echo Checking dependencies...
py -c "import pystray, PIL" 2>nul
if errorlevel 1 (
    echo Installing required packages...
    py -m pip install pystray pillow --quiet
)

py chinese_input_helper_v5.py 2>nul && goto :eof
python -m pip install pystray pillow --quiet 2>nul
python chinese_input_helper_v5.py 2>nul && goto :eof

echo Python not found. Install from https://www.python.org
pause
