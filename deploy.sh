#!/bin/bash
# =============================================================================
# MoA_MEL Audit - Script de déploiement Scaleway
# =============================================================================
# Usage: ./deploy.sh [--with-ssl]
#
# Prérequis:
#   - Ubuntu 20.04+ ou Debian 11+
#   - Accès root ou sudo
#   - Port 8080 ouvert (ou 80/443 avec SSL)
# =============================================================================

set -e

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}  MoA_MEL Audit - Installation${NC}"
echo -e "${GREEN}=======================================${NC}"

# 1. Mise à jour système
echo -e "\n${YELLOW}[1/6] Mise à jour du système...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# 2. Créer le répertoire d'installation
INSTALL_DIR="/opt/moamel"
echo -e "\n${YELLOW}[2/6] Création du répertoire d'installation: $INSTALL_DIR${NC}"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# 3. Cloner le repository (si pas déjà fait)
if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo -e "\n${YELLOW}[3/6] Clonage du repository...${NC}"
    git clone https://github.com/pgadet-wq/MoAudit_MEL.git .
else
    echo -e "\n${YELLOW}[3/6] Mise à jour du repository...${NC}"
    git pull origin main
fi

# 4. Créer l'environnement virtuel
echo -e "\n${YELLOW}[4/6] Configuration de l'environnement Python...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 5. Installer Docling pour le parsing PDF avancé
echo -e "\n${YELLOW}[5/6] Installation de Docling (parsing PDF)...${NC}"
pip install docling -q || echo -e "${YELLOW}Note: Docling optionnel, parsing basique disponible${NC}"

# 6. Créer les répertoires de données
echo -e "\n${YELLOW}[6/6] Création des répertoires de données...${NC}"
mkdir -p data/uploads
mkdir -p outputs
mkdir -p src/data

# Créer le fichier de configuration
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}Création du fichier .env...${NC}"
    cat > .env << 'EOF'
# MoA_MEL Configuration
# ======================

# Mistral API (pour parsing LLM avancé)
MISTRAL_API_KEY=your_mistral_api_key_here

# Serveur
HOST=0.0.0.0
PORT=8080

# Base de données
DATABASE_URL=sqlite:///data/moamel_audit.db
EOF
    echo -e "${YELLOW}>>> IMPORTANT: Éditez .env pour ajouter votre clé API Mistral${NC}"
fi

# Créer le service systemd
echo -e "\n${YELLOW}Création du service systemd...${NC}"
cat > /etc/systemd/system/moamel.service << EOF
[Unit]
Description=MoA_MEL Audit Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/src
Environment="PATH=$INSTALL_DIR/venv/bin"
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python server_v2.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable moamel

echo -e "\n${GREEN}=======================================${NC}"
echo -e "${GREEN}  Installation terminée !${NC}"
echo -e "${GREEN}=======================================${NC}"

echo -e "\n${YELLOW}Prochaines étapes:${NC}"
echo -e "1. Éditez le fichier de configuration:"
echo -e "   ${GREEN}nano $INSTALL_DIR/.env${NC}"
echo -e "   Ajoutez votre clé API Mistral"
echo -e ""
echo -e "2. Démarrez le service:"
echo -e "   ${GREEN}systemctl start moamel${NC}"
echo -e ""
echo -e "3. Vérifiez le statut:"
echo -e "   ${GREEN}systemctl status moamel${NC}"
echo -e ""
echo -e "4. Accédez à l'application:"
echo -e "   ${GREEN}http://VOTRE_IP_SCALEWAY:8080/app${NC}"
echo -e ""
echo -e "5. Déposez vos fichiers MEL/MMEL dans:"
echo -e "   ${GREEN}$INSTALL_DIR/data/uploads/${NC}"
echo -e ""
echo -e "${YELLOW}Logs:${NC} journalctl -u moamel -f"
