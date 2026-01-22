"""
MoA_MEL PoC - Configuration
============================
Configuration centralisée pour le prototype d'audit MEL/MMEL
Mise à jour pour support services distants (Docling, Granite-Docling)
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Literal
from pathlib import Path
from enum import Enum


class ParsingBackend(str, Enum):
    """Backend de parsing disponibles"""
    LOCAL_DOCLING = "local_docling"      # Docling installé localement
    REMOTE_DOCLING = "remote_docling"    # Service Docling distant (Scaleway)
    MISTRAL_VLM = "mistral_vlm"          # Pixtral via API Mistral
    GEMINI = "gemini"                     # Google Gemini
    FALLBACK_PYMUPDF = "fallback"         # PyMuPDF basique


@dataclass
class DoclingServiceConfig:
    """Configuration du service Docling distant"""
    # URL du service Docling API
    service_url: str = field(default_factory=lambda: os.getenv(
        "DOCLING_SERVICE_URL", "http://localhost:8001"
    ))

    # Timeout pour les requêtes (secondes)
    timeout: int = 300

    # Nombre de retries
    max_retries: int = 3

    # Intervalle entre retries (secondes)
    retry_interval: float = 2.0

    # Activer le mode VLM (Granite-Docling)
    use_vlm: bool = True

    # Format de sortie préféré
    output_format: str = "json"  # json, markdown, html


@dataclass
class GraniteDoclingConfig:
    """Configuration du service Granite-Docling VLM"""
    # URL du service vLLM
    service_url: str = field(default_factory=lambda: os.getenv(
        "GRANITE_DOCLING_URL", "http://localhost:8000/v1"
    ))

    # Nom du modèle
    model_name: str = "ibm-granite/granite-docling-258M"

    # Timeout pour l'inférence (secondes)
    timeout: int = 120

    # Paramètres de génération
    max_tokens: int = 8192
    temperature: float = 0.0

    # Backend: vllm, transformers, mlx
    backend: str = "vllm"


@dataclass
class StorageConfig:
    """Configuration du stockage fichiers"""
    # Backend: local, s3, scaleway
    backend: str = field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local"))

    # Stockage local
    local_path: str = "data/uploads"

    # S3 / Scaleway Object Storage
    s3_endpoint_url: str = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL", ""))
    s3_access_key: str = field(default_factory=lambda: os.getenv("S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: os.getenv("S3_SECRET_KEY", ""))
    s3_bucket_name: str = field(default_factory=lambda: os.getenv("S3_BUCKET_NAME", "moaudit-documents"))
    s3_region: str = field(default_factory=lambda: os.getenv("S3_REGION", "fr-par"))


@dataclass
class RedisConfig:
    """Configuration Redis pour la file de jobs"""
    # URL Redis
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Activer Redis (sinon in-memory)
    enabled: bool = field(default_factory=lambda: os.getenv("REDIS_ENABLED", "false").lower() == "true")

    # Préfixe des clés
    key_prefix: str = "moaudit:"

    # TTL des jobs terminés (secondes)
    job_ttl: int = 86400  # 24h


@dataclass
class MistralConfig:
    """Configuration API Mistral"""
    api_key: str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""))
    base_url: str = "https://api.mistral.ai/v1"
    
    # Modèles
    vlm_model: str = "pixtral-12b-2409"  # Vision pour extraction tableaux
    embed_model: str = "mistral-embed"    # Embeddings sémantiques
    llm_model: str = "mistral-large-latest"  # Analyse et synthèse
    
    # Paramètres
    temperature: float = 0.1  # Basse pour précision
    max_tokens: int = 4096

@dataclass
class DatabaseConfig:
    """Configuration base de données"""
    # SQLite pour le PoC (simple, pas de setup)
    sqlite_path: str = "data/moa_mel.db"
    
    # PostgreSQL + pgvector pour production
    pg_host: str = os.getenv("PG_HOST", "localhost")
    pg_port: int = int(os.getenv("PG_PORT", "5432"))
    pg_database: str = os.getenv("PG_DATABASE", "moa_mel")
    pg_user: str = os.getenv("PG_USER", "postgres")
    pg_password: str = os.getenv("PG_PASSWORD", "")
    
    # Mode: "sqlite" ou "postgres"
    mode: str = "sqlite"

@dataclass 
class ParsingConfig:
    """Configuration du parsing PDF"""
    # Seuil de confiance pour validation automatique
    confidence_threshold: float = 0.85
    
    # Seuil HITL (en dessous = review humain)
    hitl_threshold: float = 0.70
    
    # Formats de sortie
    output_format: str = "json"  # json, csv, xlsx
    
    # Extraction spécifique MEL/MMEL
    expected_columns: list = field(default_factory=lambda: [
        "ata_chapter",
        "item_number", 
        "item_description",
        "category",  # A, B, C, D
        "repair_interval",
        "number_installed",
        "number_required",
        "remarks",
        "exceptions"
    ])

@dataclass
class MatchingConfig:
    """Configuration du matching MEL/MMEL"""
    # Matching exact
    exact_match_fields: list = field(default_factory=lambda: [
        "ata_chapter",
        "item_number"
    ])
    
    # Matching sémantique
    semantic_match_fields: list = field(default_factory=lambda: [
        "item_description",
        "remarks"
    ])
    
    # Seuil de similarité sémantique
    semantic_threshold: float = 0.85
    
    # Poids pour le score combiné
    exact_weight: float = 0.6
    semantic_weight: float = 0.4

@dataclass
class ComparisonConfig:
    """Configuration de la comparaison/audit"""
    # Catégories MEL (ordre de restrictivité)
    category_hierarchy: dict = field(default_factory=lambda: {
        "A": 1,  # Plus restrictif
        "B": 2,
        "C": 3,
        "D": 4   # Moins restrictif
    })
    
    # Verdicts possibles
    verdicts: dict = field(default_factory=lambda: {
        "COMPLIANT": {"code": "OK", "severity": "info", "description": "MEL = MMEL"},
        "MORE_RESTRICTIVE": {"code": "MR", "severity": "info", "description": "MEL plus restrictif que MMEL"},
        "LESS_RESTRICTIVE": {"code": "LR", "severity": "critical", "description": "MEL moins restrictif que MMEL - ÉCART MAJEUR"},
        "MISSING_IN_MEL": {"code": "MIM", "severity": "warning", "description": "Item MMEL absent dans MEL"},
        "MISSING_IN_MMEL": {"code": "MIR", "severity": "info", "description": "Item MEL absent dans MMEL (spécifique opérateur)"},
        "CATEGORY_MISMATCH": {"code": "CM", "severity": "high", "description": "Catégories différentes"},
        "REMARKS_DEVIATION": {"code": "RD", "severity": "medium", "description": "Écart dans les remarques/exceptions"}
    })
    
    # SLA pour HITL
    sla_hours: dict = field(default_factory=lambda: {
        "critical": 48,
        "high": 48,
        "medium": 24,
        "warning": 24,
        "info": 0  # Pas de review requis
    })

@dataclass
class HITLConfig:
    """Configuration Human-in-the-Loop"""
    # Répertoire des logs HITL
    log_directory: str = "logs/hitl"
    
    # Format des logs
    log_format: str = "json"  # json, csv
    
    # Activer les notifications
    notifications_enabled: bool = False
    
    # Email pour notifications (si activé)
    notification_email: str = ""

@dataclass
class OutputConfig:
    """Configuration des sorties"""
    # Répertoire de sortie
    output_directory: str = "outputs"
    
    # Formats de rapport
    report_formats: list = field(default_factory=lambda: ["json", "html"])
    
    # Template HTML
    html_template: str = "templates/audit_report.html"
    
    # Interface web
    web_interface_port: int = 8080

@dataclass
class AppConfig:
    """Configuration globale de l'application"""
    # Services externes
    docling: DoclingServiceConfig = field(default_factory=DoclingServiceConfig)
    granite_docling: GraniteDoclingConfig = field(default_factory=GraniteDoclingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)

    # Configuration existante
    mistral: MistralConfig = field(default_factory=MistralConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    parsing: ParsingConfig = field(default_factory=ParsingConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    comparison: ComparisonConfig = field(default_factory=ComparisonConfig)
    hitl: HITLConfig = field(default_factory=HITLConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # Backend de parsing à utiliser
    parsing_backend: ParsingBackend = field(default_factory=lambda: ParsingBackend(
        os.getenv("PARSING_BACKEND", "remote_docling")
    ))

    # Métadonnées
    version: str = "2.0.0"
    project_name: str = "MoA_MEL Audit"

    # Chemins
    base_path: Path = field(default_factory=lambda: Path(__file__).parent.parent)

    def __post_init__(self):
        """Création des répertoires nécessaires"""
        dirs = [
            self.base_path / "data",
            self.base_path / "data" / "uploads",
            self.base_path / "logs" / "hitl",
            self.base_path / "outputs",
            self.base_path / "static",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def get_docling_url(self) -> str:
        """Retourne l'URL complète du service Docling"""
        return f"{self.docling.service_url}/convert"

    def get_granite_url(self) -> str:
        """Retourne l'URL complète du service Granite-Docling"""
        return self.granite_docling.service_url

    def is_remote_parsing(self) -> bool:
        """Vérifie si le parsing utilise un service distant"""
        return self.parsing_backend == ParsingBackend.REMOTE_DOCLING

# Instance globale
config = AppConfig()

def load_config_from_env():
    """Charge la configuration depuis les variables d'environnement"""
    # Mistral
    config.mistral.api_key = os.getenv("MISTRAL_API_KEY", config.mistral.api_key)

    # Database
    config.database.pg_password = os.getenv("PG_PASSWORD", config.database.pg_password)

    # Docling Service
    config.docling.service_url = os.getenv("DOCLING_SERVICE_URL", config.docling.service_url)
    config.docling.use_vlm = os.getenv("DOCLING_USE_VLM", "true").lower() == "true"

    # Granite-Docling Service
    config.granite_docling.service_url = os.getenv("GRANITE_DOCLING_URL", config.granite_docling.service_url)

    # Storage
    config.storage.backend = os.getenv("STORAGE_BACKEND", config.storage.backend)

    # Redis
    config.redis.url = os.getenv("REDIS_URL", config.redis.url)
    config.redis.enabled = os.getenv("REDIS_ENABLED", "false").lower() == "true"

    # Parsing backend
    backend_env = os.getenv("PARSING_BACKEND", "remote_docling")
    try:
        config.parsing_backend = ParsingBackend(backend_env)
    except ValueError:
        config.parsing_backend = ParsingBackend.REMOTE_DOCLING

    return config


def get_service_urls() -> dict:
    """Retourne les URLs des services configurés"""
    return {
        "docling_service": config.docling.service_url,
        "granite_docling": config.granite_docling.service_url,
        "parsing_backend": config.parsing_backend.value,
        "storage_backend": config.storage.backend,
        "redis_enabled": config.redis.enabled
    }

if __name__ == "__main__":
    # Test de la configuration
    import json
    from dataclasses import asdict
    
    cfg = load_config_from_env()
    # Masquer l'API key pour l'affichage
    cfg_dict = asdict(cfg)
    cfg_dict['mistral']['api_key'] = "***MASKED***"
    print(json.dumps(cfg_dict, indent=2, default=str))
