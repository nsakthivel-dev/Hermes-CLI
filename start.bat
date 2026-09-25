@echo off
REM GSuite CLI - Windows Hackathon Deployment Script
REM This script helps deploy the CLI quickly on Windows

echo.
echo 🚀 GSuite CLI - Windows Hackathon Deployment
echo =====================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker is not installed!
    echo.
    echo Please install Docker Desktop for Windows:
    echo 1. Download from: https://www.docker.com/products/docker-desktop
    echo 2. Install and restart Docker Desktop
    echo 3. Run this script again
    echo.
    pause
    exit /b 1
)

REM Check if Docker Compose is available
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker Compose is not available!
    echo.
    echo Docker Compose should be included with Docker Desktop.
    echo Please ensure Docker Desktop is running properly.
    echo.
    pause
    exit /b 1
)

echo ✅ Docker and Docker Compose are installed
echo.

REM Create necessary directories
echo 📁 Creating necessary directories...
if not exist "config" mkdir config
if not exist "cache" mkdir cache
if not exist "data" mkdir data
echo ✅ Directories created: config\, cache\, data\
echo.

REM Check for credentials
echo 🔑 Checking for Google credentials...
if not exist "config\credentials.json" (
    echo ❌ credentials.json not found!
    echo.
    echo Please add your Google OAuth credentials to: config\credentials.json
    echo.
    echo The file should look like this:
    echo {
    echo   "installed": {
    echo     "client_id": "your-client-id.apps.googleusercontent.com",
    echo     "client_secret": "your-client-secret",
    echo     "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    echo     "token_uri": "https://oauth2.googleapis.com/token"
    echo   }
    echo }
    echo.
    echo Get credentials from: https://console.cloud.google.com/
    echo.
    pause
    exit /b 1
)

echo ✅ credentials.json found
echo.

REM Build and start Docker containers
echo 🐳 Building Docker image...
docker-compose build
if %errorlevel% neq 0 (
    echo ❌ Failed to build Docker image
    pause
    exit /b 1
)

echo ✅ Docker image built successfully
echo.

echo 🚀 Starting containers...
docker-compose up -d
if %errorlevel% neq 0 (
    echo ❌ Failed to start containers
    pause
    exit /b 1
)

echo ✅ Containers started successfully
echo.

REM Wait for containers to be ready
echo ⏳ Waiting for containers to be ready...
timeout /t 5 /nobreak >nul

REM Check if container is running
docker-compose ps | findstr "Up" >nul
if %errorlevel% neq 0 (
    echo ❌ Container failed to start
    echo Showing logs:
    docker-compose logs
    pause
    exit /b 1
)

echo ✅ Container is running
echo.

REM Test the CLI
echo 🧪 Testing GSuite CLI...
docker-compose exec -T gsuite-cli hermes --help >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ CLI test failed
    echo Showing logs:
    docker-compose logs gsuite-cli
    pause
    exit /b 1
)

echo ✅ CLI is working
echo.

echo.
echo 🎉 GSuite CLI is ready for the hackathon!
echo.
echo 🎯 Demo Commands:
echo   docker-compose exec gsuite-cli hermes welcome
echo   docker-compose exec gsuite-cli hermes ai ask "show my calendar"
echo   docker-compose exec gsuite-cli hermes docs templates
echo   docker-compose exec gsuite-cli hermes calendar insights
echo   docker-compose exec gsuite-cli hermes interactive
echo.
echo 🔧 Management Commands:
echo   docker-compose logs -f gsuite-cli    ^| View logs
echo   docker-compose ps                   ^| Check status
echo   docker-compose exec gsuite-cli bash ^| Enter container
echo   docker-compose down                 ^| Stop services
echo.
echo 📝 Quick Start:
echo   1. Open Command Prompt or PowerShell as Administrator
echo   2. Navigate to this directory
echo   3. Run: start.bat
echo   4. Use the demo commands above
echo.
echo ℹ️  Good luck at the hackathon! 🚀
echo.
pause
