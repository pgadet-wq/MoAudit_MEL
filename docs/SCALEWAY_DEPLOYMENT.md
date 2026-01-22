# Guide de Déploiement Complet - MoAudit MEL sur Scaleway

> **Budget estimé** : 250-400€/mois
> **Temps de déploiement** : 2-3 heures

---

## Table des Matières

1. [Prérequis](#1-prérequis)
2. [Architecture Cible](#2-architecture-cible)
3. [Création des Ressources Scaleway](#3-création-des-ressources-scaleway)
4. [Déploiement Granite-Docling (GPU)](#4-déploiement-granite-docling-gpu)
5. [Déploiement Docling Service + MoAudit API](#5-déploiement-docling-service--moaudit-api)
6. [Configuration DNS et SSL](#6-configuration-dns-et-ssl)
7. [Configuration CI/CD](#7-configuration-cicd)
8. [Vérification et Tests](#8-vérification-et-tests)
9. [Monitoring et Maintenance](#9-monitoring-et-maintenance)

---

## 1. Prérequis

### 1.1 Comptes et Outils

- [ ] Compte Scaleway avec facturation activée
- [ ] Scaleway CLI (`scw`) installé
- [ ] Docker installé localement
- [ ] Git configuré
- [ ] Nom de domaine (optionnel mais recommandé)

### 1.2 Installation Scaleway CLI

```bash
# macOS
brew install scw

# Linux
curl -s https://raw.githubusercontent.com/scaleway/scaleway-cli/master/scripts/get.sh | sh

# Windows (PowerShell)
iwr -useb https://raw.githubusercontent.com/scaleway/scaleway-cli/master/scripts/get.ps1 | iex
```

### 1.3 Configuration CLI

```bash
# Initialiser la configuration
scw init

# Entrez:
# - Access Key: SCWxxxxxxxxxxxxxxxxx
# - Secret Key: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - Organization ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - Project ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - Default region: fr-par
# - Default zone: fr-par-1
```

---

## 2. Architecture Cible

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCALEWAY CLOUD                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────────────────────────────┐ │
│  │   USERS      │     │         DEV-1-M (CPU Instance)       │ │
│  │   Browser    │────▶│  ┌────────────┐  ┌────────────────┐  │ │
│  └──────────────┘     │  │  Nginx     │  │  MoAudit API   │  │ │
│         │             │  │  (Reverse  │──│  (FastAPI)     │  │ │
│         │             │  │   Proxy)   │  │  :8080         │  │ │
│         │             │  └────────────┘  └────────────────┘  │ │
│         │             │         │               │            │ │
│         │             │         │        ┌──────┴──────┐     │ │
│         │             │         │        │             │     │ │
│         │             │  ┌──────▼─────┐  │  ┌────────┐ │     │ │
│         │             │  │  Docling   │  │  │ Redis  │ │     │ │
│         │             │  │  Service   │  │  │ :6379  │ │     │ │
│         │             │  │  :8001     │  │  └────────┘ │     │ │
│         │             │  └──────┬─────┘  └─────────────┘     │ │
│         │             └─────────┼────────────────────────────┘ │
│         │                       │                               │
│         │                       ▼                               │
│         │             ┌──────────────────────────────────────┐ │
│         │             │       GPU-3070-S (GPU Instance)      │ │
│         │             │  ┌────────────────────────────────┐  │ │
│         │             │  │      Granite-Docling VLM       │  │ │
│         │             │  │      (vLLM Server)             │  │ │
│         │             │  │      :8000                     │  │ │
│         │             │  └────────────────────────────────┘  │ │
│         │             └──────────────────────────────────────┘ │
│         │                                                       │
│         │             ┌──────────────────────────────────────┐ │
│         └────────────▶│       Object Storage (S3)            │ │
│                       │  - moaudit-documents (PDFs)          │ │
│                       │  - moaudit-reports (Results)         │ │
│                       └──────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Estimation des Coûts

| Ressource | Type | Coût/mois |
|-----------|------|-----------|
| Instance CPU | DEV1-M (3 vCPU, 4GB RAM) | ~15€ |
| Instance GPU | GPU-3070-S (L4) | ~150-250€ |
| Object Storage | 100GB | ~2€ |
| Managed Redis | (optionnel) | ~20€ |
| Load Balancer | (optionnel) | ~10€ |
| **Total** | | **~170-300€** |

> **Note** : L'instance GPU peut être éteinte quand non utilisée pour réduire les coûts.

---

## 3. Création des Ressources Scaleway

### 3.1 Créer un Projet Dédié

```bash
# Créer le projet
scw account project create name=moaudit-mel

# Noter le Project ID retourné
export PROJECT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### 3.2 Créer les Clés SSH

```bash
# Générer une clé SSH dédiée
ssh-keygen -t ed25519 -C "moaudit-scaleway" -f ~/.ssh/moaudit_scaleway

# Ajouter la clé publique à Scaleway
scw iam ssh-key create name=moaudit-key public-key="$(cat ~/.ssh/moaudit_scaleway.pub)"
```

### 3.3 Créer le Bucket Object Storage

```bash
# Créer le bucket pour les documents
scw object bucket create name=moaudit-documents

# Créer le bucket pour les rapports
scw object bucket create name=moaudit-reports

# Créer les credentials S3
scw iam api-key create description="MoAudit S3 Access"
# Noter l'Access Key et Secret Key
```

### 3.4 Créer l'Instance CPU (MoAudit + Docling)

```bash
# Créer l'instance
scw instance server create \
  type=DEV1-M \
  image=ubuntu_jammy \
  name=moaudit-api \
  root-volume=b:50GB \
  ip=new \
  project-id=$PROJECT_ID

# Noter l'IP publique
export CPU_IP="xx.xx.xx.xx"
```

### 3.5 Créer l'Instance GPU (Granite-Docling)

```bash
# Vérifier la disponibilité GPU
scw instance server-type list zone=fr-par-2 | grep GPU

# Créer l'instance GPU (zone fr-par-2 pour GPU)
scw instance server create \
  type=GPU-3070-S \
  image=ubuntu_jammy_gpu_os_12 \
  name=granite-docling \
  root-volume=b:100GB \
  ip=new \
  zone=fr-par-2 \
  project-id=$PROJECT_ID

# Noter l'IP publique
export GPU_IP="yy.yy.yy.yy"
```

### 3.6 Créer un Réseau Privé (Optionnel mais Recommandé)

```bash
# Créer un Private Network
scw vpc private-network create \
  name=moaudit-network \
  project-id=$PROJECT_ID

# Attacher les instances au réseau privé
# (via la console Scaleway - plus simple)
```

---

## 4. Déploiement Granite-Docling (GPU)

### 4.1 Se Connecter à l'Instance GPU

```bash
ssh -i ~/.ssh/moaudit_scaleway root@$GPU_IP
```

### 4.2 Installer Docker avec Support NVIDIA

```bash
# Mettre à jour le système
apt update && apt upgrade -y

# Installer Docker
curl -fsSL https://get.docker.com | sh

# Installer NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt update
apt install -y nvidia-container-toolkit

# Configurer Docker pour NVIDIA
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# Vérifier
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### 4.3 Déployer Granite-Docling

```bash
# Créer le répertoire
mkdir -p /opt/granite-docling
cd /opt/granite-docling

# Créer docker-compose.gpu.yml
cat > docker-compose.gpu.yml << 'EOF'
version: '3.8'

services:
  granite-docling:
    image: vllm/vllm-openai:latest
    container_name: granite-docling
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - HF_HOME=/root/.cache/huggingface
    volumes:
      - ./model-cache:/root/.cache/huggingface
    ports:
      - "8000:8000"
    command: >
      --model ibm-granite/granite-docling-258M
      --revision untied
      --port 8000
      --host 0.0.0.0
      --max-model-len 4096
      --gpu-memory-utilization 0.9
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
EOF

# Lancer le service
docker compose -f docker-compose.gpu.yml up -d

# Suivre les logs (le modèle se télécharge ~500MB)
docker compose -f docker-compose.gpu.yml logs -f
```

### 4.4 Vérifier le Déploiement GPU

```bash
# Attendre que le modèle soit chargé (2-3 minutes)
# Vérifier le health
curl http://localhost:8000/health

# Vérifier les modèles disponibles
curl http://localhost:8000/v1/models

# Test d'inférence (optionnel)
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ibm-granite/granite-docling-258M",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

### 4.5 Configurer le Firewall GPU

```bash
# Sur l'instance GPU, autoriser seulement l'IP de l'instance CPU
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow from $CPU_IP to any port 8000
ufw enable
```

---

## 5. Déploiement Docling Service + MoAudit API

### 5.1 Se Connecter à l'Instance CPU

```bash
ssh -i ~/.ssh/moaudit_scaleway root@$CPU_IP
```

### 5.2 Installer Docker

```bash
# Mettre à jour
apt update && apt upgrade -y

# Installer Docker
curl -fsSL https://get.docker.com | sh

# Installer Docker Compose
apt install -y docker-compose-plugin

# Vérifier
docker --version
docker compose version
```

### 5.3 Cloner le Repository

```bash
# Installer Git
apt install -y git

# Cloner le projet
cd /opt
git clone https://github.com/VOTRE_USERNAME/MoAudit_MEL.git moaudit
cd moaudit
```

### 5.4 Configurer les Variables d'Environnement

```bash
# Copier le template
cp .env.example .env

# Éditer la configuration
nano .env
```

**Contenu du `.env`** :
```bash
# ===========================================
# MoAudit MEL - Configuration Production
# ===========================================

# Parsing Backend
PARSING_BACKEND=remote_docling

# Docling Service
DOCLING_SERVICE_URL=http://docling-service:8001
DOCLING_TIMEOUT=300

# Granite-Docling (IP privée si VPC, sinon IP publique)
GRANITE_SERVICE_URL=http://YOUR_GPU_IP:8000/v1
GRANITE_MODEL_NAME=ibm-granite/granite-docling-258M

# Redis
REDIS_ENABLED=true
REDIS_URL=redis://redis:6379/0

# Storage S3 (Scaleway Object Storage)
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://s3.fr-par.scw.cloud
S3_ACCESS_KEY=YOUR_SCW_ACCESS_KEY
S3_SECRET_KEY=YOUR_SCW_SECRET_KEY
S3_BUCKET_NAME=moaudit-documents
S3_REGION=fr-par

# Authentication
JWT_SECRET_KEY=GENERATE_A_SECURE_SECRET_HERE
MOAUDIT_API_KEY=GENERATE_AN_API_KEY_HERE

# Database (SQLite pour commencer, PostgreSQL recommandé en prod)
DATABASE_MODE=sqlite
SQLITE_PATH=/app/data/moaudit.db

# Logging
LOG_LEVEL=INFO
```

**Générer les secrets** :
```bash
# Générer JWT_SECRET_KEY
openssl rand -base64 32

# Générer MOAUDIT_API_KEY
openssl rand -hex 24
```

### 5.5 Créer docker-compose.prod.yml

```bash
cat > docker-compose.prod.yml << 'EOF'
version: '3.8'

services:
  # ===========================================
  # MoAudit API
  # ===========================================
  moaudit-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: moaudit-api
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
      - ./outputs:/app/outputs
    depends_on:
      - redis
      - docling-service
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ===========================================
  # Docling Service
  # ===========================================
  docling-service:
    build:
      context: ./services/docling-service
      dockerfile: Dockerfile
    container_name: docling-service
    environment:
      - GRANITE_SERVICE_URL=${GRANITE_SERVICE_URL}
      - GRANITE_MODEL_NAME=${GRANITE_MODEL_NAME}
      - USE_VLM=true
      - LOG_LEVEL=INFO
    ports:
      - "8001:8001"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ===========================================
  # Redis
  # ===========================================
  redis:
    image: redis:7-alpine
    container_name: moaudit-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ===========================================
  # Celery Worker (optionnel, pour jobs async)
  # ===========================================
  celery-worker:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: moaudit-celery
    env_file: .env
    command: celery -A src.tasks worker --loglevel=info --concurrency=2
    volumes:
      - ./data:/app/data
    depends_on:
      - redis
    restart: unless-stopped

  # ===========================================
  # Nginx Reverse Proxy
  # ===========================================
  nginx:
    image: nginx:alpine
    container_name: moaudit-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./static:/usr/share/nginx/html/static:ro
    depends_on:
      - moaudit-api
    restart: unless-stopped

volumes:
  redis-data:
EOF
```

### 5.6 Créer la Configuration Nginx

```bash
mkdir -p nginx/ssl

cat > nginx/nginx.conf << 'EOF'
events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # Logging
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # Upload size
    client_max_body_size 100M;

    # Upstream
    upstream moaudit_api {
        server moaudit-api:8080;
    }

    server {
        listen 80;
        server_name _;

        # Redirect to HTTPS (décommenter si SSL configuré)
        # return 301 https://$server_name$request_uri;

        location / {
            proxy_pass http://moaudit_api;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }

        # Static files
        location /static {
            alias /usr/share/nginx/html/static;
            expires 1d;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://moaudit_api/health;
        }
    }

    # HTTPS (décommenter et configurer si SSL)
    # server {
    #     listen 443 ssl http2;
    #     server_name moaudit.example.com;
    #
    #     ssl_certificate /etc/nginx/ssl/fullchain.pem;
    #     ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    #     ssl_protocols TLSv1.2 TLSv1.3;
    #
    #     location / {
    #         proxy_pass http://moaudit_api;
    #         # ... same as above
    #     }
    # }
}
EOF
```

### 5.7 Build et Lancement

```bash
cd /opt/moaudit

# Build les images
docker compose -f docker-compose.prod.yml build

# Lancer les services
docker compose -f docker-compose.prod.yml up -d

# Vérifier les logs
docker compose -f docker-compose.prod.yml logs -f

# Vérifier le statut
docker compose -f docker-compose.prod.yml ps
```

### 5.8 Vérification

```bash
# Health check basique
curl http://localhost/health

# Health check profond
curl http://localhost/health/deep

# Dashboard
curl http://localhost/
```

---

## 6. Configuration DNS et SSL

### 6.1 Configuration DNS

1. Allez dans votre registrar DNS
2. Créez un enregistrement A :
   - **Nom** : `moaudit` (ou `@` pour le domaine racine)
   - **Type** : A
   - **Valeur** : `$CPU_IP`
   - **TTL** : 300

### 6.2 SSL avec Let's Encrypt

```bash
# Installer Certbot
apt install -y certbot

# Arrêter Nginx temporairement
docker compose -f docker-compose.prod.yml stop nginx

# Obtenir le certificat
certbot certonly --standalone -d moaudit.votre-domaine.com

# Copier les certificats
cp /etc/letsencrypt/live/moaudit.votre-domaine.com/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/moaudit.votre-domaine.com/privkey.pem nginx/ssl/

# Éditer nginx.conf pour activer HTTPS (décommenter la section server 443)
nano nginx/nginx.conf

# Relancer Nginx
docker compose -f docker-compose.prod.yml up -d nginx
```

### 6.3 Renouvellement Automatique SSL

```bash
# Créer un script de renouvellement
cat > /opt/moaudit/renew-ssl.sh << 'EOF'
#!/bin/bash
cd /opt/moaudit
docker compose -f docker-compose.prod.yml stop nginx
certbot renew --quiet
cp /etc/letsencrypt/live/moaudit.votre-domaine.com/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/moaudit.votre-domaine.com/privkey.pem nginx/ssl/
docker compose -f docker-compose.prod.yml up -d nginx
EOF

chmod +x /opt/moaudit/renew-ssl.sh

# Ajouter au crontab
echo "0 3 1 * * /opt/moaudit/renew-ssl.sh" | crontab -
```

---

## 7. Configuration CI/CD

### 7.1 Secrets GitHub

Allez dans **Settings > Secrets and variables > Actions** de votre repository GitHub et ajoutez :

| Secret | Description |
|--------|-------------|
| `SCALEWAY_SSH_KEY` | Contenu de `~/.ssh/moaudit_scaleway` (clé privée) |
| `SCALEWAY_KNOWN_HOSTS` | `ssh-keyscan $CPU_IP` |
| `SCALEWAY_STAGING_HOST` | IP de l'instance CPU |
| `SCALEWAY_PROD_HOST` | IP de l'instance CPU (ou autre pour prod) |
| `SCALEWAY_DEPLOY_USER` | `root` |
| `SCALEWAY_SECRET_KEY` | Secret Key Scaleway pour le registry |
| `SCALEWAY_GPU_SSH_KEY` | Clé SSH pour l'instance GPU |
| `SCALEWAY_GPU_KNOWN_HOSTS` | `ssh-keyscan $GPU_IP` |
| `SCALEWAY_GPU_HOST` | IP de l'instance GPU |
| `SCALEWAY_GPU_USER` | `root` |
| `SLACK_WEBHOOK_URL` | (optionnel) Webhook Slack pour notifications |

### 7.2 Générer les Known Hosts

```bash
# Sur votre machine locale
ssh-keyscan $CPU_IP > known_hosts_cpu.txt
ssh-keyscan $GPU_IP > known_hosts_gpu.txt

# Copiez le contenu dans les secrets GitHub
cat known_hosts_cpu.txt
cat known_hosts_gpu.txt
```

### 7.3 Tester le Pipeline

```bash
# Créer une branche develop et pousser
git checkout -b develop
git push -u origin develop

# Le pipeline va :
# 1. Lint et tests
# 2. Build des images Docker
# 3. Scan de sécurité
# 4. Déploiement sur staging
```

---

## 8. Vérification et Tests

### 8.1 Checklist de Vérification

```bash
# Sur l'instance CPU
cd /opt/moaudit

# 1. Vérifier tous les containers
docker compose -f docker-compose.prod.yml ps

# 2. Health check profond
curl http://localhost/health/deep | jq

# 3. Tester l'upload
curl -X POST http://localhost/api/upload/MEL \
  -F "file=@test.pdf"

# 4. Vérifier la connexion au GPU
curl http://$GPU_IP:8000/v1/models
```

### 8.2 Test End-to-End

```bash
# 1. Upload MEL
MEL_RESPONSE=$(curl -s -X POST http://localhost/api/upload/MEL \
  -F "file=@samples/sample_mel.pdf")
MEL_FILE=$(echo $MEL_RESPONSE | jq -r '.filename')

# 2. Upload MMEL
MMEL_RESPONSE=$(curl -s -X POST http://localhost/api/upload/MMEL \
  -F "file=@samples/sample_mmel.pdf")
MMEL_FILE=$(echo $MMEL_RESPONSE | jq -r '.filename')

# 3. Lancer l'audit
AUDIT_RESPONSE=$(curl -s -X POST http://localhost/api/audit/start \
  -H "Content-Type: application/json" \
  -d "{\"mel_file\": \"$MEL_FILE\", \"mmel_file\": \"$MMEL_FILE\"}")
JOB_ID=$(echo $AUDIT_RESPONSE | jq -r '.job_id')

# 4. Suivre le statut
watch -n 2 "curl -s http://localhost/api/audit/status/$JOB_ID | jq"

# 5. Récupérer les résultats
curl http://localhost/api/audit/result/$JOB_ID | jq
```

---

## 9. Monitoring et Maintenance

### 9.1 Logs Centralisés

```bash
# Voir tous les logs
docker compose -f docker-compose.prod.yml logs -f

# Logs d'un service spécifique
docker compose -f docker-compose.prod.yml logs -f moaudit-api

# Logs GPU (depuis l'instance GPU)
ssh root@$GPU_IP "docker compose -f /opt/granite-docling/docker-compose.gpu.yml logs -f"
```

### 9.2 Script de Santé

```bash
cat > /opt/moaudit/health-check.sh << 'EOF'
#!/bin/bash

echo "=== MoAudit Health Check ==="
echo "Date: $(date)"
echo ""

# Check API
echo "API Status:"
curl -s http://localhost/health | jq -r '.status'

# Check Deep Health
echo ""
echo "Service Status:"
curl -s http://localhost/health/deep | jq -r '.checks | to_entries[] | "\(.key): \(.value.status)"'

# Check Docker
echo ""
echo "Container Status:"
docker compose -f /opt/moaudit/docker-compose.prod.yml ps --format "table {{.Name}}\t{{.Status}}"

# Check GPU
echo ""
echo "GPU Status:"
curl -s --connect-timeout 5 http://$GPU_IP:8000/health 2>/dev/null && echo "OK" || echo "UNREACHABLE"

# Check Disk
echo ""
echo "Disk Usage:"
df -h / | tail -1

# Check Memory
echo ""
echo "Memory:"
free -h | grep Mem
EOF

chmod +x /opt/moaudit/health-check.sh
```

### 9.3 Crontab de Maintenance

```bash
crontab -e

# Ajouter :
# Health check toutes les 5 minutes
*/5 * * * * /opt/moaudit/health-check.sh >> /var/log/moaudit-health.log 2>&1

# Nettoyage Docker hebdomadaire
0 2 * * 0 docker system prune -af --volumes

# Backup de la base de données quotidien
0 1 * * * tar -czf /opt/backups/moaudit-db-$(date +\%Y\%m\%d).tar.gz /opt/moaudit/data/

# Rotation des logs
0 0 * * * find /var/log -name "moaudit*.log" -mtime +7 -delete
```

### 9.4 Alertes (Optionnel avec Slack)

```bash
cat > /opt/moaudit/alert.sh << 'EOF'
#!/bin/bash
WEBHOOK_URL="YOUR_SLACK_WEBHOOK_URL"

STATUS=$(curl -s http://localhost/health/deep | jq -r '.status')

if [ "$STATUS" != "healthy" ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"⚠️ MoAudit Health Alert: Status is $STATUS\"}" \
        $WEBHOOK_URL
fi
EOF

chmod +x /opt/moaudit/alert.sh

# Ajouter au crontab
echo "*/5 * * * * /opt/moaudit/alert.sh" >> /etc/crontab
```

---

## Commandes Utiles

```bash
# Redémarrer tous les services
docker compose -f docker-compose.prod.yml restart

# Mettre à jour depuis Git
git pull && docker compose -f docker-compose.prod.yml up -d --build

# Voir l'utilisation des ressources
docker stats

# Arrêter l'instance GPU (économies)
scw instance server stop $GPU_INSTANCE_ID zone=fr-par-2

# Démarrer l'instance GPU
scw instance server start $GPU_INSTANCE_ID zone=fr-par-2

# Backup complet
tar -czf moaudit-backup-$(date +%Y%m%d).tar.gz /opt/moaudit
```

---

## Troubleshooting

### Le GPU n'est pas accessible

```bash
# Vérifier le firewall
ufw status

# Vérifier que le service tourne
ssh root@$GPU_IP "docker ps"

# Vérifier les logs
ssh root@$GPU_IP "docker logs granite-docling"
```

### Docling ne peut pas joindre Granite

```bash
# Vérifier la variable d'environnement
docker exec docling-service env | grep GRANITE

# Tester la connectivité depuis le container
docker exec docling-service curl http://$GPU_IP:8000/health
```

### Out of Memory

```bash
# Augmenter le swap
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

*Guide créé pour MoAudit MEL - Janvier 2026*
