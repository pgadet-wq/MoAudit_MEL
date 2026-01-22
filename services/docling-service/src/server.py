"""
Docling API Service
===================
FastAPI wrapper around Docling library for remote PDF/document conversion.
Integrates with Granite-Docling VLM for enhanced extraction.
"""

import os
import uuid
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from loguru import logger
import httpx

from config import settings, get_vlm_config, get_pipeline_config

# Conditional imports for Docling
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning("Docling not installed - running in limited mode")


# ============================================================================
# Data Models
# ============================================================================

class ConversionRequest(BaseModel):
    """Request model for document conversion."""
    source_url: Optional[str] = Field(None, description="URL of document to convert")
    output_format: str = Field("json", description="Output format: json, markdown, html, text")
    enable_ocr: bool = Field(True, description="Enable OCR for scanned documents")
    enable_tables: bool = Field(True, description="Enable table structure extraction")
    use_vlm: bool = Field(True, description="Use Granite-Docling VLM for enhanced extraction")
    max_pages: Optional[int] = Field(None, description="Maximum pages to process")


class ConversionResult(BaseModel):
    """Result of document conversion."""
    job_id: str
    status: str  # pending, processing, completed, failed
    filename: str
    pages_processed: int = 0
    total_pages: int = 0
    output_format: str
    result: Optional[dict] = None
    error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    docling_available: bool
    vlm_backend: str
    vlm_status: str
    timestamp: datetime


class BatchConversionRequest(BaseModel):
    """Request for batch document conversion."""
    documents: list[str] = Field(..., description="List of document URLs or paths")
    output_format: str = Field("json", description="Output format for all documents")
    use_vlm: bool = Field(True, description="Use VLM for all documents")


# ============================================================================
# Job Storage (In-memory for PoC, should use Redis in production)
# ============================================================================

conversion_jobs: dict[str, ConversionResult] = {}


# ============================================================================
# Docling Converter Singleton
# ============================================================================

