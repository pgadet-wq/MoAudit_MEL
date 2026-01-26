#!/usr/bin/env python3
"""
Docling Service V3 - Avec proxy d'interception
===============================================
Ce service inclut un proxy HTTP qui intercepte toutes les requêtes de Docling vers vLLM
pour analyser si les images sont correctement envoyées.
"""

from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import tempfile
import os
import sys
import json
import base64
import logging
from datetime import datetime
from typing import Optional
import httpx
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("DoclingService")

# Configuration
VLLM_URL = "http://localhost:8000"
PROXY_PORT = 8001  # Le proxy écoute ici
MODEL_NAME = "ibm-granite/granite-docling-258M"

# Stockage des requêtes interceptées
intercepted_requests = []


class ProxyHandler(BaseHTTPRequestHandler):
    """Handler HTTP qui intercepte et forwarde les requêtes."""

    def log_message(self, format, *args):
        logger.debug(f"[PROXY] {args}")

    def do_POST(self):
        """Intercepte les requêtes POST et les forwarde à vLLM."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        # Logger la requête
        logger.info(f"[PROXY] POST {self.path}")
        logger.info(f"[PROXY] Headers: {dict(self.headers)}")

        # Analyser le body JSON
        try:
            payload = json.loads(body)
            self._analyze_payload(payload)
        except json.JSONDecodeError:
            logger.warning(f"[PROXY] Body non-JSON: {len(body)} bytes")

        # Forward vers vLLM
        target_url = f"{VLLM_URL}{self.path}"
        logger.info(f"[PROXY] Forwarding to: {target_url}")

        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    target_url,
                    content=body,
                    headers={"Content-Type": self.headers.get("Content-Type", "application/json")}
                )

            # Renvoyer la réponse
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in ['transfer-encoding', 'content-encoding']:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.content)

            logger.info(f"[PROXY] Response: {response.status_code}, {len(response.content)} bytes")

        except Exception as e:
            logger.error(f"[PROXY] Error: {e}")
            self.send_error(502, str(e))

    def do_GET(self):
        """Forward GET requests."""
        target_url = f"{VLLM_URL}{self.path}"
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(target_url)
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in ['transfer-encoding', 'content-encoding']:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.content)
        except Exception as e:
            self.send_error(502, str(e))

    def _analyze_payload(self, payload: dict):
        """Analyse le payload pour détecter les images."""
        global intercepted_requests

        analysis = {
            "timestamp": datetime.now().isoformat(),
            "model": payload.get("model"),
            "has_messages": "messages" in payload,
            "has_images": False,
            "image_count": 0,
            "image_sizes": [],
            "content_types": [],
        }

        messages = payload.get("messages", [])
        for msg in messages:
            content = msg.get("content", "")

            if isinstance(content, str):
                analysis["content_types"].append("text")
                logger.info(f"[PROXY] Message content (text): {content[:100]}...")

            elif isinstance(content, list):
                for item in content:
                    item_type = item.get("type", "unknown")
                    analysis["content_types"].append(item_type)

                    if item_type == "image_url":
                        img_url = item.get("image_url", {}).get("url", "")
                        if img_url.startswith("data:image"):
                            # Image base64 détectée !
                            b64_start = img_url.find(",") + 1
                            b64_data = img_url[b64_start:] if b64_start > 0 else ""
                            analysis["has_images"] = True
                            analysis["image_count"] += 1
                            analysis["image_sizes"].append(len(b64_data))
                            logger.info(f"[PROXY] ✓ IMAGE BASE64 DÉTECTÉE: {len(b64_data)} chars")
                        else:
                            logger.warning(f"[PROXY] ⚠ Image URL (non-base64): {img_url[:50]}...")

                    elif item_type == "text":
                        text = item.get("text", "")
                        logger.info(f"[PROXY] Text content: {text[:100]}...")

        # Verdict
        if analysis["has_images"]:
            logger.info(f"[PROXY] ✓✓✓ REQUÊTE AVEC {analysis['image_count']} IMAGE(S)")
        else:
            logger.warning(f"[PROXY] ⚠⚠⚠ REQUÊTE SANS IMAGE - Content types: {analysis['content_types']}")

        intercepted_requests.append(analysis)


def start_proxy():
    """Démarre le proxy HTTP en arrière-plan."""
    server = HTTPServer(('0.0.0.0', PROXY_PORT), ProxyHandler)
    logger.info(f"[PROXY] Démarré sur le port {PROXY_PORT}")
    server.serve_forever()


# Démarrer le proxy dans un thread
proxy_thread = threading.Thread(target=start_proxy, daemon=True)
proxy_thread.start()


# FastAPI App
app = FastAPI(title="Docling Service V3 - Debug", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "Docling Service V3 - Debug",
        "vllm_direct": VLLM_URL,
        "vllm_proxy": f"http://localhost:{PROXY_PORT}",
        "intercepted_requests": len(intercepted_requests)
    }


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{VLLM_URL}/health")
            granite_ok = r.status_code == 200
    except:
        granite_ok = False
    return {"status": "healthy" if granite_ok else "degraded", "granite_docling": granite_ok}


@app.get("/intercepted")
async def get_intercepted():
    """Retourne toutes les requêtes interceptées."""
    return {
        "count": len(intercepted_requests),
        "requests": intercepted_requests[-10:]  # Les 10 dernières
    }


@app.delete("/intercepted")
async def clear_intercepted():
    """Efface les requêtes interceptées."""
    global intercepted_requests
    intercepted_requests = []
    return {"status": "cleared"}


@app.post("/convert")
async def convert_document(file: UploadFile):
    """Conversion avec Docling via le proxy."""
    global intercepted_requests

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    # Clear les requêtes précédentes
    requests_before = len(intercepted_requests)

    logger.info("=" * 60)
    logger.info(f"CONVERSION: {file.filename}")
    logger.info("=" * 60)

    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.pipeline.vlm_pipeline import VlmPipeline
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat

        # Utiliser le PROXY au lieu de vLLM direct
        proxy_url = f"http://localhost:{PROXY_PORT}/v1/chat/completions"

        vlm_options = ApiVlmOptions(
            url=proxy_url,  # <-- VIA PROXY
            prompt="Convert this page to docling.",
            response_format=ResponseFormat.DOCTAGS,
            params={"model": MODEL_NAME},
            timeout=120,
            concurrency=1,
        )

        logger.info(f"VLM Options URL (via proxy): {vlm_options.url}")

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

        result = converter.convert(tmp_path)
        doc = result.document
        markdown = doc.export_to_markdown()

        # Analyser les requêtes interceptées pendant cette conversion
        new_requests = intercepted_requests[requests_before:]
        images_sent = sum(1 for r in new_requests if r.get("has_images"))

        logger.info(f"Conversion terminée:")
        logger.info(f"  Pages: {len(doc.pages) if hasattr(doc, 'pages') else 0}")
        logger.info(f"  Markdown: {len(markdown)} chars")
        logger.info(f"  Requêtes interceptées: {len(new_requests)}")
        logger.info(f"  Requêtes avec images: {images_sent}")

        return {
            "filename": file.filename,
            "markdown": markdown,
            "markdown_length": len(markdown),
            "pages": len(doc.pages) if hasattr(doc, 'pages') else 0,
            "debug": {
                "requests_intercepted": len(new_requests),
                "requests_with_images": images_sent,
                "requests_details": new_requests
            }
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Erreur: {e}")
        logger.error(tb)
        raise HTTPException(500, f"Erreur: {str(e)}\n{tb}")

    finally:
        os.unlink(tmp_path)


@app.post("/convert-direct")
async def convert_direct(file: UploadFile, page: int = 0):
    """Conversion directe (bypass Docling) pour comparaison."""
    import fitz

    content = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = fitz.open(tmp_path)
        total_pages = doc.page_count

        results = []
        pages_to_process = [page] if page >= 0 else range(min(total_pages, 5))

        for p in pages_to_process:
            if p >= total_pages:
                continue

            pdf_page = doc.load_page(p)
            zoom = 300 / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = pdf_page.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode('utf-8')

            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                            {"type": "text", "text": "Convert this page to docling."}
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
                results.append({"page": p, "doctags": doctags, "length": len(doctags)})
            else:
                results.append({"page": p, "error": r.text})

        doc.close()

        all_content = "\n\n".join(r.get("doctags", "") for r in results if "doctags" in r)

        return {
            "filename": file.filename,
            "total_pages": total_pages,
            "results": results,
            "combined_content": all_content,
            "combined_length": len(all_content)
        }

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
