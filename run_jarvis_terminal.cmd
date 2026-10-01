@echo off
title JARVIS - Interactive Terminal
cd /d C:\jarvis-local
call .venv\Scripts\activate.bat
python jarvis.py
if errorlevel 1 (
    echo.
    echo Jarvis Terminal exited with an error.
    pause
)
