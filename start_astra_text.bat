@echo off
setlocal
cd /d "%~dp0"
title Astra Voice Assistant - Text Mode
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" (
    set "ASTRA_PYTHON=.venv\Scripts\python.exe"
) else (
    echo [Astra] Python not found in .venv\Scripts\python.exe
    echo [Astra] Create venv and install dependencies first.
    pause
    exit /b 1
)

if not exist "logs" mkdir logs
"%ASTRA_PYTHON%" main.py --text
pause
