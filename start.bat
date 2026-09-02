@echo off
chcp 65001 >nul 2>&1
title Night Wardrobe
cd /d "%~dp0"

echo ============================================
echo   Night Wardrobe - Startup
echo ============================================
echo.
echo [INFO] Working directory: %cd%

set VENV=tag_manager\.venv
set PY=%VENV%\Scripts\python.exe
set PIP=%VENV%\Scripts\pip.exe

if not exist "%VENV%" (
    echo [SETUP] Virtual environment not found, creating...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Is Python 3.10+ installed?
        echo [ERROR] Try running: python --version
        pause
        exit /b 1
    )
    echo [SETUP] Virtual environment created at %VENV%
) else (
    echo [INFO] Virtual environment found at %VENV%
)

echo [INFO] Python: %PY%
"%PY%" --version

echo [INFO] Checking dependencies...
"%PIP%" install -r tag_manager\requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo [ERROR] Check your network connection or requirements.txt
    pause
    exit /b 1
)
echo [INFO] Dependencies OK.

echo.
echo [INFO] Database: tag_manager\tag_wardrobe.sqlite3
if exist "tag_manager\tag_wardrobe.sqlite3" (
    echo [INFO] Database exists.
) else (
    echo [INFO] Database not found, will be created on first run.
)

echo.
echo ============================================
echo   Server starting at http://127.0.0.1:8765
echo   Press Ctrl+C to stop.
echo ============================================
echo.
start "" http://127.0.0.1:8765
"%PY%" -m tag_manager.run
echo.
echo [INFO] Server stopped.
pause
