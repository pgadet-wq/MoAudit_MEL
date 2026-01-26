#!/usr/bin/env python3
"""
Docling VLM Diagnostic Tool
============================
Ce script diagnostique la communication entre Docling et le modèle VLM (vLLM/Granite-Docling).
Il intercepte et logge les requêtes pour identifier pourquoi les images ne sont pas transmises.

Usage:
    python docling_vlm_diagnostic.py <pdf_path> [--page N] [--verbose]
"""

import sys
import os
import json
import base64
import logging
import tempfile
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
import httpx

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DoclingDiagnostic")


VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000")
MODEL_NAME = "ibm-granite/granite-docling-258M"


def check_vllm_health():
    """Vérifie que vLLM est accessible et fonctionne."""
    logger.info(f"Vérification de vLLM: {VLLM_URL}")

    try:
        # Health check
        r = httpx.get(f"{VLLM_URL}/health", timeout=10)
        logger.info(f"  /health: {r.status_code}")

        # Modèles disponibles
        r = httpx.get(f"{VLLM_URL}/v1/models", timeout=10)
        if r.status_code == 200:
            models = r.json()
            logger.info(f"  Modèles: {json.dumps(models, indent=2)}")

        return True
    except Exception as e:
        logger.error(f"  Erreur: {e}")
        return False


def test_vllm_text_only():
    """Test vLLM avec une requête texte seule (sans image)."""
    logger.info("Test vLLM - Texte seul (sans image)")

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": "Convert this page to docling."}
        ],
        "max_tokens": 100
    }

    try:
        r = httpx.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=30
        )
        logger.info(f"  Status: {r.status_code}")

        if r.status_code == 200:
            response = r.json()
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"  Réponse (tronquée): {content[:200]}...")
            return True
        else:
            logger.error(f"  Erreur: {r.text}")
            return False
    except Exception as e:
        logger.error(f"  Exception: {e}")
        return False


def test_vllm_with_image(image_base64: str):
    """Test vLLM avec une image en base64."""
    logger.info("Test vLLM - Avec image")
    logger.info(f"  Taille image base64: {len(image_base64)} caractères")

    # Format multimodal OpenAI-compatible
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
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

    logger.debug(f"  Payload structure: model={payload['model']}, content_types={[c['type'] for c in payload['messages'][0]['content']]}")

    try:
        r = httpx.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=120
        )
        logger.info(f"  Status: {r.status_code}")

        if r.status_code == 200:
            response = r.json()
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"  Réponse ({len(content)} chars): {content[:500]}...")

            # Vérifier si c'est des DocTags valides
            if "<loc_" in content or "<doctag>" in content:
                logger.info("  ✓ DocTags détectés dans la réponse!")
            else:
                logger.warning("  ⚠ Pas de DocTags dans la réponse")

            return True, content
        else:
            logger.error(f"  Erreur: {r.text[:500]}")
            return False, r.text
    except Exception as e:
        logger.error(f"  Exception: {e}")
        return False, str(e)


def pdf_page_to_base64(pdf_path: str, page_num: int = 0) -> str:
    """Convertit une page PDF en image base64."""
    import fitz  # PyMuPDF

    logger.info(f"Conversion PDF → Image: page {page_num}")

    doc = fitz.open(pdf_path)
    logger.info(f"  Pages totales: {len(doc)}")

    page = doc.load_page(page_num)

    # Résolution pour VLM (300 DPI recommandé)
    zoom = 300 / 72  # 72 DPI par défaut
    matrix = fitz.Matrix(zoom, zoom)

    pix = page.get_pixmap(matrix=matrix)
    img_bytes = pix.tobytes("png")

    logger.info(f"  Image: {pix.width}x{pix.height}, {len(img_bytes)} bytes")

    doc.close()

    return base64.b64encode(img_bytes).decode('utf-8')


