#!/bin/bash
# =============================================================================
# MoAudit_MEL - Scaleway Deployment Script
# =============================================================================
# This script helps deploy the application to Scaleway
#
# Prerequisites:
#   - Scaleway CLI installed: https://github.com/scaleway/scaleway-cli
#   - Docker installed
#   - Scaleway account with API keys configured
#
# Usage:
#   ./deploy/scaleway-deploy.sh [instance|container]
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="moaudit-mel"
REGISTRY_NAMESPACE="moaudit"
IMAGE_TAG="latest"
REGION="fr-par"
ZONE="fr-par-1"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Scaleway CLI
    if ! command -v scw &> /dev/null; then
        log_error "Scaleway CLI not found. Install it: https://github.com/scaleway/scaleway-cli"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Please install Docker first."
    fi

    # Check if logged in to Scaleway
    if ! scw account project list &> /dev/null; then
        log_error "Not logged in to Scaleway. Run: scw init"
    fi

    log_success "All prerequisites met!"
}

build_image() {
    log_info "Building Docker image..."
    docker build -t ${APP_NAME}:${IMAGE_TAG} .
    log_success "Image built: ${APP_NAME}:${IMAGE_TAG}"
}

# =============================================================================
# OPTION 1: Deploy to Scaleway Instance (VM)
# =============================================================================
deploy_instance() {
    log_info "Deploying to Scaleway Instance..."

    # Ask for instance type
    echo ""
    echo "Available instance types for testing:"
    echo "  1) DEV1-S  - 2 vCPU, 2GB RAM  (~€0.01/hr) - Recommended for testing"
    echo "  2) DEV1-M  - 3 vCPU, 4GB RAM  (~€0.02/hr)"
    echo "  3) DEV1-L  - 4 vCPU, 8GB RAM  (~€0.04/hr)"
    echo "  4) GP1-XS  - 4 vCPU, 16GB RAM (~€0.08/hr) - For production"
    echo "  5) GPU-3070-S - 1 GPU RTX 3070 (~€0.80/hr) - If GPU needed"
    echo ""
    read -p "Select instance type [1-5, default=1]: " INSTANCE_CHOICE

    case ${INSTANCE_CHOICE:-1} in
        1) INSTANCE_TYPE="DEV1-S" ;;
        2) INSTANCE_TYPE="DEV1-M" ;;
        3) INSTANCE_TYPE="DEV1-L" ;;
        4) INSTANCE_TYPE="GP1-XS" ;;
        5) INSTANCE_TYPE="GPU-3070-S" ;;
        *) INSTANCE_TYPE="DEV1-S" ;;
    esac

    log_info "Selected instance type: ${INSTANCE_TYPE}"

    # Create the instance
    log_info "Creating instance..."
    INSTANCE_ID=$(scw instance server create \
        type=${INSTANCE_TYPE} \
        zone=${ZONE} \
        image=ubuntu_jammy \
        name=${APP_NAME}-server \
        --output json | jq -r '.id')

    log_success "Instance created: ${INSTANCE_ID}"

    # Wait for instance to be ready
    log_info "Waiting for instance to be ready..."
    scw instance server wait ${INSTANCE_ID} zone=${ZONE}

    # Get instance IP
    INSTANCE_IP=$(scw instance server get ${INSTANCE_ID} zone=${ZONE} --output json | jq -r '.public_ip.address')

    log_success "Instance ready!"
    echo ""
    echo "=============================================="
    echo "Instance IP: ${INSTANCE_IP}"
    echo "=============================================="
    echo ""
    echo "Next steps:"
    echo "1. SSH into the instance:"
    echo "   ssh root@${INSTANCE_IP}"
    echo ""
    echo "2. Run the setup script on the instance:"
    echo "   curl -sSL https://get.docker.com | sh"
    echo "   git clone <your-repo-url> /app"
    echo "   cd /app"
    echo "   cp .env.example .env"
    echo "   # Edit .env with your MISTRAL_API_KEY"
    echo "   docker compose up -d"
    echo ""
    echo "3. Access the application:"
    echo "   http://${INSTANCE_IP}:8080"
    echo ""
}

