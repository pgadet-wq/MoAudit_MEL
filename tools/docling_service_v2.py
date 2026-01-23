#!/usr/bin/env python3
"""
Docling Service V2 - Version avec diagnostic intégré
====================================================
Service FastAPI qui utilise Docling avec Granite-Docling VLM.
Inclut du logging détaillé pour debugger les problèmes de transmission d'images.

Déploiement sur Scaleway:
    scp docling_service_v2.py root@51.159.146.199:/opt/docling-service/server.py
    ssh root@51.159.146.199 "pkill -f 'python3 server.py'; cd /opt/docling-service && nohup python3 server.py > /var/log/docling-service.log 2>&1 &"
"""

from fastapi import FastAPI, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import tempfile
import os
import sys
import json
import base64
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import httpx
import asyncio

# Configuration du logging détaillé
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/docling-service-debug.log')
    ]
)
logger = logging.getLogger("DoclingService")

# Configuration
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000")
MODEL_NAME = os.getenv("MODEL_NAME", "ibm-granite/granite-docling-258M")
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))  # Limiter pour les tests

# Statistiques globales
stats = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_failed": 0,
    "vllm_calls": 0,
    "vllm_with_images": 0,
    "last_request": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management."""
    logger.info("=" * 60)
    logger.info("DOCLING SERVICE V2 - DÉMARRAGE")
    logger.info(f"vLLM URL: {VLLM_URL}")
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Max pages: {MAX_PAGES}")
    logger.info("=" * 60)
    yield
    logger.info("Service arrêté")


app = FastAPI(
    title="Docling Service V2",
    version="2.0.0",
    description="Service de conversion PDF avec Granite-Docling VLM",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Proxy HTTP pour intercepter les requêtes Docling → vLLM
# ============================================================================

class InterceptingTransport(httpx.BaseTransport):
    """Transport HTTP qui logge toutes les requêtes."""

    def __init__(self, wrapped: httpx.BaseTransport):
        self._wrapped = wrapped

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        logger.debug(f"[INTERCEPT] {request.method} {request.url}")

        # Analyser le body si c'est JSON
        if request.content:
            try:
                body = json.loads(request.content)
                self._analyze_request(body)
            except json.JSONDecodeError:
                logger.debug(f"  Body (non-JSON): {len(request.content)} bytes")

        response = self._wrapped.handle_request(request)
        logger.debug(f"  Response: {response.status_code}")

        return response

    def _analyze_request(self, body: dict):
        """Analyse le contenu d'une requête JSON."""
        if "messages" not in body:
            return

        stats["vllm_calls"] += 1

        for i, msg in enumerate(body.get("messages", [])):
            content = msg.get("content", "")

            if isinstance(content, list):
                # Format multimodal
                types = [c.get("type", "?") for c in content]
                logger.info(f"  Message {i} types: {types}")

                has_image = False
                for item in content:
                    if item.get("type") == "image_url":
                        img_url = item.get("image_url", {}).get("url", "")
                        if img_url.startswith("data:image"):
                            # Extraire la taille de l'image base64
                            b64_start = img_url.find(",") + 1
                            b64_data = img_url[b64_start:] if b64_start > 0 else ""
                            logger.info(f"  ✓ IMAGE DÉTECTÉE: {len(b64_data)} chars base64")
                            has_image = True
                        else:
                            logger.warning(f"  ⚠ Image URL non-data: {img_url[:50]}...")

                if has_image:
                    stats["vllm_with_images"] += 1
                else:
                    logger.warning("  ⚠ Requête multimodale SANS image!")

            elif isinstance(content, str):
                logger.debug(f"  Message {i} (text): {content[:100]}...")


def get_intercepting_client():
    """Crée un client HTTP avec interception."""
    transport = httpx.HTTPTransport()
    intercepting = InterceptingTransport(transport)
    return httpx.Client(transport=intercepting, timeout=120)


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/")
async def root():
    return {
        "service": "Docling Service V2",
        "version": "2.0.0",
        "vllm_url": VLLM_URL,
        "model": MODEL_NAME,
        "stats": stats
    }


