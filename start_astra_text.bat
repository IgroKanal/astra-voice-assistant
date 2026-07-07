@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\Activate.bat" call ".venv\Scripts\Activate.bat"
python main.py --text
pause
