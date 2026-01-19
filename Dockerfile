# MoA_MEL Audit Pipeline
# ========================
# Dockerfile pour déploiement sur Scaleway

FROM python:3.11-slim

LABEL maintainer="MoA Team"
LABEL description="MEL/MMEL Audit Pipeline - IOSA Parser Viewer"
LABEL version="1.0.0"

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app

# Créer l'utilisateur non-root
RUN groupadd -r moamel && useradd -r -g moamel moamel

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Répertoire de travail
WORKDIR ${APP_HOME}

# Copier les dépendances en premier (cache Docker)
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY src/ ./src/
COPY data/ ./data/
COPY docs/ ./docs/

# Créer les répertoires nécessaires
RUN mkdir -p outputs logs/hitl static data/uploads \
    && chown -R moamel:moamel ${APP_HOME}

# Passer à l'utilisateur non-root
USER moamel

# Exposer le port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Commande de démarrage
CMD ["python", "src/server.py"]
