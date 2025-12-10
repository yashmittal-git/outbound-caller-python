FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install LiveKit CLI (lk)
# Try the install script first, fallback to manual installation
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi && \
    VERSION=$(curl -s https://api.github.com/repos/livekit/livekit-cli/releases/latest | grep -oP '"tag_name": "v\K([^"]*)' || echo "1.0.0") && \
    wget -q https://github.com/livekit/livekit-cli/releases/download/v${VERSION}/livekit-cli_${VERSION}_linux_${ARCH}.tar.gz -O /tmp/lk.tar.gz && \
    tar -xzf /tmp/lk.tar.gz -C /tmp && \
    mv /tmp/lk /usr/local/bin/lk && \
    chmod +x /usr/local/bin/lk && \
    rm -f /tmp/lk.tar.gz && \
    lk --version || echo "lk CLI installed but version check failed"

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Download required model files
# This downloads turn detector models and other plugin files
# The agent will fallback to "stt" mode if turn detector files aren't available
RUN python agent.py download-files 2>&1 | tee /tmp/download-files.log || \
    (echo "Warning: download-files had issues. Check /tmp/download-files.log. Agent will use fallback turn detection." && true)

# Expose ports
# 5000 for Flask API server
# 8080 for agent (if needed)
EXPOSE 5000 8080

# Default command (can be overridden in docker-compose)
CMD ["python", "api_server.py"]
