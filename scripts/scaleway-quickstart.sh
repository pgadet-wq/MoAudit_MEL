#!/bin/bash
# ===========================================
# MoAudit MEL - Scaleway Quick Start
# ===========================================
# This script automates the initial setup on a Scaleway instance
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/MoAudit_MEL/main/scripts/scaleway-quickstart.sh | bash
#
# Or after cloning:
#   chmod +x scripts/scaleway-quickstart.sh
#   ./scripts/scaleway-quickstart.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================="
echo "   MoAudit MEL - Scaleway Quick Start"
echo "============================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log_error "Please run as root (sudo)"
    exit 1
fi

# Check instance type
HAS_GPU=false
if command -v nvidia-smi &> /dev/null; then
    if nvidia-smi &> /dev/null; then
        HAS_GPU=true
        log_info "GPU detected - will setup Granite-Docling"
    fi
fi

# Update system
log_info "Updating system packages..."
apt update && apt upgrade -y

# Install Docker
log_info "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    log_info "Docker already installed"
fi

# Install Docker Compose plugin
log_info "Installing Docker Compose..."
apt install -y docker-compose-plugin

# Verify Docker
docker --version
docker compose version

# For GPU instances
if [ "$HAS_GPU" = true ]; then
    log_info "Setting up NVIDIA Container Toolkit..."

    # Add NVIDIA repository
    distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

    apt update
    apt install -y nvidia-container-toolkit

    # Configure Docker for NVIDIA
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker

    # Verify GPU
    log_info "Verifying GPU setup..."
    docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
fi

# Install useful tools
log_info "Installing additional tools..."
apt install -y git curl jq htop

# Setup project directory
PROJECT_DIR="/opt/moaudit"
log_info "Setting up project directory at $PROJECT_DIR..."

if [ -d "$PROJECT_DIR" ]; then
    log_warning "Project directory exists. Pulling latest changes..."
    cd "$PROJECT_DIR"
    git pull || true
else
    log_info "Cloning repository..."
    # Replace with your repository URL
    read -p "Enter your Git repository URL: " REPO_URL
    git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# Setup environment
if [ ! -f ".env" ]; then
    log_info "Creating .env file from template..."
    cp .env.example .env

    # Generate secrets
    JWT_SECRET=$(openssl rand -base64 32)
    API_KEY=$(openssl rand -hex 24)

    # Update .env with generated secrets
    sed -i "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|" .env
    sed -i "s|MOAUDIT_API_KEY=.*|MOAUDIT_API_KEY=$API_KEY|" .env

    log_warning "Please edit .env to configure your deployment:"
    echo "  nano $PROJECT_DIR/.env"
    echo ""
    echo "Key settings to configure:"
    echo "  - GRANITE_SERVICE_URL (your GPU instance IP)"
    echo "  - S3_ACCESS_KEY / S3_SECRET_KEY (Scaleway credentials)"
    echo "  - S3_BUCKET_NAME (your bucket name)"
fi

# Create data directories
mkdir -p data outputs nginx/ssl

# For GPU instance: deploy Granite-Docling
if [ "$HAS_GPU" = true ]; then
    log_info "Setting up Granite-Docling VLM..."

    GRANITE_DIR="/opt/granite-docling"
    mkdir -p "$GRANITE_DIR"
    cp services/granite-docling/docker-compose.gpu.yml "$GRANITE_DIR/"

    log_info "Starting Granite-Docling..."
    cd "$GRANITE_DIR"
    docker compose -f docker-compose.gpu.yml up -d

    log_info "Waiting for model to load (this may take 2-5 minutes)..."
    sleep 30

    # Check status
    MAX_RETRIES=60
    RETRY=0
    while [ $RETRY -lt $MAX_RETRIES ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_success "Granite-Docling is ready!"
            break
        fi
        RETRY=$((RETRY + 1))
        echo -n "."
        sleep 5
    done
    echo ""

    if [ $RETRY -eq $MAX_RETRIES ]; then
        log_warning "Granite-Docling is still starting. Check logs with:"
        echo "  docker compose -f $GRANITE_DIR/docker-compose.gpu.yml logs -f"
    fi

    cd "$PROJECT_DIR"
fi

# For CPU instance: build and start services
if [ "$HAS_GPU" = false ]; then
    log_info "Building Docker images..."
    docker compose -f docker-compose.prod.yml build

    echo ""
    log_success "Setup complete!"
    echo ""
    echo "Next steps:"
    echo "1. Edit the configuration file:"
    echo "   nano $PROJECT_DIR/.env"
    echo ""
    echo "2. Update GRANITE_SERVICE_URL with your GPU instance IP"
    echo ""
    echo "3. Start the services:"
    echo "   cd $PROJECT_DIR"
    echo "   docker compose -f docker-compose.prod.yml up -d"
    echo ""
    echo "4. Check health:"
    echo "   curl http://localhost/health/deep"
fi

# Summary
echo ""
echo "============================================="
echo "   Setup Summary"
echo "============================================="
echo "Project directory: $PROJECT_DIR"
echo "GPU detected: $HAS_GPU"
echo ""
if [ "$HAS_GPU" = true ]; then
    echo "Granite-Docling status:"
    docker ps --filter "name=granite-docling" --format "table {{.Names}}\t{{.Status}}"
    echo ""
    echo "GPU IP for other instances: $(curl -s ifconfig.me)"
fi
echo ""
echo "Documentation: $PROJECT_DIR/docs/SCALEWAY_DEPLOYMENT.md"
