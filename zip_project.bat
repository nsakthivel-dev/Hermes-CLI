@echo off
setlocal
echo ==========================================================
echo Starting Hermes-CLI Project Packaging...
echo ==========================================================

python "%~dp0zip_project.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] An error occurred during packaging.
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause
