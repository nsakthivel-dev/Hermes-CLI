#!/bin/bash

# GSuite CLI - Hackathon Quick Start Script
# This script helps deploy the CLI quickly for hackathon demos

set -e

echo "🚀 GSuite CLI - Hackathon Deployment"
echo "====================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed!"
        echo ""
        echo "Please install Docker first:"
        echo "  - Mac: https://docs.docker.com/docker-for-mac/install/"
        echo "  - Linux: curl -fsSL https://get.docker.com -o get-docker.sh"
        echo "  - Windows: https://docs.docker.com/docker-for-windows/install/"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed!"
        echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    fi
    
    print_status "Docker and Docker Compose are installed"
}

# Create necessary directories
create_directories() {
    print_info "Creating necessary directories..."
    
    mkdir -p config cache data
    
    print_status "Directories created: config/, cache/, data/"
}

# Check for credentials
check_credentials() {
    print_info "Checking for Google credentials..."
    
    if [ ! -f "config/credentials.json" ]; then
        print_error "credentials.json not found!"
        echo ""
        echo "Please add your Google OAuth credentials to: config/credentials.json"
        echo ""
        echo "The file should look like this:"
        echo "{"
        echo "  \"installed\": {"
        echo "    \"client_id\": \"your-client-id.apps.googleusercontent.com\","
        echo "    \"client_secret\": \"your-client-secret\","
        echo "    \"auth_uri\": \"https://accounts.google.com/o/oauth2/auth\","
        echo "    \"token_uri\": \"https://oauth2.googleapis.com/token\""
        echo "  }"
        echo "}"
        echo ""
        echo "Get credentials from: https://console.cloud.google.com/"
        exit 1
    fi
    
    print_status "credentials.json found"
}

# Build and start Docker containers
start_docker() {
    print_info "Building Docker image..."
    
    if docker-compose build; then
        print_status "Docker image built successfully"
    else
        print_error "Failed to build Docker image"
        exit 1
    fi
    
    print_info "Starting containers..."
    
    if docker-compose up -d; then
        print_status "Containers started successfully"
    else
        print_error "Failed to start containers"
        exit 1
    fi
    
    # Wait for containers to be ready
    print_info "Waiting for containers to be ready..."
    sleep 5
    
    # Check if container is running
    if docker-compose ps | grep -q "Up"; then
        print_status "Container is running"
    else
        print_error "Container failed to start"
        docker-compose logs
        exit 1
    fi
}

# Test the CLI
test_cli() {
    print_info "Testing GSuite CLI..."
    
    if docker-compose exec -T gsuite-cli hermes --help > /dev/null 2>&1; then
        print_status "CLI is working"
    else
        print_error "CLI test failed"
        docker-compose logs gsuite-cli
        exit 1
    fi
}

# Show demo commands
show_demo_commands() {
    echo ""
    print_status "🎉 GSuite CLI is ready for the hackathon!"
    echo ""
    echo "🎯 Demo Commands:"
    echo "  docker-compose exec gsuite-cli hermes welcome"
    echo "  docker-compose exec gsuite-cli hermes ai ask \"show my calendar\""
    echo "  docker-compose exec gsuite-cli hermes docs templates"
    echo "  docker-compose exec gsuite-cli hermes calendar insights"
    echo "  docker-compose exec gsuite-cli hermes interactive"
    echo ""
    echo "📊 Advanced Features:"
    echo "  docker-compose exec gsuite-cli gs calendar analytics"
    echo "  docker-compose exec gsuite-cli gs docs template meeting"
    echo "  docker-compose exec gsuite-cli gs ai summarize"
    echo ""
    echo "🔧 Management Commands:"
    echo "  docker-compose logs -f gsuite-cli    # View logs"
    echo "  docker-compose ps                   # Check status"
    echo "  docker-compose exec gsuite-cli bash # Enter container"
    echo "  docker-compose down                 # Stop services"
    echo ""
    print_info "Good luck at the hackathon! 🚀"
}

# Cleanup function
cleanup() {
    if [ $? -ne 0 ]; then
        print_error "Deployment failed!"
        echo ""
        print_info "Cleaning up..."
        docker-compose down 2>/dev/null || true
        exit 1
    fi
}

# Set up cleanup trap
trap cleanup EXIT

# Main deployment flow
main() {
    echo "Starting deployment process..."
    echo ""
    
    check_docker
    echo ""
    
    create_directories
    echo ""
    
    check_credentials
    echo ""
    
    start_docker
    echo ""
    
    test_cli
    echo ""
    
    show_demo_commands
}

# Handle script arguments
case "${1:-}" in
    "stop")
        echo "🛑 Stopping GSuite CLI..."
        docker-compose down
        print_status "Services stopped"
        ;;
    "restart")
        echo "🔄 Restarting GSuite CLI..."
        docker-compose down
        main
        ;;
    "logs")
        echo "📋 Showing logs..."
        docker-compose logs -f gsuite-cli
        ;;
    "bash")
        echo "🐚 Entering container..."
        docker-compose exec gsuite-cli bash
        ;;
    "status")
        echo "📊 Checking status..."
        docker-compose ps
        ;;
    "help"|"-h"|"--help")
        echo "GSuite CLI - Hackathon Deployment Script"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  (no args)  Deploy and start the CLI"
        echo "  stop       Stop all services"
        echo "  restart    Restart all services"
        echo "  logs       Show container logs"
        echo "  bash       Enter container shell"
        echo "  status     Show service status"
        echo "  help       Show this help"
        echo ""
        exit 0
        ;;
    *)
        main
        ;;
esac
