@echo off
title JARVIS - Push To Talk (F8)
cd /d C:\jarvis-local
call .venv\Scripts\activate.bat
python jarvis_voice_ptt.py
if errorlevel 1 (
    echo.
    echo Jarvis PTT exited with an error.
    pause
)
