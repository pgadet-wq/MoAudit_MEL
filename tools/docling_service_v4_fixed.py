#!/usr/bin/env python3
"""
Docling Service V4 - Avec correction du format DocTags
======================================================
Ce service corrige le format des DocTags de Granite-Docling pour être
compatible avec le parser de Docling.

Granite-Docling génère: <loc_42><loc_18><loc_263><loc_32>TEXT
Docling attend:         <text><loc_42><loc_18><loc_263><loc_32>TEXT</text>
"""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import os
import sys
import json
import base64
import re
import logging
from datetime import datetime
from typing import Optional
import httpx

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("DoclingService")

VLLM_URL = "http://localhost:8000"
MODEL_NAME = "ibm-granite/granite-docling-258M"

app = FastAPI(title="Docling Service V4 - Fixed", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def convert_doctags_format(raw_doctags: str) -> str:
    """
    Convertit les DocTags du format Granite-Docling vers le format Docling.

    Input:  <loc_42><loc_18><loc_263><loc_32>TEXT
    Output: <text><loc_42><loc_18><loc_263><loc_32>TEXT</text>
    """
    if not raw_doctags:
        return ""

    # Pattern pour une séquence de 4 coordonnées suivies de texte
    # <loc_X><loc_Y><loc_W><loc_H>texte
    pattern = r'(<loc_\d+><loc_\d+><loc_\d+><loc_\d+>)([^<]+)'

    def replace_match(match):
        coords = match.group(1)
        text = match.group(2).strip()
        if text:
            return f'<text>{coords}{text}</text>'
        return ''

    converted = re.sub(pattern, replace_match, raw_doctags)

    # Nettoyer les lignes vides
    lines = [line.strip() for line in converted.split('\n') if line.strip()]
    return '\n'.join(lines)


@app.get("/")
async def root():
    return {"service": "Docling Service V4 - Fixed", "version": "4.0.0"}


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{VLLM_URL}/health")
            granite_ok = r.status_code == 200
    except:
        granite_ok = False
    return {"status": "healthy" if granite_ok else "degraded", "granite_docling": granite_ok}


@app.post("/test/convert-format")
async def test_convert_format(raw: str):
    """Teste la conversion de format DocTags."""
    converted = convert_doctags_format(raw)
    return {"raw": raw, "converted": converted}


@app.post("/convert")
async def convert_document(file: UploadFile):
    """Conversion avec correction du format DocTags."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    logger.info(f"CONVERSION: {file.filename}")

    try:
        import fitz
        from PIL import Image
        import io
        from docling_core.types.doc.document import DocTagsDocument, DoclingDocument

        # Ouvrir le PDF
        pdf = fitz.open(tmp_path)
        total_pages = pdf.page_count
        logger.info(f"Pages: {total_pages}")

        all_doctags = []
        all_images = []

        for page_num in range(min(total_pages, 20)):  # Max 20 pages
            # Extraire l'image de la page
            page = pdf.load_page(page_num)
            zoom = 2.0  # scale=2.0 comme dans VlmPipelineOptions
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            pil_image = Image.open(io.BytesIO(img_bytes))

            # Encoder en base64 pour vLLM
            b64 = base64.b64encode(img_bytes).decode('utf-8')

            logger.info(f"Page {page_num}: {pix.width}x{pix.height}")

            # Appeler vLLM
            payload = {
                "model": MODEL_NAME,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": "Convert this page to docling."}
                    ]
                }],
                "max_tokens": 4096,
                "temperature": 0.0
            }

            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

            if r.status_code != 200:
                logger.error(f"vLLM error: {r.text}")
                continue

            response = r.json()
            raw_doctags = response.get("choices", [{}])[0].get("message", {}).get("content", "")

            logger.info(f"Page {page_num} raw DocTags: {len(raw_doctags)} chars")
            logger.debug(f"Raw: {raw_doctags[:200]}...")

            # CONVERSION DU FORMAT
            converted_doctags = convert_doctags_format(raw_doctags)
            logger.info(f"Page {page_num} converted DocTags: {len(converted_doctags)} chars")
            logger.debug(f"Converted: {converted_doctags[:200]}...")

            all_doctags.append(converted_doctags)
            all_images.append(pil_image)

        pdf.close()

        # Créer le document Docling
        if not all_doctags or not all_images:
            return {
                "filename": file.filename,
                "markdown": "",
                "markdown_length": 0,
                "pages": total_pages,
                "error": "No content extracted"
            }

        logger.info(f"Creating DocTagsDocument with {len(all_doctags)} pages...")

        dt_doc = DocTagsDocument.from_doctags_and_image_pairs(all_doctags, all_images)
        doc = DoclingDocument.load_from_doctags(dt_doc, file.filename)

        # Export
        markdown = doc.export_to_markdown()
        texts_count = len(list(doc.texts))
        tables_count = len(list(doc.tables))

        logger.info(f"Result: {len(markdown)} chars, {texts_count} texts, {tables_count} tables")

        return {
            "filename": file.filename,
            "markdown": markdown,
            "markdown_length": len(markdown),
            "pages": total_pages,
            "texts_count": texts_count,
            "tables_count": tables_count
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error: {e}\n{tb}")
        raise HTTPException(500, f"Erreur: {str(e)}\n{tb}")

    finally:
        os.unlink(tmp_path)


@app.post("/convert-direct")
async def convert_direct(file: UploadFile, page: int = 0):
    """Conversion directe (raw DocTags, sans conversion format)."""
    import fitz

    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        pdf = fitz.open(tmp_path)
        total_pages = pdf.page_count
        results = []

        pages_to_process = [page] if page >= 0 else range(min(total_pages, 10))

        for p in pages_to_process:
            if p >= total_pages:
                continue

            pdf_page = pdf.load_page(p)
            zoom = 300 / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = pdf_page.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode('utf-8')

            payload = {
                "model": MODEL_NAME,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": "Convert this page to docling."}
                    ]
                }],
                "max_tokens": 4096
            }

            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(f"{VLLM_URL}/v1/chat/completions", json=payload)

            if r.status_code == 200:
                response = r.json()
                raw = response.get("choices", [{}])[0].get("message", {}).get("content", "")
                converted = convert_doctags_format(raw)
                results.append({
                    "page": p,
                    "raw_doctags": raw,
                    "converted_doctags": converted,
                    "raw_length": len(raw),
                    "converted_length": len(converted)
                })
            else:
                results.append({"page": p, "error": r.text})

        pdf.close()

        return {
            "filename": file.filename,
            "total_pages": total_pages,
            "results": results
        }

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