def test_docling_api_options():
    """Teste les options ApiVlmOptions de Docling."""
    logger.info("Test configuration Docling ApiVlmOptions")

    try:
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.pipeline.vlm_pipeline import VlmPipeline

        logger.info("  ✓ Imports Docling réussis")

        # Afficher les attributs de ApiVlmOptions
        import inspect
        sig = inspect.signature(ApiVlmOptions.__init__)
        params = list(sig.parameters.keys())
        logger.info(f"  ApiVlmOptions params: {params}")

        # Créer une instance pour voir les valeurs par défaut
        options = ApiVlmOptions(
            url=f"{VLLM_URL}/v1/chat/completions",
            prompt="Convert this page to docling.",
            response_format=ResponseFormat.DOCTAGS,
            params={"model": MODEL_NAME},
            timeout=120,
        )

        logger.info(f"  Options créées:")
        logger.info(f"    url: {options.url}")
        logger.info(f"    prompt: {options.prompt}")
        logger.info(f"    response_format: {options.response_format}")
        logger.info(f"    params: {options.params}")

        return True
    except ImportError as e:
        logger.error(f"  Erreur import: {e}")
        return False
    except Exception as e:
        logger.error(f"  Exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_docling_conversion(pdf_path: str, page_num: Optional[int] = None):
    """Teste la conversion Docling complète avec interception des requêtes."""
    logger.info(f"Test conversion Docling complète: {pdf_path}")

    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.pipeline.vlm_pipeline import VlmPipeline
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat

        # Intercepter les requêtes HTTP
        original_post = httpx.Client.post
        request_log = []

        def intercepted_post(self, url, **kwargs):
            logger.info(f"  [INTERCEPT] POST {url}")

            if "json" in kwargs:
                payload = kwargs["json"]
                logger.info(f"    Payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}")

                if isinstance(payload, dict) and "messages" in payload:
                    messages = payload["messages"]
                    for i, msg in enumerate(messages):
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            types = [c.get("type") for c in content]
                            logger.info(f"    Message {i} content types: {types}")

                            # Chercher les images
                            for c in content:
                                if c.get("type") == "image_url":
                                    img_url = c.get("image_url", {}).get("url", "")
                                    if img_url.startswith("data:"):
                                        logger.info(f"    ✓ Image base64 détectée ({len(img_url)} chars)")
                                    else:
                                        logger.warning(f"    ⚠ Image URL non-base64: {img_url[:100]}")
                        else:
                            logger.info(f"    Message {i} content: {str(content)[:100]}...")

                request_log.append({
                    "url": str(url),
                    "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
                    "has_image": "image" in str(payload).lower()
                })

            return original_post(self, url, **kwargs)

        # Monkey-patch
        httpx.Client.post = intercepted_post

        try:
            vlm_options = ApiVlmOptions(
                url=f"{VLLM_URL}/v1/chat/completions",
                prompt="Convert this page to docling.",
                response_format=ResponseFormat.DOCTAGS,
                params={"model": MODEL_NAME},
                timeout=120,
                concurrency=1,  # Séquentiel pour debug
            )

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

            logger.info("  Démarrage conversion...")
            result = converter.convert(pdf_path)

            doc = result.document
            markdown = doc.export_to_markdown()

            logger.info(f"  Résultat:")
            logger.info(f"    Pages: {len(doc.pages) if hasattr(doc, 'pages') else 'N/A'}")
            logger.info(f"    Markdown length: {len(markdown)}")
            logger.info(f"    Markdown preview: {markdown[:500] if markdown else '(vide)'}")

            logger.info(f"  Requêtes interceptées: {len(request_log)}")
            for req in request_log:
                logger.info(f"    - {req}")

            return markdown, request_log

        finally:
            # Restaurer
            httpx.Client.post = original_post

    except Exception as e:
        logger.error(f"  Exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, []


def run_full_diagnostic(pdf_path: str, page_num: int = 0):
    """Exécute le diagnostic complet."""
    print("=" * 70)
    print("DOCLING VLM DIAGNOSTIC")
    print(f"PDF: {pdf_path}")
    print(f"Date: {datetime.now().isoformat()}")
    print("=" * 70)

    results = {}

    # 1. Check vLLM
    print("\n[1/5] Vérification vLLM...")
    results["vllm_health"] = check_vllm_health()

    # 2. Test texte seul
    print("\n[2/5] Test vLLM - Texte seul...")
    results["vllm_text"] = test_vllm_text_only()

    # 3. Test avec image directe
    print("\n[3/5] Test vLLM - Avec image...")
    try:
        img_b64 = pdf_page_to_base64(pdf_path, page_num)
        success, response = test_vllm_with_image(img_b64)
        results["vllm_image"] = success
        results["vllm_image_response"] = response[:1000] if response else None
    except Exception as e:
        logger.error(f"Erreur: {e}")
        results["vllm_image"] = False
        results["vllm_image_error"] = str(e)

    # 4. Test config Docling
    print("\n[4/5] Test configuration Docling...")
    results["docling_config"] = test_docling_api_options()

    # 5. Test conversion complète
    print("\n[5/5] Test conversion Docling complète...")
    markdown, request_log = test_docling_conversion(pdf_path, page_num)
    results["docling_conversion"] = markdown is not None and len(markdown) > 0
    results["docling_markdown_length"] = len(markdown) if markdown else 0
    results["docling_requests"] = len(request_log)
    results["docling_requests_with_images"] = sum(1 for r in request_log if r.get("has_image"))

    # Résumé
    print("\n" + "=" * 70)
    print("RÉSUMÉ DIAGNOSTIC")
    print("=" * 70)

    for key, value in results.items():
        status = "✓" if value else "✗" if isinstance(value, bool) else value
        print(f"  {key}: {status}")

    # Conclusion
    print("\n" + "-" * 70)
    print("ANALYSE:")

    if not results.get("vllm_health"):
        print("  ❌ vLLM n'est pas accessible - vérifier le service")
    elif not results.get("vllm_image"):
        print("  ❌ vLLM ne répond pas correctement aux images - vérifier le modèle VLM")
    elif results.get("docling_requests_with_images", 0) == 0:
        print("  ❌ PROBLÈME IDENTIFIÉ: Docling n'envoie PAS d'images à vLLM!")
        print("     → Les requêtes interceptées ne contiennent pas de data:image base64")
        print("     → Vérifier la configuration ApiVlmOptions ou la version de Docling")
    elif results.get("docling_markdown_length", 0) == 0:
        print("  ❌ Docling envoie les images mais le markdown est vide")
        print("     → Vérifier le post-processing des DocTags")
    else:
        print("  ✓ Tout semble fonctionner!")

    print("-" * 70)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnostic Docling VLM")
    parser.add_argument("pdf_path", nargs="?", help="Chemin vers le PDF à tester")
    parser.add_argument("--page", type=int, default=0, help="Numéro de page à tester (défaut: 0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mode verbose")
    parser.add_argument("--vllm-url", default="http://localhost:8000", help="URL vLLM")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    VLLM_URL = args.vllm_url

    if args.pdf_path:
        run_full_diagnostic(args.pdf_path, args.page)
    else:
        # Mode rapide sans PDF
        print("Mode rapide (sans PDF)")
        check_vllm_health()
        test_vllm_text_only()
        test_docling_api_options()
