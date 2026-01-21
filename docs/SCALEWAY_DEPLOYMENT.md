# Déploiement MoAudit_MEL sur Scaleway

Ce guide détaille les étapes pour déployer l'application MoAudit_MEL sur Scaleway.

## Table des matières

1. [Prérequis](#prérequis)
2. [Option 1 : Instance (VM)](#option-1--instance-vm) - Recommandé pour tests
3. [Option 2 : Serverless Containers](#option-2--serverless-containers)
4. [Option 3 : Instance GPU](#option-3--instance-gpu)
5. [Configuration Post-Déploiement](#configuration-post-déploiement)
6. [Dépannage](#dépannage)

---

## Prérequis

### 1. Compte Scaleway

1. Créez un compte sur [console.scaleway.com](https://console.scaleway.com)
2. Ajoutez un moyen de paiement
3. Générez une clé API :
   - Allez dans **Identity and Access Management** > **API Keys**
   - Cliquez sur **Generate an API Key**
   - Notez votre `Access Key` et `Secret Key`

### 2. Installation des outils locaux

```bash
# Installer Scaleway CLI
# macOS
brew install scw

# Linux
curl -s https://raw.githubusercontent.com/scaleway/scaleway-cli/master/scripts/get.sh | sh

# Windows (PowerShell)
iwr -useb https://raw.githubusercontent.com/scaleway/scaleway-cli/master/scripts/get.ps1 | iex
```

### 3. Configuration de Scaleway CLI

```bash
scw init
# Suivez les instructions pour entrer vos clés API
```

### 4. Clé API Mistral (pour le parsing LLM)

Obtenez une clé sur [console.mistral.ai](https://console.mistral.ai)

---

## Option 1 : Instance (VM)

**Recommandé pour** : Tests, développement, besoin de persistance

### Étape 1 : Créer l'instance

Via la console web :
1. Allez sur [console.scaleway.com/instance/servers](https://console.scaleway.com/instance/servers)
2. Cliquez **Create Instance**
3. Sélectionnez :
   - **Region** : Paris (fr-par-1)
   - **Type** : DEV1-S (2 vCPU, 2GB RAM) - ~€7/mois
   - **Image** : Ubuntu 22.04 LTS
   - **Name** : moaudit-mel-server
4. Ajoutez votre clé SSH
5. Cliquez **Create Instance**

Via CLI :
```bash
# Créer l'instance
scw instance server create \
  type=DEV1-S \
  zone=fr-par-1 \
  image=ubuntu_jammy \
  name=moaudit-mel-server

# Lister les instances pour obtenir l'IP
scw instance server list
```

### Étape 2 : Se connecter à l'instance

```bash
ssh root@<IP_DE_LINSTANCE>
```

### Étape 3 : Installer Docker

```bash
# Mise à jour système
apt update && apt upgrade -y

# Installer Docker
curl -fsSL https://get.docker.com | sh

# Installer Docker Compose
apt install -y docker-compose-plugin

# Vérifier l'installation
docker --version
docker compose version
```

### Étape 4 : Déployer l'application

```bash
# Créer le répertoire
mkdir -p /opt/moaudit && cd /opt/moaudit

# Cloner le repository (ou copier les fichiers)
git clone https://github.com/<votre-repo>/MoAudit_MEL.git .

# Configurer l'environnement
cp .env.example .env
nano .env  # Ajoutez votre MISTRAL_API_KEY

# Lancer l'application
docker compose up -d

# Vérifier le statut
docker compose ps
docker compose logs -f
```

### Étape 5 : Configurer le pare-feu

```bash
# Via console Scaleway ou CLI
# Autoriser le port 8080
scw instance security-group create name=moaudit-sg inbound-default-policy=drop
scw instance security-group-rule create security-group-id=<SG_ID> direction=inbound protocol=TCP dest-port-from=8080 action=accept
scw instance security-group-rule create security-group-id=<SG_ID> direction=inbound protocol=TCP dest-port-from=22 action=accept
```

### Étape 6 : Tester

```bash
# Depuis votre machine locale
curl http://<IP_INSTANCE>:8080/health

# Accéder au dashboard
open http://<IP_INSTANCE>:8080/dashboard
```

---

## Option 2 : Serverless Containers

**Recommandé pour** : Production, auto-scaling, pay-per-use

### Étape 1 : Créer le namespace Container Registry

```bash
scw registry namespace create name=moaudit region=fr-par
```

### Étape 2 : Build et push de l'image

```bash
# Build local
docker build -t moaudit-mel:latest .

# Login au registry Scaleway
scw registry login

# Tag l'image
docker tag moaudit-mel:latest rg.fr-par.scw.cloud/moaudit/moaudit-mel:latest

# Push
docker push rg.fr-par.scw.cloud/moaudit/moaudit-mel:latest
```

### Étape 3 : Créer le Serverless Container

Via console :
1. Allez sur [console.scaleway.com/containers](https://console.scaleway.com/containers)
2. **Create namespace** puis **Deploy a container**
3. Sélectionnez votre image depuis le registry
4. Configurez :
   - **Port** : 8080
   - **Resources** : 1 vCPU, 2GB RAM
   - **Scaling** : Min 0, Max 5
   - **Environment Variables** :
     - `MISTRAL_API_KEY` = votre_clé
     - `PORT` = 8080
5. Déployez

Via CLI :
```bash
# Créer namespace
scw container namespace create name=moaudit-ns region=fr-par

# Créer et déployer le container
scw container container create \
  namespace-id=<NAMESPACE_ID> \
  name=moaudit-mel \
  registry-image=rg.fr-par.scw.cloud/moaudit/moaudit-mel:latest \
  port=8080 \
  cpu-limit=1000 \
  memory-limit=2048 \
  min-scale=0 \
  max-scale=5 \
  environment-variables.MISTRAL_API_KEY=<VOTRE_CLE> \
  region=fr-par

# Déployer
scw container container deploy <CONTAINER_ID> region=fr-par
```

### Étape 4 : Obtenir l'URL

```bash
scw container container list region=fr-par
# Note the domain_name
```

L'application sera accessible sur `https://<container-name>.functions.fnc.fr-par.scw.cloud`

---

## Option 3 : Instance GPU

**Recommandé pour** : Parsing de gros volumes de PDF, modèles LLM locaux

### Types disponibles

| Type | GPU | Prix/heure |
|------|-----|------------|
| GPU-3070-S | RTX 3070 | ~€0.80 |
| RENDER-S | P100 | ~€1.00 |
| L4-1-24G | L4 24GB | ~€0.70 |

### Déploiement

```bash
# Créer instance GPU
scw instance server create \
  type=GPU-3070-S \
  zone=fr-par-2 \
  image=ubuntu_jammy_gpu_os_12 \
  name=moaudit-gpu

# Se connecter
ssh root@<IP>

# Les drivers NVIDIA sont pré-installés
nvidia-smi

# Installer Docker avec support GPU
curl -fsSL https://get.docker.com | sh
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | tee /etc/apt/sources.list.d/nvidia-docker.list
apt-get update && apt-get install -y nvidia-container-toolkit
systemctl restart docker

# Lancer avec GPU
docker run --gpus all -p 8080:8080 moaudit-mel:latest
```

---

## Configuration Post-Déploiement

### Configurer un nom de domaine (optionnel)

1. Achetez/utilisez un domaine sur Scaleway Domains
2. Créez un enregistrement A pointant vers l'IP de l'instance
3. Configurez HTTPS avec Let's Encrypt :

```bash
# Installer Caddy (reverse proxy avec HTTPS automatique)
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy

# Configurer Caddy
cat > /etc/caddy/Caddyfile << EOF
moaudit.votredomaine.com {
    reverse_proxy localhost:8080
}
EOF

# Redémarrer Caddy
systemctl restart caddy
```

### Monitoring

```bash
# Installer Prometheus Node Exporter
docker run -d --name node-exporter \
  --net="host" \
  --pid="host" \
  -v "/:/host:ro,rslave" \
  quay.io/prometheus/node-exporter:latest \
  --path.rootfs=/host

# Les métriques sont sur :9100/metrics
```

### Sauvegardes automatiques

Activez les snapshots automatiques dans la console Scaleway :
1. Instance > Volumes > Votre volume
2. Enable automatic snapshots
3. Configurez la fréquence (quotidien recommandé)

---

## Dépannage

### L'application ne démarre pas

```bash
# Vérifier les logs
docker compose logs -f

# Vérifier que le port est libre
netstat -tlnp | grep 8080

# Vérifier la mémoire disponible
free -h
```

### Erreur "Permission denied"

```bash
# Vérifier les permissions des volumes
chown -R 1000:1000 outputs/ data/uploads/
```

### Timeout sur le parsing

Augmentez les ressources de l'instance ou utilisez une instance GPU.

### Connexion refusée

```bash
# Vérifier le pare-feu Scaleway
scw instance security-group list

# Vérifier que l'application écoute sur 0.0.0.0
docker compose logs | grep "Uvicorn running"
```

### Clé Mistral invalide

```bash
# Tester la clé
curl https://api.mistral.ai/v1/models \
  -H "Authorization: Bearer $MISTRAL_API_KEY"
```

---

## Coûts estimés

| Configuration | Usage | Coût mensuel estimé |
|--------------|-------|---------------------|
| DEV1-S (test) | 24/7 | ~€7 |
| DEV1-M (dev) | 24/7 | ~€14 |
| GP1-XS (prod) | 24/7 | ~€60 |
| Serverless | 1000 req/jour | ~€5-15 |
| GPU (ponctuel) | 10h/mois | ~€8 |

---

## Commandes utiles

```bash
# Scaleway CLI
scw instance server list          # Lister les instances
scw instance server stop <ID>     # Arrêter une instance
scw instance server start <ID>    # Démarrer une instance
scw instance server delete <ID>   # Supprimer une instance

# Docker
docker compose up -d              # Démarrer en arrière-plan
docker compose down               # Arrêter
docker compose logs -f            # Voir les logs
docker compose restart            # Redémarrer
docker compose pull               # Mettre à jour l'image

# Monitoring
htop                              # Ressources système
docker stats                      # Ressources containers
```
