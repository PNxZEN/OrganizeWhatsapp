@echo off
title WhatsApp Media Gallery
cd /d "%~dp0"

:: Set clean environment prioritizing Python 3.13 and venv
set "PATH=%~dp0venv\Scripts;C:\Python313;C:\Python313\Scripts;%SystemRoot%\system32;%SystemRoot%;%PATH%"

:: Determine onboarding state
set "IS_FIRST_LAUNCH=0"
if not exist "%~dp0config.json" (
    set "IS_FIRST_LAUNCH=1"
) else (
    findstr /i /c:"\"onboarding_completed\": true" "%~dp0config.json" >nul 2>&1
    if errorlevel 1 set "IS_FIRST_LAUNCH=1"
)

:: If server is already running, avoid duplicate processes and simply open browser
curl.exe -s -m 1 http://127.0.0.1:8000/api/health >nul 2>&1
if %errorlevel% equ 0 (
    if "%IS_FIRST_LAUNCH%"=="1" (
        start "" "http://127.0.0.1:8000/gallery.html?onboarding=1"
    ) else (
        start "" "http://127.0.0.1:8000/gallery.html"
    )
    exit /b 0
)

:: Ensure venv exists
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in .\venv
    echo Please ensure Python virtual environment is installed.
    pause
    exit /b 1
)

:: Welcome banner for first-time launch
if "%IS_FIRST_LAUNCH%"=="1" (
    echo ==============================================================================
    echo                 WhatsApp Media Organizer - Welcome
    echo ==============================================================================
    echo  First-time setup detected.
    echo  Opening the interactive setup guide in your browser...
    echo ==============================================================================
    echo.
)

:: Launch gallery server and auto-open browser
start "WhatsApp Gallery Server" "%~dp0venv\Scripts\python.exe" "%~dp0wa_media_organizer.py" --serve --auto-open