@app.get("/health")
async def health():
    """Health check avec vérification vLLM."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{VLLM_URL}/health")
            granite_ok = r.status_code == 200
    except Exception as e:
        logger.warning(f"vLLM health check failed: {e}")
        granite_ok = False

    return {
        "status": "healthy" if granite_ok else "degraded",
        "granite_docling": granite_ok,
        "vllm_url": VLLM_URL,
        "stats": stats
    }


@app.get("/stats")
async def get_stats():
    """Statistiques détaillées."""
    return {
        "stats": stats,
        "analysis": {
            "vllm_calls_with_images_ratio": (
                stats["vllm_with_images"] / stats["vllm_calls"]
                if stats["vllm_calls"] > 0 else 0
            )
        }
    }


@app.post("/test/vllm-text")
async def test_vllm_text():
    """Test vLLM avec texte seul."""
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "Convert this page to docling."}],
        "max_tokens": 100
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

    return {
        "status_code": r.status_code,
        "response": r.json() if r.status_code == 200 else r.text
    }


@app.post("/test/vllm-image")
async def test_vllm_image(file: UploadFile):
    """Test vLLM avec une image uploadée."""
    content = await file.read()
    b64 = base64.b64encode(content).decode('utf-8')

    # Détecter le type MIME
    mime_type = "image/png"
    if file.filename.lower().endswith(".jpg") or file.filename.lower().endswith(".jpeg"):
        mime_type = "image/jpeg"

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"}
                    },
                    {
                        "type": "text",
                        "text": "Convert this page to docling."
                    }
                ]
            }
        ],
        "max_tokens": 4096
    }

    logger.info(f"Test vLLM avec image: {len(b64)} chars base64")

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

    response_data = r.json() if r.status_code == 200 else {"error": r.text}

    return {
        "status_code": r.status_code,
        "image_size_b64": len(b64),
        "response": response_data
    }


@app.post("/test/pdf-page")
async def test_pdf_page(file: UploadFile, page: int = 0):
    """Extrait une page PDF en image et teste avec vLLM directement."""
    import fitz  # PyMuPDF

    content = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = fitz.open(tmp_path)
        logger.info(f"PDF: {doc.page_count} pages, test page {page}")

        if page >= doc.page_count:
            raise HTTPException(400, f"Page {page} n'existe pas (max: {doc.page_count - 1})")

        pdf_page = doc.load_page(page)
        zoom = 300 / 72
        matrix = fitz.Matrix(zoom, zoom)
        pix = pdf_page.get_pixmap(matrix=matrix)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode('utf-8')

        doc.close()

        logger.info(f"Image extraite: {pix.width}x{pix.height}, {len(b64)} chars base64")

        # Envoyer à vLLM
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}
                        },
                        {
                            "type": "text",
                            "text": "Convert this page to docling."
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

        if r.status_code == 200:
            response = r.json()
            doctags = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            doctags = f"ERROR: {r.text}"

        return {
            "page": page,
            "image_size": f"{pix.width}x{pix.height}",
            "image_b64_length": len(b64),
            "vllm_status": r.status_code,
            "doctags_length": len(doctags),
            "doctags_preview": doctags[:1000] if doctags else "(vide)",
            "has_doctags": "<loc_" in doctags or "<doctag>" in doctags
        }

    finally:
        os.unlink(tmp_path)


@app.post("/convert")
async def convert_document(file: UploadFile, max_pages: Optional[int] = None):
    """
    Convertit un PDF en utilisant Docling + Granite-Docling VLM.
    Inclut du logging détaillé pour le debugging.
    """
    stats["requests_total"] += 1
    stats["last_request"] = datetime.now().isoformat()

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    logger.info(f"=" * 60)
    logger.info(f"CONVERSION: {file.filename}")
    logger.info(f"Taille: {len(content)} bytes")
    logger.info(f"=" * 60)

    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.pipeline.vlm_pipeline import VlmPipeline
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat

        logger.info("Imports Docling OK")

        # Configurer les options VLM
        vlm_options = ApiVlmOptions(
            url=f"{VLLM_URL}/v1/chat/completions",
            prompt="Convert this page to docling.",
            response_format=ResponseFormat.DOCTAGS,
            params={"model": MODEL_NAME},
            timeout=120,
            concurrency=1,  # Séquentiel pour debug
        )

        logger.info(f"VLM Options:")
        logger.info(f"  url: {vlm_options.url}")
        logger.info(f"  model: {vlm_options.params.get('model')}")
        logger.info(f"  response_format: {vlm_options.response_format}")

        pipeline_options = VlmPipelineOptions(
            vlm_options=vlm_options,
            enable_remote_services=True
        )

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )
            }
        )

        logger.info("Démarrage conversion Docling...")

        # Reset compteurs pour cette requête
        initial_vllm_calls = stats["vllm_calls"]
        initial_with_images = stats["vllm_with_images"]

        result = converter.convert(tmp_path)
        doc = result.document

        # Calcul des stats de cette requête
        vllm_calls_this_request = stats["vllm_calls"] - initial_vllm_calls
        with_images_this_request = stats["vllm_with_images"] - initial_with_images

        markdown = doc.export_to_markdown()
        pages_count = len(doc.pages) if hasattr(doc, 'pages') else 0

        logger.info(f"Conversion terminée:")
        logger.info(f"  Pages: {pages_count}")
        logger.info(f"  Markdown: {len(markdown)} chars")
        logger.info(f"  Requêtes vLLM: {vllm_calls_this_request}")
        logger.info(f"  Requêtes avec images: {with_images_this_request}")
        logger.info(f"  Preview: {markdown[:500] if markdown else '(vide)'}")

        if len(markdown) == 0:
            logger.warning("⚠ MARKDOWN VIDE!")
            if vllm_calls_this_request == 0:
                logger.error("  → Aucune requête vLLM envoyée!")
            elif with_images_this_request == 0:
                logger.error("  → Requêtes vLLM sans images!")

        stats["requests_success"] += 1

        return {
            "filename": file.filename,
            "markdown": markdown,
            "markdown_length": len(markdown),
            "pages": pages_count,
            "debug": {
                "vllm_calls": vllm_calls_this_request,
                "vllm_with_images": with_images_this_request,
                "images_ratio": with_images_this_request / vllm_calls_this_request if vllm_calls_this_request > 0 else 0
            }
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Erreur conversion: {e}")
        logger.error(tb)
        stats["requests_failed"] += 1
        raise HTTPException(500, f"Erreur: {str(e)}\n{tb}")

    finally:
        os.unlink(tmp_path)


@app.post("/convert-direct")
async def convert_direct(file: UploadFile, page: int = 0):
    """
    Conversion DIRECTE sans Docling - extrait page PDF → vLLM → markdown.
    Utile pour bypasser Docling et tester la chaîne minimale.
    """
    import fitz

    content = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = fitz.open(tmp_path)
        total_pages = doc.page_count
        logger.info(f"Conversion directe: {total_pages} pages, traitement page {page}")

        results = []

        # Traiter une seule page ou toutes
        pages_to_process = [page] if page >= 0 else range(min(total_pages, MAX_PAGES))

        for p in pages_to_process:
            if p >= total_pages:
                continue

            pdf_page = doc.load_page(p)
            zoom = 300 / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = pdf_page.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode('utf-8')

            logger.info(f"Page {p}: {pix.width}x{pix.height}")

            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"}
                            },
                            {
                                "type": "text",
                                "text": "Convert this page to docling."
                            }
                        ]
                    }
                ],
                "max_tokens": 4096
            }

            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

            if r.status_code == 200:
                response = r.json()
                doctags = response.get("choices", [{}])[0].get("message", {}).get("content", "")
                results.append({
                    "page": p,
                    "doctags": doctags,
                    "length": len(doctags)
                })
            else:
                results.append({
                    "page": p,
                    "error": r.text
                })

        doc.close()

        # Concaténer tous les DocTags
        all_content = "\n\n".join(r.get("doctags", "") for r in results if "doctags" in r)

        return {
            "filename": file.filename,
            "total_pages": total_pages,
            "processed_pages": len(results),
            "results": results,
            "combined_content": all_content,
            "combined_length": len(all_content)
        }

    finally:
        os.unlink(tmp_path)


@app.get("/debug/docling-info")
async def docling_info():
    """Informations sur l'installation Docling."""
    info = {}

    try:
        import docling
        info["docling_version"] = getattr(docling, "__version__", "unknown")
        info["docling_path"] = docling.__file__
    except ImportError as e:
        info["docling_error"] = str(e)

    try:
        from docling.datamodel.vlm_model_specs import ApiVlmOptions
        import inspect
        sig = inspect.signature(ApiVlmOptions.__init__)
        info["ApiVlmOptions_params"] = list(sig.parameters.keys())
    except Exception as e:
        info["ApiVlmOptions_error"] = str(e)

    try:
        from docling.pipeline.vlm_pipeline import VlmPipeline
        info["VlmPipeline"] = "OK"
    except Exception as e:
        info["VlmPipeline_error"] = str(e)

    return info


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
