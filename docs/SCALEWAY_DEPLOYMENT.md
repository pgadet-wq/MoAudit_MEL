# Guide de Déploiement Scaleway - MoA_MEL / IOSA Parser Viewer

Ce guide détaille la procédure complète pour déployer l'outil d'audit MEL/MMEL sur une instance Scaleway.

## Table des matières

1. [Prérequis](#prérequis)
2. [Création de l'instance Scaleway](#création-de-linstance-scaleway)
3. [Configuration de l'instance](#configuration-de-linstance)
4. [Déploiement de l'application](#déploiement-de-lapplication)
5. [Configuration Mistral AI](#configuration-mistral-ai)
6. [Utilisation du Dashboard](#utilisation-du-dashboard)
7. [Maintenance](#maintenance)
8. [Dépannage](#dépannage)

---

## Prérequis

### Compte Scaleway
- Compte Scaleway actif : https://console.scaleway.com
- Clé API Scaleway (optionnel, pour CLI)

### Clé API Mistral
- Compte Mistral AI : https://console.mistral.ai
- Clé API pour l'extraction LLM des documents PDF

### Outils locaux (optionnel)
```bash
# Scaleway CLI (pour automatisation)
brew install scw  # macOS
# ou
curl -s https://raw.githubusercontent.com/scaleway/scaleway-cli/master/scripts/get.sh | sh
```

---

## Création de l'instance Scaleway

### Étape 1 : Connexion à la console

1. Allez sur https://console.scaleway.com
2. Connectez-vous à votre compte

### Étape 2 : Créer une instance

1. **Compute** → **Instances** → **Create instance**

2. **Configuration recommandée :**

   | Paramètre | Valeur recommandée | Notes |
   |-----------|-------------------|-------|
   | Zone | fr-par-1 (Paris) | Faible latence vers Mistral AI |
   | Type | DEV1-M (3 vCPU, 4GB RAM) | Suffisant pour PoC |
   | Image | Ubuntu 22.04 LTS | Stable, support Docker |
   | Volume | 40 GB Block Storage | Pour les documents PDF |
   | IP | Flexible IP | IP publique fixe |

3. **Nom de l'instance :** `moamel-audit-server`

4. **SSH Keys :** Ajoutez votre clé SSH publique

5. Cliquez sur **Create instance**

### Étape 3 : Configuration du pare-feu (Security Groups)

1. Allez dans **Network** → **Security Groups**
2. Créez ou modifiez le groupe associé à votre instance
3. Ajoutez les règles entrantes (Inbound):

   | Port | Protocol | Source | Description |
   |------|----------|--------|-------------|
   | 22 | TCP | Votre IP | SSH |
   | 80 | TCP | 0.0.0.0/0 | HTTP |
   | 443 | TCP | 0.0.0.0/0 | HTTPS |
   | 8080 | TCP | 0.0.0.0/0 | API (dev) |

---

## Configuration de l'instance

### Étape 1 : Connexion SSH

```bash
# Remplacez par l'IP de votre instance
ssh root@<IP_INSTANCE>
```

### Étape 2 : Mise à jour système

```bash
apt update && apt upgrade -y
```

### Étape 3 : Installation de Docker

```bash
# Installation Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Installation Docker Compose
apt install -y docker-compose-plugin

# Vérification
docker --version
docker compose version
```

### Étape 4 : Installation des outils

```bash
apt install -y git curl htop
```

### Étape 5 : Cloner le projet

```bash
cd /opt
git clone https://github.com/pgadet-wq/MoAudit_MEL.git
cd MoAudit_MEL
```

---

## Déploiement de l'application

### Option A : Déploiement automatique (recommandé)

```bash
# Définir la clé Mistral API
export MISTRAL_API_KEY="votre-clé-api-mistral"

# Lancer le script de déploiement
./scripts/deploy-scaleway.sh dev
# ou pour production :
# ./scripts/deploy-scaleway.sh prod
```

### Option B : Déploiement manuel

1. **Créer le fichier .env :**

```bash
cat > .env << 'EOF'
# Configuration MoA_MEL
ENVIRONMENT=dev
MISTRAL_API_KEY=votre-clé-api-mistral
PORT=8080
PG_PASSWORD=mot_de_passe_securise_32_caracteres
EOF
```

2. **Construire et démarrer :**

```bash
# Mode développement
docker compose build
docker compose up -d

# Mode production (avec Nginx)
docker compose --profile production build
docker compose --profile production up -d
```

3. **Vérifier le déploiement :**

```bash
# Statut des containers
docker compose ps

# Logs
docker compose logs -f moamel

# Test de l'API
curl http://localhost:8080/health
```

---

## Configuration Mistral AI

### Obtenir une clé API

1. Allez sur https://console.mistral.ai
2. **API Keys** → **Create new key**
3. Copiez la clé générée

### Configurer dans MoA_MEL

```bash
# Éditer le fichier .env
nano .env

# Modifier la ligne :
MISTRAL_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Redémarrer l'application
docker compose restart moamel
```

### Modèles utilisés

| Modèle | Usage | Coût approximatif |
|--------|-------|-------------------|
| `pixtral-12b-2409` | Extraction visuelle des tableaux PDF | ~$0.15/1M tokens |
| `mistral-large-latest` | Analyse sémantique et structuration | ~$4/1M tokens |
| `mistral-embed` | Embeddings pour matching | ~$0.1/1M tokens |

---

## Utilisation du Dashboard

### Accès au Dashboard

- **URL :** `http://<IP_INSTANCE>:8080/dashboard`
- **API Docs :** `http://<IP_INSTANCE>:8080/docs`

### Fonctionnalités principales

#### 1. Upload de documents
```bash
# Via curl
curl -X POST "http://<IP>:8080/api/upload/mel" \
  -F "file=@chemin/vers/MEL.pdf"

curl -X POST "http://<IP>:8080/api/upload/mmel" \
  -F "file=@chemin/vers/MMEL.pdf"
```

#### 2. Lancer un audit
```bash
curl -X POST "http://<IP>:8080/api/audit/start" \
  -H "Content-Type: application/json" \
  -d '{
    "mel_path": "data/uploads/mel_xxx.pdf",
    "mmel_path": "data/uploads/mmel_xxx.pdf",
    "api_key": "sk-xxx"
  }'
```

#### 3. Consulter les résultats
```bash
# Statut
curl "http://<IP>:8080/api/audit/status/<job_id>"

# Résultat complet
curl "http://<IP>:8080/api/audit/result/<job_id>"
```

#### 4. Données de démonstration
```bash
curl "http://<IP>:8080/api/demo-data"
```

---

## Maintenance

### Logs et monitoring

```bash
# Logs en temps réel
docker compose logs -f moamel

# Logs PostgreSQL
docker compose logs -f postgres

# Utilisation des ressources
docker stats
```

### Sauvegarde

```bash
# Backup de la base de données
docker compose exec postgres pg_dump -U postgres moa_mel > backup_$(date +%Y%m%d).sql

# Backup des documents
tar -czvf documents_backup_$(date +%Y%m%d).tar.gz data/uploads outputs
```

### Mise à jour

```bash
cd /opt/MoAudit_MEL

# Récupérer les dernières modifications
git pull origin main

# Reconstruire et redémarrer
docker compose build
docker compose up -d
```

### Redémarrage

```bash
# Redémarrer un service
docker compose restart moamel

# Redémarrer tout
docker compose down && docker compose up -d
```

---

## Dépannage

### L'application ne démarre pas

```bash
# Vérifier les logs
docker compose logs moamel

# Vérifier la configuration
cat .env

# Vérifier les ports
netstat -tlnp | grep 8080
```

### Erreur "MISTRAL_API_KEY not set"

```bash
# Vérifier que la clé est définie
grep MISTRAL_API_KEY .env

# S'assurer qu'elle est valide sur console.mistral.ai
```

### Base de données inaccessible

```bash
# Vérifier que PostgreSQL est en cours d'exécution
docker compose ps postgres

# Tester la connexion
docker compose exec postgres psql -U postgres -c "SELECT 1"
```

### Problèmes de mémoire

```bash
# Vérifier l'utilisation mémoire
free -h
docker stats

# Si nécessaire, augmenter la RAM de l'instance Scaleway
```

### Réinitialisation complète

```bash
# ATTENTION : supprime toutes les données
docker compose down -v
rm -rf outputs/* logs/*
docker compose up -d
```

---

## Architecture du déploiement

```
┌──────────────────────────────────────────────────────────────┐
│                    Instance Scaleway                          │
│                      (DEV1-M)                                │
│                                                              │
│  ┌────────────────┐    ┌────────────────┐                   │
│  │     Nginx      │    │   MoA_MEL App  │                   │
│  │   (reverse     │───▶│   (FastAPI)    │                   │
│  │    proxy)      │    │   Port 8080    │                   │
│  │   Port 80/443  │    └───────┬────────┘                   │
│  └────────────────┘            │                            │
│                                │                            │
│                    ┌───────────▼────────────┐               │
│                    │     PostgreSQL         │               │
│                    │     + pgvector         │               │
│                    │     Port 5432          │               │
│                    └────────────────────────┘               │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    Volumes Docker                        ││
│  │  • data/uploads  - Documents PDF uploadés               ││
│  │  • outputs       - Résultats d'audit                    ││
│  │  • logs          - Logs HITL et application             ││
│  │  • postgres_data - Données PostgreSQL                   ││
│  └─────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS
                              ▼
                    ┌─────────────────┐
                    │   Mistral AI    │
                    │   API (🇫🇷)     │
                    └─────────────────┘
```

---

## Coûts estimés

| Ressource | Spécification | Coût mensuel |
|-----------|--------------|--------------|
| Instance DEV1-M | 3 vCPU, 4 GB RAM | ~€7/mois |
| Block Storage | 40 GB | ~€4/mois |
| IP Flexible | 1 IP | ~€3/mois |
| Mistral API | ~10 audits/mois | ~€10-20/mois |
| **Total estimé** | | **~€25-35/mois** |

---

## Support

- **Issues GitHub :** https://github.com/pgadet-wq/MoAudit_MEL/issues
- **Documentation Scaleway :** https://www.scaleway.com/en/docs/
- **Documentation Mistral :** https://docs.mistral.ai/
