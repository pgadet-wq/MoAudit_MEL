"""
Docling Service Configuration
=============================
Configuration management for the Docling API service.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from enum import Enum


class VLMBackend(str, Enum):
    """Supported VLM backends for document processing."""
    GRANITE_DOCLING = "granite_docling"
    GRANITE_DOCLING_VLLM = "granite_docling_vllm"
    SMOL_DOCLING = "smol_docling"
    LOCAL_ONLY = "local_only"  # No VLM, basic extraction


class StorageBackend(str, Enum):
    """Supported storage backends."""
    LOCAL = "local"
    S3 = "s3"
    SCALEWAY = "scaleway"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service Identity
    service_name: str = "docling-service"
    service_version: str = "1.0.0"
    debug: bool = False

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8001
    workers: int = 4

    # Granite-Docling VLM Configuration
    vlm_backend: VLMBackend = VLMBackend.GRANITE_DOCLING_VLLM
    granite_docling_url: str = Field(
        default="http://granite-docling:8000/v1",
        description="URL of the Granite-Docling vLLM service"
    )
    granite_model_name: str = "ibm-granite/granite-docling-258M"
    vlm_timeout: int = 120  # seconds
    vlm_max_retries: int = 3

    # Docling Processing Configuration
    enable_ocr: bool = True
    enable_table_structure: bool = True
    enable_code_enrichment: bool = True
    enable_formula_enrichment: bool = True
    table_mode: str = "accurate"  # "fast" or "accurate"
    ocr_engine: str = "rapidocr"  # rapidocr, tesseract, easyocr
    max_pages: Optional[int] = None  # None = no limit
    max_file_size_mb: int = 100
    document_timeout: int = 300  # seconds

    # Storage Configuration
    storage_backend: StorageBackend = StorageBackend.LOCAL
    local_storage_path: str = "/tmp/docling-uploads"

    # S3/Scaleway Object Storage
    s3_endpoint_url: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_bucket_name: str = "docling-documents"
    s3_region: str = "fr-par"

    # Processing Queue (Redis)
    redis_url: Optional[str] = None
    enable_queue: bool = False

    # Model Cache
    model_cache_path: str = "/root/.cache/docling/models"
    preload_models: bool = True

    # CORS
    cors_origins: list[str] = ["*"]

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds

    class Config:
        env_prefix = "DOCLING_"
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_vlm_config() -> dict:
    """Get VLM configuration based on backend selection."""
    if settings.vlm_backend == VLMBackend.LOCAL_ONLY:
        return {"use_vlm": False}

    return {
        "use_vlm": True,
        "vlm_backend": settings.vlm_backend.value,
        "vlm_endpoint": settings.granite_docling_url,
        "vlm_model": settings.granite_model_name,
        "vlm_timeout": settings.vlm_timeout,
    }


def get_pipeline_config() -> dict:
    """Get Docling pipeline configuration."""
    return {
        "do_ocr": settings.enable_ocr,
        "do_table_structure": settings.enable_table_structure,
        "do_code_enrichment": settings.enable_code_enrichment,
        "do_formula_enrichment": settings.enable_formula_enrichment,
        "table_structure_options": {
            "mode": settings.table_mode.upper()
        },
        "ocr_options": {
            "engine": settings.ocr_engine
        },
        "max_num_pages": settings.max_pages,
        "document_timeout": settings.document_timeout,
    }
