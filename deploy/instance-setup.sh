#!/bin/bash
# =============================================================================
# MoAudit_MEL - Instance Setup Script
# =============================================================================
# Run this script on a fresh Scaleway Ubuntu instance to set up the application
#
# Usage (on the instance):
#   curl -sSL <raw-github-url>/deploy/instance-setup.sh | bash
# Or:
#   wget -O - <raw-github-url>/deploy/instance-setup.sh | bash
# =============================================================================

set -e

echo "=============================================="
echo "  MoAudit_MEL - Instance Setup"
echo "=============================================="

# Update system
echo "[1/6] Updating system packages..."
apt-get update && apt-get upgrade -y

# Install Docker
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Install Docker Compose
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    apt-get install -y docker-compose-plugin
fi

# Install useful tools
echo "[4/6] Installing utilities..."
apt-get install -y git curl jq htop

# Create application directory
echo "[5/6] Setting up application directory..."
APP_DIR="/opt/moaudit"
mkdir -p ${APP_DIR}
cd ${APP_DIR}

# Clone repository (or copy files)
echo "[6/6] Cloning application..."
if [ -d ".git" ]; then
    git pull
else
    # Replace with your actual repository URL
    echo "Please clone your repository manually:"
    echo "  git clone <your-repo-url> ${APP_DIR}"
    echo ""
    echo "Or copy the files manually."
fi

echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Navigate to the app directory:"
echo "   cd ${APP_DIR}"
echo ""
echo "2. Create your environment file:"
echo "   cp .env.example .env"
echo "   nano .env  # Add your MISTRAL_API_KEY"
echo ""
echo "3. Start the application:"
echo "   docker compose up -d"
echo ""
echo "4. Check logs:"
echo "   docker compose logs -f"
echo ""
echo "5. Access the application:"
echo "   http://<your-instance-ip>:8080"
echo ""
echo "Useful commands:"
echo "  docker compose ps      # Check status"
echo "  docker compose logs    # View logs"
echo "  docker compose down    # Stop"
echo "  docker compose restart # Restart"
echo ""
