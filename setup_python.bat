@echo off
echo ==========================================
echo   GSuite CLI - Simple Setup for Windows
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed!
    echo.
    echo Please install Python 3.10 or newer from the Microsoft Store or python.org.
    echo.
    echo Trying to open Microsoft Store page for Python...
    start ms-windows-store://pdp/?ProductId=9PJPW5LDXLZ5
    pause
    exit /b
)

echo Python found. Setting up virtual environment...
if not exist "venv" (
    python -m venv venv
    echo Virtual environment created.
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt
pip install -e .

echo.
echo ==========================================
echo   Setup Complete!
echo ==========================================
echo.
echo Type 'hermes welcome' to start.
echo.
cmd /k
