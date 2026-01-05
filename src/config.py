"""
MoA_MEL PoC - Configuration
============================
Configuration centralisée pour le prototype d'audit MEL/MMEL
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

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
    mistral: MistralConfig = field(default_factory=MistralConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    parsing: ParsingConfig = field(default_factory=ParsingConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    comparison: ComparisonConfig = field(default_factory=ComparisonConfig)
    hitl: HITLConfig = field(default_factory=HITLConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    
    # Métadonnées
    version: str = "1.0.0-poc"
    project_name: str = "MoA_MEL Audit PoC"
    
    # Chemins
    base_path: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    
    def __post_init__(self):
        """Création des répertoires nécessaires"""
        dirs = [
            self.base_path / "data",
            self.base_path / "logs" / "hitl",
            self.base_path / "outputs",
            self.base_path / "static",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

# Instance globale
config = AppConfig()

def load_config_from_env():
    """Charge la configuration depuis les variables d'environnement"""
    config.mistral.api_key = os.getenv("MISTRAL_API_KEY", config.mistral.api_key)
    config.database.pg_password = os.getenv("PG_PASSWORD", config.database.pg_password)
    return config

if __name__ == "__main__":
    # Test de la configuration
    import json
    from dataclasses import asdict
    
    cfg = load_config_from_env()
    # Masquer l'API key pour l'affichage
    cfg_dict = asdict(cfg)
    cfg_dict['mistral']['api_key'] = "***MASKED***"
    print(json.dumps(cfg_dict, indent=2, default=str))
