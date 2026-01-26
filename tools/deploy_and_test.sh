#!/bin/bash
#
# Script de déploiement et test du service Docling V2
# Usage: ./deploy_and_test.sh [--deploy] [--test] [--logs]
#

SERVER="51.159.146.199"
SERVER_USER="root"
REMOTE_PATH="/opt/docling-service"

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_header() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
}

# Fonction: Déployer le service
deploy() {
    print_header "DÉPLOIEMENT"

    echo "Copie de docling_service_v2.py vers le serveur..."
    scp docling_service_v2.py ${SERVER_USER}@${SERVER}:${REMOTE_PATH}/server.py

    if [ $? -eq 0 ]; then
        print_status "Fichier copié"
    else
        print_error "Erreur de copie"
        exit 1
    fi

    echo "Redémarrage du service..."
    ssh ${SERVER_USER}@${SERVER} << 'EOF'
pkill -f "python3 server.py" 2>/dev/null
sleep 1
cd /opt/docling-service
nohup python3 server.py > /var/log/docling-service.log 2>&1 &
sleep 3
ps aux | grep -v grep | grep "python3 server.py" && echo "Service démarré" || echo "ERREUR: Service non démarré"
EOF

    print_status "Déploiement terminé"
}

# Fonction: Tests
run_tests() {
    print_header "TESTS"

    echo ""
    echo "1. Health check vLLM..."
    VLLM_HEALTH=$(curl -s http://${SERVER}:8000/health)
    if [[ "$VLLM_HEALTH" == *"healthy"* ]]; then
        print_status "vLLM OK"
    else
        print_error "vLLM non disponible: $VLLM_HEALTH"
    fi

    echo ""
    echo "2. Health check Docling Service..."
    DOCLING_HEALTH=$(curl -s http://${SERVER}:8080/health)
    echo "$DOCLING_HEALTH" | python3 -m json.tool 2>/dev/null || echo "$DOCLING_HEALTH"
    if [[ "$DOCLING_HEALTH" == *"healthy"* ]]; then
        print_status "Docling Service OK"
    else
        print_warning "Docling Service dégradé"
    fi

    echo ""
    echo "3. Test vLLM texte seul..."
    VLLM_TEXT=$(curl -s -X POST http://${SERVER}:8080/test/vllm-text)
    echo "$VLLM_TEXT" | python3 -m json.tool 2>/dev/null | head -20
    if [[ "$VLLM_TEXT" == *"200"* ]] || [[ "$VLLM_TEXT" == *"choices"* ]]; then
        print_status "vLLM texte OK"
    else
        print_error "vLLM texte échoué"
    fi

    echo ""
    echo "4. Info Docling..."
    curl -s http://${SERVER}:8080/debug/docling-info | python3 -m json.tool 2>/dev/null

    echo ""
    echo "5. Stats service..."
    curl -s http://${SERVER}:8080/stats | python3 -m json.tool 2>/dev/null
}

# Fonction: Test avec PDF
test_pdf() {
    local PDF_FILE="$1"

    if [ ! -f "$PDF_FILE" ]; then
        print_error "Fichier non trouvé: $PDF_FILE"
        exit 1
    fi

    print_header "TEST PDF: $PDF_FILE"

    echo ""
    echo "1. Test direct page 0 (bypass Docling)..."
    RESULT=$(curl -s -X POST http://${SERVER}:8080/test/pdf-page \
        -F "file=@${PDF_FILE}" \
        -F "page=0")
    echo "$RESULT" | python3 -m json.tool 2>/dev/null

    if [[ "$RESULT" == *"has_doctags\":true"* ]]; then
        print_status "DocTags générés directement ✓"
    else
        print_warning "Pas de DocTags dans le test direct"
    fi

    echo ""
    echo "2. Test conversion Docling..."
    RESULT=$(curl -s -X POST http://${SERVER}:8080/convert \
        -F "file=@${PDF_FILE}")
    echo "$RESULT" | python3 -m json.tool 2>/dev/null | head -30

    MARKDOWN_LEN=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('markdown_length',0))" 2>/dev/null)
    if [ "$MARKDOWN_LEN" -gt 0 ] 2>/dev/null; then
        print_status "Markdown généré: $MARKDOWN_LEN caractères ✓"
    else
        print_error "Markdown vide!"
    fi
}

# Fonction: Voir les logs
show_logs() {
    print_header "LOGS RÉCENTS"
    ssh ${SERVER_USER}@${SERVER} "tail -100 /var/log/docling-service.log"
}

# Fonction: Logs en temps réel
follow_logs() {
    print_header "LOGS EN TEMPS RÉEL (Ctrl+C pour quitter)"
    ssh ${SERVER_USER}@${SERVER} "tail -f /var/log/docling-service.log"
}

# Fonction: Générer PDF de test
create_test_pdf() {
    print_header "GÉNÉRATION PDF DE TEST"
    python3 create_test_pdf.py .
    print_status "PDFs créés: test_simple.pdf, test_mel_table.pdf"
}

# Main
case "$1" in
    --deploy)
        deploy
        ;;
    --test)
        run_tests
        ;;
    --test-pdf)
        if [ -z "$2" ]; then
            echo "Usage: $0 --test-pdf <fichier.pdf>"
            exit 1
        fi
        test_pdf "$2"
        ;;
    --logs)
        show_logs
        ;;
    --follow)
        follow_logs
        ;;
    --create-pdf)
        create_test_pdf
        ;;
    --full)
        deploy
        sleep 2
        run_tests
        ;;
    *)
        echo "Usage: $0 [option]"
        echo ""
        echo "Options:"
        echo "  --deploy       Déployer le service sur le serveur"
        echo "  --test         Exécuter les tests de base"
        echo "  --test-pdf <f> Tester avec un fichier PDF"
        echo "  --logs         Afficher les logs récents"
        echo "  --follow       Suivre les logs en temps réel"
        echo "  --create-pdf   Générer les PDFs de test"
        echo "  --full         Déployer puis tester"
        echo ""
        echo "Exemple:"
        echo "  $0 --full"
        echo "  $0 --create-pdf && $0 --test-pdf test_simple.pdf"
        ;;
esac
