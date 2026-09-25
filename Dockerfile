# GSuite CLI - Docker Deployment
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# Create necessary directories
RUN mkdir -p /app/.config/gsuite-cli /app/.cache/gsuite-cli

# Install the CLI in development mode
RUN pip install -e .

# Create entrypoint script
RUN echo '#!/bin/bash\n\
echo "🚀 GSuite CLI - Docker Container Started"\n\
echo "📊 Container Info:"\n\
echo "   - Python: $(python --version)"\n\
echo "   - GSuite CLI: $(gs --version 2>/dev/null || echo "Installed")"\n\
echo "   - Working Directory: $(pwd)"\n\
echo ""\n\
echo "🎯 Quick Start:"\n\
echo "   1. Run: gs welcome"\n\
echo "   2. Or: gs ai ask \\"show my calendar\\"" \n\
echo ""\n\
echo "⚙️  Configuration:"\n\
echo "   - Config dir: /app/.config/gsuite-cli"\n\
echo "   - Cache dir: /app/.cache/gsuite-cli"\n\
echo "   - Add your credentials.json to /app/.config/gsuite-cli/"\n\
echo ""\n\
exec "$@"' > /app/entrypoint.sh && \
chmod +x /app/entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command
CMD ["bash"]

# Expose port (if needed for future web interface)
EXPOSE 8080

# Labels
LABEL maintainer="GSuite CLI Team" \
      version="1.0.0" \
      description="AI-powered Google Workspace CLI with Docker support"
