@echo off
title JARVIS - Sci-Fi HUD Voice Assistant
cd /d C:\jarvis-local
call .venv\Scripts\activate.bat
python jarvis_wake.py
if errorlevel 1 (
    echo.
    echo Jarvis exited with an error.
    pause
)