class DoclingConverterManager:
    """Manages the Docling DocumentConverter instance."""

    _instance: Optional["DoclingConverterManager"] = None
    _converter: Optional["DocumentConverter"] = None
    _vlm_converter: Optional["DocumentConverter"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        """Initialize Docling converters."""
        if not DOCLING_AVAILABLE:
            logger.warning("Docling not available - skipping initialization")
            return

        logger.info("Initializing Docling converters...")

        # Standard converter (no VLM)
        try:
            self._converter = DocumentConverter()
            logger.info("Standard DocumentConverter initialized")
        except Exception as e:
            logger.error(f"Failed to initialize standard converter: {e}")

        # VLM-enabled converter
        if settings.vlm_backend != "local_only":
            try:
                await self._init_vlm_converter()
            except Exception as e:
                logger.error(f"Failed to initialize VLM converter: {e}")

    async def _init_vlm_converter(self):
        """Initialize VLM-enabled converter."""
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        # Check if Granite-Docling is available
        vlm_available = await self._check_vlm_health()

        if vlm_available:
            try:
                # Configure for remote VLM
                from docling.datamodel.vlm_model_specs import openai_compatible_vlm_options

                vlm_options = openai_compatible_vlm_options(
                    model=settings.granite_model_name,
                    base_url=settings.granite_docling_url
                )

                pipeline_options = PdfPipelineOptions(
                    do_ocr=settings.enable_ocr,
                    do_table_structure=settings.enable_table_structure,
                    vlm_model_specs=vlm_options
                )

                self._vlm_converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: pipeline_options
                    }
                )
                logger.info("VLM-enabled DocumentConverter initialized")
            except Exception as e:
                logger.warning(f"VLM converter initialization failed: {e}")
                self._vlm_converter = None
        else:
            logger.warning("Granite-Docling VLM not available - using standard converter")

    async def _check_vlm_health(self) -> bool:
        """Check if the VLM service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # vLLM health endpoint
                response = await client.get(f"{settings.granite_docling_url}/models")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"VLM health check failed: {e}")
            return False

    def get_converter(self, use_vlm: bool = True) -> Optional["DocumentConverter"]:
        """Get the appropriate converter."""
        if use_vlm and self._vlm_converter:
            return self._vlm_converter
        return self._converter

    @property
    def is_available(self) -> bool:
        return self._converter is not None


converter_manager = DoclingConverterManager()


# ============================================================================
# Application Lifecycle
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(f"Starting {settings.service_name} v{settings.service_version}")

    # Create storage directory
    os.makedirs(settings.local_storage_path, exist_ok=True)

    # Initialize Docling
    if settings.preload_models:
        await converter_manager.initialize()

    yield

    # Shutdown
    logger.info("Shutting down Docling service")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Docling API Service",
    description="REST API for document conversion using Docling + Granite-Docling VLM",
    version=settings.service_version,
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    vlm_status = "unavailable"

    if settings.vlm_backend != "local_only":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.granite_docling_url}/models")
                vlm_status = "healthy" if response.status_code == 200 else "unhealthy"
        except Exception:
            vlm_status = "unreachable"

    return HealthResponse(
        status="healthy" if converter_manager.is_available or not DOCLING_AVAILABLE else "degraded",
        service=settings.service_name,
        version=settings.service_version,
        docling_available=DOCLING_AVAILABLE and converter_manager.is_available,
        vlm_backend=settings.vlm_backend.value,
        vlm_status=vlm_status,
        timestamp=datetime.utcnow()
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.service_name,
        "version": settings.service_version,
        "docs": "/docs",
        "health": "/health"
    }


# ============================================================================
# Conversion Endpoints
# ============================================================================

@app.post("/convert", response_model=ConversionResult)
async def convert_document(
    file: UploadFile = File(...),
    output_format: str = Query("json", description="Output format: json, markdown, html, text"),
    use_vlm: bool = Query(True, description="Use Granite-Docling VLM"),
    enable_ocr: bool = Query(True, description="Enable OCR"),
    max_pages: Optional[int] = Query(None, description="Max pages to process"),
    background_tasks: BackgroundTasks = None
):
    """
    Convert a document (PDF, DOCX, etc.) to structured format.

    Supports:
    - PDF (with OCR, table extraction, VLM enhancement)
    - DOCX, XLSX, PPTX
    - Markdown, HTML
    - Images (PNG, JPEG, TIFF)
    """
    job_id = str(uuid.uuid4())
    start_time = datetime.utcnow()

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Check file size
    file_content = await file.read()
    file_size_mb = len(file_content) / (1024 * 1024)

    if file_size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {file_size_mb:.1f}MB (max: {settings.max_file_size_mb}MB)"
        )

    # Create job record
    job = ConversionResult(
        job_id=job_id,
        status="processing",
        filename=file.filename,
        output_format=output_format,
        created_at=start_time
    )
    conversion_jobs[job_id] = job

    # Save file temporarily
    temp_path = Path(settings.local_storage_path) / f"{job_id}_{file.filename}"

    try:
        with open(temp_path, "wb") as f:
            f.write(file_content)

        # Process document
        result = await _process_document(
            file_path=str(temp_path),
            output_format=output_format,
            use_vlm=use_vlm,
            enable_ocr=enable_ocr,
            max_pages=max_pages
        )

        # Update job
        job.status = "completed"
        job.result = result.get("content")
        job.pages_processed = result.get("pages_processed", 0)
        job.total_pages = result.get("total_pages", 0)
        job.completed_at = datetime.utcnow()
        job.processing_time_ms = int((job.completed_at - start_time).total_seconds() * 1000)

    except Exception as e:
        logger.error(f"Conversion failed for {file.filename}: {e}")
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.utcnow()

    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()

    return job


@app.post("/convert/url", response_model=ConversionResult)
async def convert_from_url(request: ConversionRequest):
    """Convert a document from URL."""
    if not request.source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    job_id = str(uuid.uuid4())
    start_time = datetime.utcnow()

    # Create job record
    job = ConversionResult(
        job_id=job_id,
        status="processing",
        filename=request.source_url.split("/")[-1],
        output_format=request.output_format,
        created_at=start_time
    )
    conversion_jobs[job_id] = job

    try:
        # Download file
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(request.source_url)
            response.raise_for_status()

        # Save temporarily
        temp_path = Path(settings.local_storage_path) / f"{job_id}_{job.filename}"
        with open(temp_path, "wb") as f:
            f.write(response.content)

        # Process
        result = await _process_document(
            file_path=str(temp_path),
            output_format=request.output_format,
            use_vlm=request.use_vlm,
            enable_ocr=request.enable_ocr,
            max_pages=request.max_pages
        )

        job.status = "completed"
        job.result = result.get("content")
        job.pages_processed = result.get("pages_processed", 0)
        job.total_pages = result.get("total_pages", 0)
        job.completed_at = datetime.utcnow()
        job.processing_time_ms = int((job.completed_at - start_time).total_seconds() * 1000)

        # Cleanup
        temp_path.unlink()

    except httpx.HTTPError as e:
        job.status = "failed"
        job.error = f"Failed to download: {e}"
        job.completed_at = datetime.utcnow()
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.utcnow()

    return job


@app.get("/convert/{job_id}", response_model=ConversionResult)
async def get_conversion_status(job_id: str):
    """Get the status and result of a conversion job."""
    if job_id not in conversion_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return conversion_jobs[job_id]


@app.post("/convert/batch")
async def batch_convert(request: BatchConversionRequest, background_tasks: BackgroundTasks):
    """
    Convert multiple documents in batch.
    Returns job IDs for tracking.
    """
    job_ids = []

    for doc_url in request.documents:
        job_id = str(uuid.uuid4())
        job_ids.append(job_id)

        job = ConversionResult(
            job_id=job_id,
            status="pending",
            filename=doc_url.split("/")[-1],
            output_format=request.output_format,
            created_at=datetime.utcnow()
        )
        conversion_jobs[job_id] = job

        # Queue for background processing
        background_tasks.add_task(
            _process_batch_item,
            job_id=job_id,
            doc_url=doc_url,
            output_format=request.output_format,
            use_vlm=request.use_vlm
        )

    return {"batch_id": str(uuid.uuid4()), "job_ids": job_ids, "count": len(job_ids)}


# ============================================================================
# MEL/MMEL Specific Endpoints
# ============================================================================

@app.post("/convert/mel")
async def convert_mel_document(
    file: UploadFile = File(...),
    document_type: str = Query(..., description="MEL or MMEL"),
    aircraft_type: Optional[str] = Query(None, description="e.g., A320-214"),
    operator: Optional[str] = Query(None, description="Operator name for MEL")
):
    """
    Convert MEL/MMEL document with aviation-specific extraction.
    Optimized for equipment list table structures.
    """
    job_id = str(uuid.uuid4())
    start_time = datetime.utcnow()

    if document_type not in ["MEL", "MMEL"]:
        raise HTTPException(status_code=400, detail="document_type must be MEL or MMEL")

    # Read file
    file_content = await file.read()
    temp_path = Path(settings.local_storage_path) / f"{job_id}_{file.filename}"

    try:
        with open(temp_path, "wb") as f:
            f.write(file_content)

        # Process with VLM for better table extraction
        result = await _process_document(
            file_path=str(temp_path),
            output_format="json",
            use_vlm=True,  # Always use VLM for MEL/MMEL
            enable_ocr=True,
            max_pages=None
        )

        # Add MEL-specific metadata
        mel_result = {
            "job_id": job_id,
            "document_type": document_type,
            "aircraft_type": aircraft_type,
            "operator": operator if document_type == "MEL" else None,
            "filename": file.filename,
            "pages_processed": result.get("pages_processed", 0),
            "total_pages": result.get("total_pages", 0),
            "content": result.get("content"),
            "tables_extracted": result.get("tables_count", 0),
            "processing_time_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
            "status": "completed"
        }

        return mel_result

    except Exception as e:
        logger.error(f"MEL conversion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path.exists():
            temp_path.unlink()


# ============================================================================
# Internal Processing Functions
# ============================================================================

async def _process_document(
    file_path: str,
    output_format: str,
    use_vlm: bool,
    enable_ocr: bool,
    max_pages: Optional[int]
) -> dict:
    """Process a document using Docling."""

    if not DOCLING_AVAILABLE:
        # Fallback: basic extraction without Docling
        return await _fallback_extraction(file_path, output_format)

    converter = converter_manager.get_converter(use_vlm=use_vlm)

    if converter is None:
        raise ValueError("No Docling converter available")

    # Run conversion in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: converter.convert(file_path)
    )

    # Extract content based on format
    doc = result.document

    content = None
    if output_format == "json":
        content = doc.export_to_dict()
    elif output_format == "markdown":
        content = doc.export_to_markdown()
    elif output_format == "html":
        content = doc.export_to_html()
    elif output_format == "text":
        content = doc.export_to_text()
    else:
        content = doc.export_to_dict()

    # Count tables
    tables_count = len([item for item in doc.items if hasattr(item, 'table')])

    return {
        "content": content,
        "pages_processed": len(doc.pages) if hasattr(doc, 'pages') else 0,
        "total_pages": len(doc.pages) if hasattr(doc, 'pages') else 0,
        "tables_count": tables_count
    }


async def _fallback_extraction(file_path: str, output_format: str) -> dict:
    """Fallback extraction when Docling is not available."""
    import fitz  # PyMuPDF

    doc = fitz.open(file_path)
    pages_text = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        pages_text.append({
            "page": page_num + 1,
            "text": text
        })

    total_pages = len(doc)
    doc.close()

    if output_format == "json":
        content = {"pages": pages_text, "extraction_method": "fallback_pymupdf"}
    elif output_format == "markdown":
        content = "\n\n---\n\n".join([f"## Page {p['page']}\n\n{p['text']}" for p in pages_text])
    elif output_format == "text":
        content = "\n\n".join([p['text'] for p in pages_text])
    else:
        content = {"pages": pages_text}

    return {
        "content": content,
        "pages_processed": total_pages,
        "total_pages": total_pages,
        "tables_count": 0  # Fallback doesn't extract tables
    }


async def _process_batch_item(job_id: str, doc_url: str, output_format: str, use_vlm: bool):
    """Process a single item in batch conversion."""
    job = conversion_jobs.get(job_id)
    if not job:
        return

    job.status = "processing"
    start_time = datetime.utcnow()

    try:
        # Download
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(doc_url)
            response.raise_for_status()

        # Save
        temp_path = Path(settings.local_storage_path) / f"{job_id}_{job.filename}"
        with open(temp_path, "wb") as f:
            f.write(response.content)

        # Process
        result = await _process_document(
            file_path=str(temp_path),
            output_format=output_format,
            use_vlm=use_vlm,
            enable_ocr=True,
            max_pages=None
        )

        job.status = "completed"
        job.result = result.get("content")
        job.pages_processed = result.get("pages_processed", 0)
        job.completed_at = datetime.utcnow()
        job.processing_time_ms = int((job.completed_at - start_time).total_seconds() * 1000)

        temp_path.unlink()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.utcnow()


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.debug
    )
