@echo off
title WhatsApp Media Gallery
cd /d "%~dp0"
setlocal EnableDelayedExpansion

:: ============================================================
:: Bundled PATH: Portable runtime + ADB take priority over system
:: ============================================================
set "PATH=%~dp0runtime;%~dp0runtime\Scripts;%~dp0bin;%~dp0bin\platform-tools;%PATH%"

:: ============================================================
:: Determine onboarding state (for browser URL)
:: ============================================================
set "IS_FIRST_LAUNCH=0"
if not exist "%~dp0config.json" (
    set "IS_FIRST_LAUNCH=1"
) else (
    findstr /i /c:"\"onboarding_completed\": true" "%~dp0config.json" >nul 2>&1
    if errorlevel 1 set "IS_FIRST_LAUNCH=1"
)

:: ============================================================
:: Single-instance check: if server already running, open browser
:: ============================================================
curl.exe -s -m 1 http://127.0.0.1:8000/api/health >nul 2>&1
if %errorlevel% equ 0 (
    if "!IS_FIRST_LAUNCH!"=="1" (
        start "" "http://127.0.0.1:8000/gallery.html?onboarding=1"
    ) else (
        start "" "http://127.0.0.1:8000/gallery.html"
    )
    exit /b 0
)

:: ============================================================
:: Python Interpreter Discovery (zero-overhead, no import checks)
::   Priority 1: Bundled portable runtime (pre-installed wheels, instant launch)
::   Priority 2: Local development venv
::   Priority 3: System Python (launches directly; import errors surface naturally)
:: ============================================================
set "PYTHON_EXE="

if exist "%~dp0runtime\python.exe" (
    set "PYTHON_EXE=%~dp0runtime\python.exe"
    set "PYTHONNOUSERSITE=1"
    goto :found_python
)

if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
    goto :found_python
)

where python.exe >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python.exe"
    goto :found_python
)

where py.exe >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py.exe"
    goto :found_python
)

echo [ERROR] Python not found.
echo.
echo  No Python interpreter was found in:
echo    - %~dp0runtime\  (Portable embedded runtime)
echo    - %~dp0venv\     (Development virtual environment)
echo    - System PATH    (python.exe / py.exe)
echo.
echo  To fix: Download the portable ZIP from GitHub Releases (it includes Python),
echo  or install Python 3.10+ from https://www.python.org/downloads/
pause
exit /b 1

:found_python

:: ============================================================
:: Welcome banner for first-time launch
:: ============================================================
if "!IS_FIRST_LAUNCH!"=="1" (
    echo ==============================================================================
    echo              WhatsApp Media Organizer - First Launch
    echo ==============================================================================
    echo  Opening the interactive setup guide in your browser...
    echo ==============================================================================
    echo.
)

:: ============================================================
:: Launch gallery server (background) and auto-open browser
:: ============================================================
start "WhatsApp Gallery Server" "!PYTHON_EXE!" "%~dp0wa_media_organizer.py" --serve --auto-open

endlocal
