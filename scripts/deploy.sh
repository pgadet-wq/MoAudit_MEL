#!/bin/bash
# ===========================================
# MoAudit MEL - Deployment Script
# ===========================================
# Usage: ./scripts/deploy.sh [staging|production]

set -e

ENVIRONMENT=${1:-staging}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Banner
echo "============================================="
echo "   MoAudit MEL Deployment - $ENVIRONMENT"
echo "============================================="
echo ""

cd "$PROJECT_DIR"

# Check requirements
log_info "Checking requirements..."
command -v docker >/dev/null 2>&1 || { log_error "Docker is required but not installed."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { log_error "Docker Compose is required but not installed."; exit 1; }

# Check .env file
if [ ! -f ".env" ]; then
    log_error ".env file not found!"
    log_info "Copy .env.example to .env and configure it:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

# Load environment variables
source .env

# Determine compose files
COMPOSE_FILES="-f docker-compose.prod.yml"

log_info "Environment: $ENVIRONMENT"
log_info "Compose files: $COMPOSE_FILES"

# Pull latest code (if git repo)
if [ -d ".git" ]; then
    log_info "Pulling latest code..."
    git pull --rebase || log_warning "Git pull failed, continuing with local code"
fi

# Build images
log_info "Building Docker images..."
docker compose $COMPOSE_FILES build --no-cache

# Stop existing containers
log_info "Stopping existing containers..."
docker compose $COMPOSE_FILES down --remove-orphans || true

# Start services
log_info "Starting services..."
docker compose $COMPOSE_FILES up -d

# Wait for services to be ready
log_info "Waiting for services to be ready..."
sleep 10

# Health check
log_info "Running health check..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        log_success "API is healthy!"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    log_info "Waiting for API... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    log_error "Health check failed after $MAX_RETRIES attempts"
    log_info "Checking container logs..."
    docker compose $COMPOSE_FILES logs --tail=50
    exit 1
fi

# Deep health check
log_info "Running deep health check..."
DEEP_HEALTH=$(curl -s http://localhost:8080/health/deep)
DEEP_STATUS=$(echo "$DEEP_HEALTH" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ "$DEEP_STATUS" = "healthy" ]; then
    log_success "All services are healthy!"
else
    log_warning "Some services may be degraded: $DEEP_STATUS"
    echo "$DEEP_HEALTH" | python3 -m json.tool 2>/dev/null || echo "$DEEP_HEALTH"
fi

# Show running containers
echo ""
log_info "Running containers:"
docker compose $COMPOSE_FILES ps

# Show resource usage
echo ""
log_info "Resource usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

echo ""
log_success "Deployment complete!"
echo ""
echo "Access the dashboard at: http://localhost"
echo "API documentation at: http://localhost:8080/docs"
echo ""
echo "Useful commands:"
echo "  View logs:     docker compose $COMPOSE_FILES logs -f"
echo "  Stop:          docker compose $COMPOSE_FILES down"
echo "  Restart:       docker compose $COMPOSE_FILES restart"
echo "  Health check:  curl http://localhost/health/deep"