# =============================================================================
# OPTION 2: Deploy to Scaleway Serverless Containers
# =============================================================================
deploy_container() {
    log_info "Deploying to Scaleway Serverless Containers..."

    # Create registry namespace if not exists
    log_info "Setting up Container Registry..."
    scw registry namespace create name=${REGISTRY_NAMESPACE} region=${REGION} 2>/dev/null || true

    # Get registry endpoint
    REGISTRY_ENDPOINT=$(scw registry namespace list region=${REGION} --output json | \
        jq -r ".[] | select(.name==\"${REGISTRY_NAMESPACE}\") | .endpoint")

    if [ -z "$REGISTRY_ENDPOINT" ]; then
        log_error "Failed to get registry endpoint"
    fi

    log_info "Registry endpoint: ${REGISTRY_ENDPOINT}"

    # Login to registry
    log_info "Logging in to Scaleway Container Registry..."
    scw registry login

    # Tag and push image
    FULL_IMAGE="${REGISTRY_ENDPOINT}/${APP_NAME}:${IMAGE_TAG}"
    log_info "Tagging image as ${FULL_IMAGE}..."
    docker tag ${APP_NAME}:${IMAGE_TAG} ${FULL_IMAGE}

    log_info "Pushing image to registry..."
    docker push ${FULL_IMAGE}

    log_success "Image pushed to registry!"

    # Create serverless container namespace
    log_info "Creating serverless container namespace..."
    scw container namespace create name=${APP_NAME}-ns region=${REGION} 2>/dev/null || true

    # Get namespace ID
    NAMESPACE_ID=$(scw container namespace list region=${REGION} --output json | \
        jq -r ".[] | select(.name==\"${APP_NAME}-ns\") | .id")

    # Check if MISTRAL_API_KEY is set
    if [ -z "$MISTRAL_API_KEY" ]; then
        log_warning "MISTRAL_API_KEY not set in environment"
        read -p "Enter your Mistral API key: " MISTRAL_API_KEY
    fi

    # Deploy container
    log_info "Deploying container..."
    CONTAINER_ID=$(scw container container create \
        namespace-id=${NAMESPACE_ID} \
        name=${APP_NAME} \
        registry-image=${FULL_IMAGE} \
        port=8080 \
        cpu-limit=1000 \
        memory-limit=2048 \
        min-scale=0 \
        max-scale=5 \
        environment-variables.MISTRAL_API_KEY=${MISTRAL_API_KEY} \
        environment-variables.PORT=8080 \
        region=${REGION} \
        --output json | jq -r '.id')

    # Deploy the container
    scw container container deploy ${CONTAINER_ID} region=${REGION}

    # Wait and get endpoint
    sleep 10
    CONTAINER_URL=$(scw container container get ${CONTAINER_ID} region=${REGION} --output json | jq -r '.domain_name')

    log_success "Container deployed!"
    echo ""
    echo "=============================================="
    echo "Container URL: https://${CONTAINER_URL}"
    echo "=============================================="
    echo ""
    echo "Test it with:"
    echo "  curl https://${CONTAINER_URL}/health"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

echo "=============================================="
echo "  MoAudit_MEL - Scaleway Deployment"
echo "=============================================="
echo ""

check_prerequisites
build_image

DEPLOY_TYPE=${1:-""}

if [ -z "$DEPLOY_TYPE" ]; then
    echo ""
    echo "Select deployment type:"
    echo "  1) Instance (VM) - Full control, persistent storage"
    echo "  2) Serverless Container - Auto-scaling, pay-per-use"
    echo ""
    read -p "Choice [1-2]: " DEPLOY_CHOICE

    case ${DEPLOY_CHOICE} in
        1) DEPLOY_TYPE="instance" ;;
        2) DEPLOY_TYPE="container" ;;
        *) log_error "Invalid choice" ;;
    esac
fi

case ${DEPLOY_TYPE} in
    instance)
        deploy_instance
        ;;
    container)
        deploy_container
        ;;
    *)
        log_error "Unknown deployment type: ${DEPLOY_TYPE}. Use 'instance' or 'container'"
        ;;
esac

log_success "Deployment complete!"
