#!/bin/bash
# =============================================================================
# MoA_MEL - Script de déploiement Scaleway
# =============================================================================
# Ce script automatise le déploiement sur une instance Scaleway
# Usage: ./scripts/deploy-scaleway.sh [dev|prod]
# =============================================================================

set -euo pipefail

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration par défaut
ENV="${1:-dev}"
PROJECT_NAME="moamel"
SCALEWAY_REGION="${SCALEWAY_REGION:-fr-par}"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# =============================================================================
# PHASE 1: Vérification des prérequis
# =============================================================================
check_prerequisites() {
    log_info "Vérification des prérequis..."

    # Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker n'est pas installé. Installez Docker: https://docs.docker.com/get-docker/"
    fi

    # Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose n'est pas installé."
    fi

    # Variables d'environnement requises
    if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
        log_warn "MISTRAL_API_KEY non définie. L'extraction LLM sera désactivée."
        log_info "Définissez: export MISTRAL_API_KEY='votre-clé-api'"
    fi

    log_success "Prérequis vérifiés"
}

# =============================================================================
# PHASE 2: Configuration de l'environnement
# =============================================================================
setup_environment() {
    log_info "Configuration de l'environnement ($ENV)..."

    # Créer le fichier .env s'il n'existe pas
    if [[ ! -f ".env" ]]; then
        log_info "Création du fichier .env..."
        cat > .env << EOF
# MoA_MEL Environment Configuration
# ==================================
# Généré le $(date)

# Environnement
ENVIRONMENT=${ENV}

# API Mistral (requis pour l'extraction LLM)
MISTRAL_API_KEY=${MISTRAL_API_KEY:-}

# Port de l'application
PORT=8080

# Base de données PostgreSQL
PG_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
PG_EXTERNAL_PORT=5432

# Production uniquement
HTTP_PORT=80
HTTPS_PORT=443
EOF
        log_success "Fichier .env créé"
        log_warn "IMPORTANT: Éditez .env pour configurer MISTRAL_API_KEY"
    else
        log_info "Fichier .env existant conservé"
    fi

    # Créer les répertoires nécessaires
    mkdir -p data/uploads outputs logs/hitl nginx/ssl

    log_success "Environnement configuré"
}

# =============================================================================
# PHASE 3: Configuration Nginx (production)
# =============================================================================
setup_nginx() {
    if [[ "$ENV" == "prod" ]]; then
        log_info "Configuration Nginx pour production..."

        if [[ ! -f "nginx/nginx.conf" ]]; then
            cat > nginx/nginx.conf << 'EOF'
events {
    worker_connections 1024;
}

http {
    upstream moamel_app {
        server moamel:8080;
    }

    server {
        listen 80;
        server_name _;

        # Redirection HTTPS en production
        # return 301 https://$server_name$request_uri;

        location / {
            proxy_pass http://moamel_app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # WebSocket support
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

        location /health {
            proxy_pass http://moamel_app/health;
            access_log off;
        }
    }

    # HTTPS (décommenter et configurer les certificats)
    # server {
    #     listen 443 ssl;
    #     server_name your-domain.com;
    #
    #     ssl_certificate /etc/nginx/ssl/fullchain.pem;
    #     ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    #
    #     location / {
    #         proxy_pass http://moamel_app;
    #         # ... mêmes headers que ci-dessus
    #     }
    # }
}
EOF
            log_success "Configuration Nginx créée"
        fi
    fi
}

# =============================================================================
# PHASE 4: Build et démarrage
# =============================================================================
build_and_start() {
    log_info "Construction des images Docker..."

    if [[ "$ENV" == "prod" ]]; then
        docker compose --profile production build
        log_info "Démarrage en mode production..."
        docker compose --profile production up -d
    else
        docker compose build
        log_info "Démarrage en mode développement..."
        docker compose up -d
    fi

    log_success "Services démarrés"
}

# =============================================================================
# PHASE 5: Vérification du déploiement
# =============================================================================
verify_deployment() {
    log_info "Vérification du déploiement..."

    # Attendre que les services soient prêts
    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            log_success "Application accessible sur http://localhost:8080"
            break
        fi
        log_info "Attente du démarrage... ($attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done

    if [[ $attempt -gt $max_attempts ]]; then
        log_error "L'application n'a pas démarré dans le temps imparti"
    fi

    # Afficher le statut des containers
    echo ""
    log_info "Statut des services:"
    docker compose ps

    echo ""
    log_info "Logs récents:"
    docker compose logs --tail=20 moamel
}

# =============================================================================
# PHASE 6: Instructions finales
# =============================================================================
print_instructions() {
    echo ""
    echo "============================================================================="
    echo -e "${GREEN}Déploiement MoA_MEL terminé!${NC}"
    echo "============================================================================="
    echo ""
    echo "URLs disponibles:"
    echo "  - Dashboard:     http://localhost:8080/dashboard"
    echo "  - API Root:      http://localhost:8080/"
    echo "  - Health Check:  http://localhost:8080/health"
    echo "  - API Docs:      http://localhost:8080/docs"
    echo ""
    echo "Commandes utiles:"
    echo "  - Voir les logs:     docker compose logs -f moamel"
    echo "  - Redémarrer:        docker compose restart moamel"
    echo "  - Arrêter:           docker compose down"
    echo "  - Nettoyer:          docker compose down -v --rmi all"
    echo ""
    echo "Pour un test rapide:"
    echo "  curl http://localhost:8080/api/demo-data"
    echo ""

    if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
        echo -e "${YELLOW}ATTENTION: MISTRAL_API_KEY non configurée${NC}"
        echo "L'extraction LLM ne fonctionnera pas."
        echo "Éditez .env et relancez: docker compose restart moamel"
        echo ""
    fi
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    echo ""
    echo "============================================================================="
    echo "  MoA_MEL - Déploiement Scaleway"
    echo "  Environnement: $ENV"
    echo "============================================================================="
    echo ""

    check_prerequisites
    setup_environment
    setup_nginx
    build_and_start
    verify_deployment
    print_instructions
}

# Exécuter
main "$@"
