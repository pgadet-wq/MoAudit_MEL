#!/usr/bin/env python3
"""
MoA_MEL - Unified Parser
========================
Façade unifiant tous les parsers avec pattern Factory.

Usage:
    parser = UnifiedParser.create(api_key="...", backend="semantic")
    result = parser.parse_document("document.pdf", doc_type="MEL")
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

logger = logging.getLogger("UnifiedParser")


class ParserBackend(Enum):
    """Backends de parsing disponibles"""
    SEMANTIC = "semantic"      # LLM-based (Mistral Large)
    DOCLING = "docling"        # Docling pure (sans LLM)
    HYBRID = "hybrid"          # Docling + LLM enrichment
    MOCK = "mock"              # Données de test


@dataclass
class ParsedDocument:
    """Résultat unifié de parsing"""
    document_type: str              # MEL ou MMEL
    source_file: str
    parser_backend: str
    parsing_timestamp: str
    items: List[Dict[str, Any]]
    statistics: Dict[str, Any]
    warnings: List[str]

    @property
    def total_items(self) -> int:
        return len(self.items)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class UnifiedParser:
    """
    Parser unifié avec sélection automatique du backend.

    Priorise:
    1. Semantic (LLM) si api_key disponible
    2. Hybrid si Docling disponible
    3. Mock pour tests
    """

    def __init__(
        self,
        api_key: str = "",
        backend: ParserBackend = ParserBackend.HYBRID,
        llm_model: str = "mistral-large-latest"
    ):
        self.api_key = api_key
        self.backend = backend
        self.llm_model = llm_model

        # Initialiser les composants selon le backend
        self._init_components()

    def _init_components(self):
        """Initialise les composants de parsing"""
        self.semantic_parser = None
        self.continuity_resolver = None
        self.hybrid_parser = None

        # Import des composants V2
        try:
            from parsers.page_continuity_resolver import PageContinuityResolver, TableRowMerger
            self.continuity_resolver = PageContinuityResolver()
            self.table_merger = TableRowMerger()
            logger.info("PageContinuityResolver chargé")
        except ImportError as e:
            logger.warning(f"PageContinuityResolver non disponible: {e}")

        if self.api_key and self.backend in [ParserBackend.SEMANTIC, ParserBackend.HYBRID]:
            try:
                from parsers.semantic_parser import SemanticMELParser, HybridParser
                self.semantic_parser = SemanticMELParser(
                    api_key=self.api_key,
                    model=self.llm_model
                )
                self.hybrid_parser = HybridParser(api_key=self.api_key)
                logger.info(f"SemanticParser chargé (model: {self.llm_model})")
            except ImportError as e:
                logger.warning(f"SemanticParser non disponible: {e}")

    @classmethod
    def create(
        cls,
        api_key: str = "",
        backend: str = "auto"
    ) -> "UnifiedParser":
        """
        Factory method pour créer le parser optimal.

        Args:
            api_key: Clé API Mistral (optionnel)
            backend: "auto", "semantic", "docling", "hybrid", "mock"

        Returns:
            Instance configurée de UnifiedParser
        """
        # Déterminer le backend automatiquement
        if backend == "auto":
            if api_key:
                backend_enum = ParserBackend.SEMANTIC
            else:
                # Vérifier si Docling est disponible
                try:
                    from docling.document_converter import DocumentConverter
                    backend_enum = ParserBackend.DOCLING
                except ImportError:
                    backend_enum = ParserBackend.MOCK
        else:
            backend_enum = ParserBackend(backend)

        logger.info(f"Création UnifiedParser avec backend: {backend_enum.value}")
        return cls(api_key=api_key, backend=backend_enum)

    def parse_document(
        self,
        pdf_path: str,
        doc_type: str = "MEL"
    ) -> ParsedDocument:
        """
        Parse un document PDF.

        Args:
            pdf_path: Chemin vers le PDF
            doc_type: "MEL" ou "MMEL"

        Returns:
            ParsedDocument avec les items extraits
        """
        logger.info(f"Parsing {doc_type}: {pdf_path} (backend: {self.backend.value})")

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"Document non trouvé: {pdf_path}")

        warnings = []
        items = []

        # Sélection du pipeline selon le backend
        if self.backend == ParserBackend.MOCK:
            items = self._parse_mock(pdf_path, doc_type)

        elif self.backend == ParserBackend.DOCLING:
            items, warnings = self._parse_docling(pdf_path, doc_type)

        elif self.backend == ParserBackend.SEMANTIC:
            items, warnings = self._parse_semantic(pdf_path, doc_type)

        elif self.backend == ParserBackend.HYBRID:
            items, warnings = self._parse_hybrid(pdf_path, doc_type)

        # Enrichir les items avec métadonnées
        for item in items:
            item["document_type"] = doc_type
            item["source_document"] = path.name

        # Calculer les statistiques
        stats = self._compute_statistics(items)

        return ParsedDocument(
            document_type=doc_type,
            source_file=str(path),
            parser_backend=self.backend.value,
            parsing_timestamp=datetime.now().isoformat(),
            items=items,
            statistics=stats,
            warnings=warnings
        )

    def _parse_mock(self, pdf_path: str, doc_type: str) -> List[Dict]:
        """Génère des données mock pour tests"""
        logger.info("Utilisation du parser MOCK")

        return [
            {
                "ata_chapter": "21",
                "ata_section": "10",
                "item_number": "21-10-01",
                "item_description": f"[MOCK] Sample {doc_type} Item",
                "category": "C",
                "number_installed": "2",
                "number_required": "1",
                "remarks_raw": "(O) May be inoperative provided...",
                "extraction_method": "mock"
            }
        ]

    def _parse_docling(self, pdf_path: str, doc_type: str) -> tuple:
        """Parse avec Docling (extraction tables)"""
        warnings = []
        items = []

        try:
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            result = converter.convert(pdf_path)
            markdown = result.document.export_to_markdown()

            # Extraction basique regex
            items = self._extract_items_from_markdown(markdown)

        except ImportError:
            warnings.append("Docling non installé")
        except Exception as e:
            warnings.append(f"Erreur Docling: {e}")

        return items, warnings

    def _parse_semantic(self, pdf_path: str, doc_type: str) -> tuple:
        """Parse avec LLM sémantique"""
        warnings = []
        items = []

        if not self.semantic_parser:
            warnings.append("SemanticParser non disponible")
            return self._parse_docling(pdf_path, doc_type)

        try:
            # 1. Conversion Docling → Markdown
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(pdf_path)
            markdown = result.document.export_to_markdown()

            # 2. Résolution continuité multi-pages
            if self.continuity_resolver:
                pages = self._split_by_pages(markdown)
                blocks = self.continuity_resolver.process_markdown_pages(pages)
            else:
                blocks = [{"content": markdown, "source_pages": [0]}]

            # 3. Extraction sémantique par bloc
            for block in blocks:
                content = block.content if hasattr(block, 'content') else block.get('content', '')
                source_pages = block.source_pages if hasattr(block, 'source_pages') else block.get('source_pages', [])

                extraction = self.semantic_parser.parse_block(
                    content,
                    source_page=source_pages[0] if source_pages else 0
                )

                if extraction.success:
                    items.extend(extraction.items)
                else:
                    warnings.append(f"Extraction échouée page {source_pages}: {extraction.error}")

        except Exception as e:
            warnings.append(f"Erreur semantic parsing: {e}")
            # Fallback vers Docling
            return self._parse_docling(pdf_path, doc_type)

        return items, warnings

    def _parse_hybrid(self, pdf_path: str, doc_type: str) -> tuple:
        """Parse hybride: Docling + enrichissement LLM"""
        warnings = []

        # D'abord extraction Docling
        items, docling_warnings = self._parse_docling(pdf_path, doc_type)
        warnings.extend(docling_warnings)

        # Enrichissement LLM si disponible
        if self.hybrid_parser and items:
            try:
                enriched_items = []
                for item in items:
                    enriched = self.hybrid_parser.enrich_item(item)
                    enriched_items.append(enriched)
                items = enriched_items
            except Exception as e:
                warnings.append(f"Enrichissement LLM échoué: {e}")

        return items, warnings

    def _split_by_pages(self, markdown: str) -> List[str]:
        """Divise le markdown par pages"""
        import re

        patterns = [r'\n---\n', r'\nPage \d+\n', r'\n\[Page \d+\]']

        for pattern in patterns:
            parts = re.split(pattern, markdown)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]

        return [markdown]

    def _extract_items_from_markdown(self, markdown: str) -> List[Dict]:
        """Extraction regex basique depuis markdown"""
        import re

        items = []
        ata_pattern = r'(\d{2})-(\d{2})-(\d{2,3})([A-Z])?'

        for match in re.finditer(ata_pattern, markdown):
            chapter, section, item_num, suffix = match.groups()

            # Contexte autour du match
            start = max(0, match.start() - 50)
            end = min(len(markdown), match.end() + 300)
            context = markdown[start:end]

            item = {
                "ata_chapter": chapter,
                "ata_section": section,
                "item_number": f"{chapter}-{section}-{item_num.zfill(2)}{suffix or ''}",
                "item_description": self._extract_description(context),
                "category": self._extract_category(context),
                "number_installed": "-",
                "number_required": "-",
                "remarks_raw": self._extract_remarks(context),
                "extraction_method": "regex"
            }
            items.append(item)

        return items

    def _extract_description(self, context: str) -> str:
        """Extrait description depuis contexte"""
        import re
        match = re.search(r'\d{2}-\d{2}-\d{2,3}[A-Z]?\s+([^\n|]+)', context)
        return match.group(1).strip()[:200] if match else ""

    def _extract_category(self, context: str) -> str:
        """Extrait catégorie depuis contexte"""
        import re
        for cat in ['A', 'B', 'C', 'D']:
            if re.search(rf'\b{cat}\b', context[:100]):
                return cat
        return "C"

    def _extract_remarks(self, context: str) -> str:
        """Extrait remarks depuis contexte"""
        import re
        match = re.search(r'\([OM]\)[^|]*', context, re.IGNORECASE)
        return match.group(0).strip()[:500] if match else ""

    def _compute_statistics(self, items: List[Dict]) -> Dict[str, Any]:
        """Calcule les statistiques de parsing"""
        stats = {
            "total_items": len(items),
            "by_chapter": {},
            "by_category": {"A": 0, "B": 0, "C": 0, "D": 0},
            "by_method": {}
        }

        for item in items:
            # Par chapitre
            ch = item.get("ata_chapter", "00")
            stats["by_chapter"][ch] = stats["by_chapter"].get(ch, 0) + 1

            # Par catégorie
            cat = item.get("category", "")
            if cat in stats["by_category"]:
                stats["by_category"][cat] += 1

            # Par méthode d'extraction
            method = item.get("extraction_method", "unknown")
            stats["by_method"][method] = stats["by_method"].get(method, 0) + 1

        return stats


# ============== Fonctions utilitaires ==============

def parse_mel_document(pdf_path: str, api_key: str = "") -> ParsedDocument:
    """Shortcut pour parser un MEL"""
    parser = UnifiedParser.create(api_key=api_key)
    return parser.parse_document(pdf_path, doc_type="MEL")


def parse_mmel_document(pdf_path: str, api_key: str = "") -> ParsedDocument:
    """Shortcut pour parser un MMEL"""
    parser = UnifiedParser.create(api_key=api_key)
    return parser.parse_document(pdf_path, doc_type="MMEL")


# ============== CLI ==============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MoA_MEL Unified Parser")
    parser.add_argument("pdf", help="PDF à parser")
    parser.add_argument("--type", choices=["MEL", "MMEL"], default="MEL")
    parser.add_argument("--backend", choices=["auto", "semantic", "docling", "mock"], default="auto")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--output", "-o", help="Fichier JSON de sortie")

    args = parser.parse_args()

    unified_parser = UnifiedParser.create(api_key=args.api_key, backend=args.backend)
    result = unified_parser.parse_document(args.pdf, doc_type=args.type)

    print(f"\n{'='*50}")
    print(f"Parsing terminé: {result.total_items} items")
    print(f"Backend: {result.parser_backend}")
    print(f"Stats: {json.dumps(result.statistics, indent=2)}")

    if args.output:
        result.to_json(args.output)
        print(f"Sauvegardé: {args.output}")
