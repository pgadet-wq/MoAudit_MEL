#!/usr/bin/env python3
"""
Debug script pour comprendre comment Docling parse les réponses vLLM.
À exécuter SUR LE SERVEUR.
"""

import json
import sys

# Test avec une réponse vLLM simulée
MOCK_VLLM_RESPONSE = {
    "id": "test",
    "object": "chat.completion",
    "model": "ibm-granite/granite-docling-258M",
    "choices": [{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": "<loc_42><loc_18><loc_263><loc_32>TEST MEL DOCUMENT\n<loc_41><loc_40><loc_226><loc_49>ATA Chapter 21\n"
        },
        "finish_reason": "stop"
    }]
}


def test_doctag_parsing():
    """Teste le parsing des DocTags."""
    print("=" * 60)
    print("TEST 1: Parsing DocTags")
    print("=" * 60)

    try:
        from docling.datamodel.vlm_model_specs import ResponseFormat
        print(f"ResponseFormat values: {list(ResponseFormat)}")
    except Exception as e:
        print(f"Error: {e}")

    # Essayer d'importer le parser de DocTags
    try:
        from docling.backend.vlm_backend import VlmBackend
        print("VlmBackend imported OK")
    except ImportError as e:
        print(f"VlmBackend import error: {e}")

    try:
        from docling.models.vlm_model import VlmModel
        print("VlmModel imported OK")
    except ImportError as e:
        print(f"VlmModel import error: {e}")


def test_document_export():
    """Teste l'export document."""
    print("\n" + "=" * 60)
    print("TEST 2: Document Export")
    print("=" * 60)

    try:
        from docling.datamodel.document import DoclingDocument

        # Créer un document vide
        doc = DoclingDocument(name="test")
        print(f"Document pages: {len(doc.pages) if hasattr(doc, 'pages') else 'N/A'}")
        print(f"Document items: {len(list(doc.iterate_items())) if hasattr(doc, 'iterate_items') else 'N/A'}")

        md = doc.export_to_markdown()
        print(f"Empty doc markdown: '{md}'")

    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()


def test_vlm_pipeline_internals():
    """Inspecte le pipeline VLM."""
    print("\n" + "=" * 60)
    print("TEST 3: VLM Pipeline Internals")
    print("=" * 60)

    try:
        from docling.pipeline.vlm_pipeline import VlmPipeline
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat

        # Créer les options
        vlm_options = ApiVlmOptions(
            url="http://localhost:8000/v1/chat/completions",
            prompt="Convert this page to docling.",
            response_format=ResponseFormat.DOCTAGS,
            params={"model": "ibm-granite/granite-docling-258M"},
        )

        pipeline_options = VlmPipelineOptions(
            vlm_options=vlm_options,
            enable_remote_services=True
        )

        print(f"VLM Options: {vlm_options}")
        print(f"Pipeline Options: {pipeline_options}")

        # Inspecter les méthodes du pipeline
        import inspect
        members = inspect.getmembers(VlmPipeline, predicate=inspect.isfunction)
        print(f"\nVlmPipeline methods: {[m[0] for m in members]}")

    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()


def test_doctag_to_document():
    """Teste la conversion DocTags -> Document."""
    print("\n" + "=" * 60)
    print("TEST 4: DocTags to Document Conversion")
    print("=" * 60)

    doctags = "<loc_42><loc_18><loc_263><loc_32>TEST MEL DOCUMENT\n<loc_41><loc_40><loc_226><loc_49>ATA Chapter 21\n"

    try:
        # Chercher le parser de DocTags
        from docling.datamodel.document import DoclingDocument

        # Méthode 1: Essayer from_doctags si ça existe
        if hasattr(DoclingDocument, 'from_doctags'):
            doc = DoclingDocument.from_doctags(doctags)
            print(f"from_doctags: {doc}")

        # Méthode 2: Chercher dans les utilitaires
        try:
            from docling.utils.doctag_parser import parse_doctags
            result = parse_doctags(doctags)
            print(f"parse_doctags: {result}")
        except ImportError:
            print("doctag_parser not found")

        # Méthode 3: Chercher dans le backend
        try:
            from docling.backend.doctag_backend import DoctagBackend
            print("DoctagBackend found")
        except ImportError:
            print("DoctagBackend not found")

    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()


def inspect_docling_modules():
    """Liste tous les modules Docling disponibles."""
    print("\n" + "=" * 60)
    print("TEST 5: Docling Modules")
    print("=" * 60)

    import pkgutil
    import docling

    print(f"Docling path: {docling.__file__}")

    for importer, modname, ispkg in pkgutil.walk_packages(path=docling.__path__, prefix='docling.'):
        print(f"  {'[PKG]' if ispkg else '     '} {modname}")


def test_real_conversion():
    """Teste une vraie conversion avec logging détaillé."""
    print("\n" + "=" * 60)
    print("TEST 6: Real Conversion with Debug")
    print("=" * 60)

    import tempfile
    import fitz

    # Créer un PDF minimal
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((50, 100), "Hello World", fontsize=20)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        doc.save(f.name)
        pdf_path = f.name
    doc.close()

    print(f"Test PDF: {pdf_path}")

    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.pipeline.vlm_pipeline import VlmPipeline
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel.vlm_model_specs import ApiVlmOptions, ResponseFormat

        vlm_options = ApiVlmOptions(
            url="http://localhost:8000/v1/chat/completions",
            prompt="Convert this page to docling.",
            response_format=ResponseFormat.DOCTAGS,
            params={"model": "ibm-granite/granite-docling-258M"},
            timeout=60,
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

        print("Starting conversion...")
        result = converter.convert(pdf_path)

        print(f"\nResult type: {type(result)}")
        print(f"Result attributes: {dir(result)}")

        doc = result.document
        print(f"\nDocument type: {type(doc)}")
        print(f"Document attributes: {[a for a in dir(doc) if not a.startswith('_')]}")

        if hasattr(doc, 'pages'):
            print(f"Pages: {len(doc.pages)}")
            for i, page in enumerate(doc.pages):
                print(f"  Page {i}: {type(page)}")
                if hasattr(page, 'cells'):
                    print(f"    Cells: {len(page.cells) if page.cells else 0}")
                if hasattr(page, 'items'):
                    print(f"    Items: {list(page.items) if page.items else []}")

        if hasattr(doc, 'texts'):
            print(f"Texts: {doc.texts}")

        if hasattr(doc, 'tables'):
            print(f"Tables: {list(doc.tables)}")

        # Export
        md = doc.export_to_markdown()
        print(f"\nMarkdown ({len(md)} chars): {md[:500] if md else '(empty)'}")

        # Essayer d'autres exports
        if hasattr(doc, 'export_to_dict'):
            d = doc.export_to_dict()
            print(f"\nDict export keys: {list(d.keys()) if d else 'N/A'}")

    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

    finally:
        import os
        os.unlink(pdf_path)


if __name__ == "__main__":
    test_doctag_parsing()
    test_document_export()
    test_vlm_pipeline_internals()
    test_doctag_to_document()
    # inspect_docling_modules()  # Uncomment to see all modules
    test_real_conversion()
