#!/usr/bin/env python3
"""
MoA_MEL - Parser MEL/MMEL basé sur Docling
==========================================
Extraction fiable des tableaux avec validation ATA.
Supporte parsing local ET service distant Docling (Scaleway).
"""

import json
import re
import logging
import asyncio
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Union
from datetime import datetime
from abc import ABC, abstractmethod

import httpx

# Import configuration
try:
    from config import config, ParsingBackend, load_config_from_env
    load_config_from_env()
except ImportError:
    config = None
    ParsingBackend = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DoclingParser")


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class MELItem:
    """Item MEL/MMEL extrait"""
    ata_chapter: str           # Ex: "21"
    ata_section: str           # Ex: "10"
    item_number: str           # Ex: "21-10-01A"
    item_description: str
    category: str              # A, B, C, D
    number_installed: str
    number_required: str
    remarks: str
    source_page: int = 0
    source_table: int = 0
    confidence: float = 1.0

    def to_dict(self):
        return asdict(self)

    @property
    def full_ata(self) -> str:
        """Format complet ATA: XX-YY-ZZ"""
        return self.item_number


@dataclass
class ParsingResult:
    """Résultat du parsing"""
    document_name: str
    document_type: str
    parsing_timestamp: str
    parser: str
    items: List[MELItem]
    statistics: dict
    raw_content: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "document_name": self.document_name,
            "document_type": self.document_type,
            "parsing_timestamp": self.parsing_timestamp,
            "parser": self.parser,
            "statistics": self.statistics,
            "items": [item.to_dict() for item in self.items],
            "error": self.error
        }


# ============================================================================
# ATA Parsing Utilities
# ============================================================================

def parse_ata_number(raw: str) -> dict:
    """
    Parse un numéro ATA et extrait les composants.
    Formats supportés: 21-10-01, 21-10-01A, 21-10- 01A, etc.
    """
    # Nettoyer
    cleaned = re.sub(r'\s+', '', str(raw).strip())

    # Pattern ATA: XX-YY-ZZ[A-Z]?
    pattern = r'^(\d{2})-(\d{2})-?(\d{2,3})([A-Z])?$'
    match = re.match(pattern, cleaned)

    if match:
        chapter, section, item, suffix = match.groups()
        item_num = f"{chapter}-{section}-{item.zfill(2)}"
        if suffix:
            item_num += suffix
        return {
            'valid': True,
            'chapter': chapter,
            'section': section,
            'item_number': item_num,
            'suffix': suffix or ''
        }

    return {'valid': False, 'raw': raw}


def extract_mel_items_from_table(df, table_idx: int = 0) -> List[MELItem]:
    """Extrait les items MEL d'un DataFrame Docling"""
    items = []

    # Identifier les colonnes
    cols = list(df.columns)
    n_cols = len(cols)

    if n_cols < 6:
        return items

    current_description = ""

    for idx, row in df.iterrows():
        values = [str(row.iloc[i]).strip() if i < len(row) else "" for i in range(n_cols)]

        # Colonne 0: System/Sequence number
        col0 = values[0]

        # Vérifier si c'est un numéro ATA
        ata_info = parse_ata_number(col0)

        if ata_info['valid']:
            # C'est une ligne avec un item ATA
            item_num = ata_info['item_number']
            chapter = ata_info['chapter']
            section = ata_info['section']

            # Colonne 1: Description (peut être vide si c'est une sous-ligne)
            desc = values[1] if len(values) > 1 else ""
            if desc and not desc.isspace():
                current_description = desc

            # Colonnes 2-5: Category, Installed, Required, Remarks
            category = values[2] if len(values) > 2 else ""
            installed = values[3] if len(values) > 3 else ""
            required = values[4] if len(values) > 4 else ""
            remarks = values[5] if len(values) > 5 else ""

            # Ne garder que si on a une catégorie (A, B, C, D)
            if category in ['A', 'B', 'C', 'D']:
                item = MELItem(
                    ata_chapter=chapter,
                    ata_section=section,
                    item_number=item_num,
                    item_description=current_description,
                    category=category,
                    number_installed=installed,
                    number_required=required,
                    remarks=remarks,
                    source_table=table_idx,
                    confidence=0.95
                )
                items.append(item)
                logger.debug(f"  Extrait: {item_num} - {current_description[:40]}... Cat={category}")

        elif col0 and not any(c.isdigit() for c in col0[:3]):
            # Ligne de description sans numéro ATA - possible titre de section
            pass

    return items


def extract_mel_items_from_json(content: dict, doc_type: str = "MEL") -> List[MELItem]:
    """
    Extrait les items MEL depuis le JSON retourné par le service Docling.
    Gère différents formats de sortie (tables, pages, items).
    """
    items = []

    # Si le contenu a déjà des items extraits
    if "items" in content and isinstance(content["items"], list):
        for item_data in content["items"]:
            try:
                ata_info = parse_ata_number(item_data.get("item_number", ""))
                if ata_info['valid']:
                    item = MELItem(
                        ata_chapter=ata_info['chapter'],
                        ata_section=ata_info['section'],
                        item_number=ata_info['item_number'],
                        item_description=item_data.get("item_description", ""),
                        category=item_data.get("category", ""),
                        number_installed=item_data.get("number_installed", ""),
                        number_required=item_data.get("number_required", ""),
                        remarks=item_data.get("remarks", ""),
                        source_page=item_data.get("source_page", 0),
                        confidence=item_data.get("confidence", 0.9)
                    )
                    items.append(item)
            except Exception as e:
                logger.warning(f"Erreur extraction item: {e}")

    # Si le contenu a des tables (format Docling standard)
    elif "tables" in content:
        for table_idx, table in enumerate(content.get("tables", [])):
            if "data" in table:
                # Convertir en DataFrame-like structure
                import pandas as pd
                try:
                    df = pd.DataFrame(table["data"])
                    table_items = extract_mel_items_from_table(df, table_idx)
                    items.extend(table_items)
                except Exception as e:
                    logger.warning(f"Erreur parsing table {table_idx}: {e}")

    # Format pages avec texte brut - extraction par regex
    elif "pages" in content:
        for page in content.get("pages", []):
            text = page.get("text", "")
            # Pattern pour détecter les lignes MEL
            pattern = r'(\d{2}-\d{2}-\d{2,3}[A-Z]?)\s+(.+?)\s+([ABCD])\s+(\d+)\s+(\d+)\s*(.*)$'
            for match in re.finditer(pattern, text, re.MULTILINE):
                ata_info = parse_ata_number(match.group(1))
                if ata_info['valid']:
                    item = MELItem(
                        ata_chapter=ata_info['chapter'],
                        ata_section=ata_info['section'],
                        item_number=ata_info['item_number'],
                        item_description=match.group(2).strip(),
                        category=match.group(3),
                        number_installed=match.group(4),
                        number_required=match.group(5),
                        remarks=match.group(6).strip() if match.group(6) else "",
                        source_page=page.get("page", 0),
                        confidence=0.8
                    )
                    items.append(item)

    return items


# ============================================================================
# Parser Backends
# ============================================================================

class ParserBackend(ABC):
    """Interface abstraite pour les backends de parsing"""

    @abstractmethod
    async def parse(self, source: Union[str, bytes], doc_type: str = "MEL") -> ParsingResult:
        """Parse un document et retourne le résultat"""
        pass


class LocalDoclingParser(ParserBackend):
    """Parser utilisant Docling localement"""

    def __init__(self):
        self._converter = None

    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
        return self._converter

    async def parse(self, source: Union[str, bytes], doc_type: str = "MEL") -> ParsingResult:
        """Parse un document avec Docling local"""
        logger.info(f"Parsing {doc_type} avec Docling local: {source}")

        try:
            converter = self._get_converter()

            # Si source est bytes, sauvegarder temporairement
            if isinstance(source, bytes):
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(source)
                    source = f.name

            result = converter.convert(source)

            # Extraire les tableaux
            tables = list(result.document.tables)
            logger.info(f"Tableaux détectés: {len(tables)}")

            all_items = []

            for i, table in enumerate(tables):
                try:
                    df = table.export_to_dataframe()
                    if len(df.columns) >= 6:
                        items = extract_mel_items_from_table(df, table_idx=i)
                        if items:
                            logger.info(f"  Tableau {i}: {len(items)} items extraits")
                            all_items.extend(items)
                except Exception as e:
                    logger.warning(f"  Tableau {i}: Erreur - {e}")

            # Dédoublonner
            unique_items = {}
            for item in all_items:
                if item.item_number not in unique_items:
                    unique_items[item.item_number] = item

            items_list = list(unique_items.values())
            logger.info(f"Total items uniques: {len(items_list)}")

            # Stats par chapitre
            by_chapter = {}
            for item in items_list:
                ch = item.ata_chapter
                by_chapter[ch] = by_chapter.get(ch, 0) + 1

            return ParsingResult(
                document_name=Path(source).name if isinstance(source, str) else "document.pdf",
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_local",
                items=items_list,
                statistics={
                    "total_tables": len(tables),
                    "total_items": len(items_list),
                    "by_chapter": by_chapter
                }
            )

        except Exception as e:
            logger.error(f"Erreur parsing local: {e}")
            return ParsingResult(
                document_name=str(source),
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_local",
                items=[],
                statistics={},
                error=str(e)
            )


class RemoteDoclingParser(ParserBackend):
    """Parser utilisant le service Docling distant (Scaleway)"""

    def __init__(self, service_url: str = None, timeout: int = 300, use_vlm: bool = True):
        if config:
            self.service_url = service_url or config.docling.service_url
            self.timeout = timeout or config.docling.timeout
            self.use_vlm = use_vlm if use_vlm is not None else config.docling.use_vlm
        else:
            self.service_url = service_url or "http://localhost:8001"
            self.timeout = timeout or 300
            self.use_vlm = use_vlm

    async def parse(self, source: Union[str, bytes], doc_type: str = "MEL") -> ParsingResult:
        """Parse un document via le service Docling distant"""
        logger.info(f"Parsing {doc_type} via service distant: {self.service_url}")

        try:
            # Préparer le fichier
            if isinstance(source, str):
                # Chemin de fichier
                file_path = Path(source)
                if not file_path.exists():
                    raise FileNotFoundError(f"Fichier non trouvé: {source}")
                file_content = file_path.read_bytes()
                filename = file_path.name
            else:
                # Bytes directement
                file_content = source
                filename = "document.pdf"

            # Appeler le service Docling
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Endpoint spécifique MEL/MMEL
                url = f"{self.service_url}/convert/mel"

                files = {"file": (filename, file_content, "application/pdf")}
                params = {
                    "document_type": doc_type,
                    "use_vlm": str(self.use_vlm).lower()
                }

                logger.info(f"Envoi vers {url}...")
                response = await client.post(url, files=files, params=params)

                if response.status_code != 200:
                    # Fallback vers endpoint générique
                    url = f"{self.service_url}/convert"
                    params = {
                        "output_format": "json",
                        "use_vlm": str(self.use_vlm).lower()
                    }
                    response = await client.post(url, files=files, params=params)

                response.raise_for_status()
                result_json = response.json()

            # Extraire les items du résultat
            content = result_json.get("result") or result_json.get("content") or result_json

            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    content = {"text": content}

            items = extract_mel_items_from_json(content, doc_type)

            # Dédoublonner
            unique_items = {}
            for item in items:
                if item.item_number not in unique_items:
                    unique_items[item.item_number] = item

            items_list = list(unique_items.values())

            # Stats
            by_chapter = {}
            for item in items_list:
                ch = item.ata_chapter
                by_chapter[ch] = by_chapter.get(ch, 0) + 1

            return ParsingResult(
                document_name=filename,
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_remote",
                items=items_list,
                statistics={
                    "total_items": len(items_list),
                    "by_chapter": by_chapter,
                    "pages_processed": result_json.get("pages_processed", 0),
                    "processing_time_ms": result_json.get("processing_time_ms", 0)
                },
                raw_content=content
            )

        except httpx.TimeoutException:
            logger.error(f"Timeout lors de l'appel au service Docling")
            return ParsingResult(
                document_name=str(source),
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_remote",
                items=[],
                statistics={},
                error="Timeout: le service Docling n'a pas répondu à temps"
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Erreur HTTP du service Docling: {e.response.status_code}")
            return ParsingResult(
                document_name=str(source),
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_remote",
                items=[],
                statistics={},
                error=f"Erreur HTTP {e.response.status_code}: {e.response.text}"
            )

        except Exception as e:
            logger.error(f"Erreur parsing distant: {e}")
            return ParsingResult(
                document_name=str(source),
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="docling_remote",
                items=[],
                statistics={},
                error=str(e)
            )


class FallbackParser(ParserBackend):
    """Parser de secours utilisant PyMuPDF (extraction basique)"""

    async def parse(self, source: Union[str, bytes], doc_type: str = "MEL") -> ParsingResult:
        """Extraction basique avec PyMuPDF"""
        import fitz

        logger.info(f"Parsing {doc_type} avec PyMuPDF (fallback)")

        try:
            if isinstance(source, bytes):
                doc = fitz.open(stream=source, filetype="pdf")
                filename = "document.pdf"
            else:
                doc = fitz.open(source)
                filename = Path(source).name

            items = []
            pattern = r'(\d{2}-\d{2}-\d{2,3}[A-Z]?)\s+(.+?)\s+([ABCD])\s+(\d+)\s+(\d+)\s*(.*)$'

            for page_num, page in enumerate(doc):
                text = page.get_text()
                for match in re.finditer(pattern, text, re.MULTILINE):
                    ata_info = parse_ata_number(match.group(1))
                    if ata_info['valid']:
                        item = MELItem(
                            ata_chapter=ata_info['chapter'],
                            ata_section=ata_info['section'],
                            item_number=ata_info['item_number'],
                            item_description=match.group(2).strip(),
                            category=match.group(3),
                            number_installed=match.group(4),
                            number_required=match.group(5),
                            remarks=match.group(6).strip() if match.group(6) else "",
                            source_page=page_num + 1,
                            confidence=0.7
                        )
                        items.append(item)

            total_pages = len(doc)
            doc.close()

            # Dédoublonner
            unique_items = {}
            for item in items:
                if item.item_number not in unique_items:
                    unique_items[item.item_number] = item

            items_list = list(unique_items.values())

            by_chapter = {}
            for item in items_list:
                ch = item.ata_chapter
                by_chapter[ch] = by_chapter.get(ch, 0) + 1

            return ParsingResult(
                document_name=filename,
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="pymupdf_fallback",
                items=items_list,
                statistics={
                    "total_pages": total_pages,
                    "total_items": len(items_list),
                    "by_chapter": by_chapter
                }
            )

        except Exception as e:
            logger.error(f"Erreur parsing fallback: {e}")
            return ParsingResult(
                document_name=str(source),
                document_type=doc_type,
                parsing_timestamp=datetime.now().isoformat(),
                parser="pymupdf_fallback",
                items=[],
                statistics={},
                error=str(e)
            )


# ============================================================================
# Parser Factory
# ============================================================================

def get_parser(backend: str = None) -> ParserBackend:
    """
    Factory pour obtenir le parser approprié selon la configuration.

    Args:
        backend: Type de backend ("local_docling", "remote_docling", "fallback")
                 Si None, utilise la configuration globale.
    """
    if backend is None and config:
        backend = config.parsing_backend.value
    elif backend is None:
        backend = "remote_docling"

    if backend == "local_docling":
        return LocalDoclingParser()
    elif backend == "remote_docling":
        return RemoteDoclingParser()
    elif backend == "fallback":
        return FallbackParser()
    else:
        # Default to remote
        return RemoteDoclingParser()


# ============================================================================
# High-Level API (Compatibilité)
# ============================================================================

def parse_document(pdf_path: str, doc_type: str = "MEL", backend: str = None) -> dict:
    """
    Parse un document MEL ou MMEL.
    API synchrone pour compatibilité avec le code existant.

    Args:
        pdf_path: Chemin vers le fichier PDF
        doc_type: Type de document ("MEL" ou "MMEL")
        backend: Backend à utiliser (optionnel)

    Returns:
        dict avec les items extraits
    """
    parser = get_parser(backend)

    # Exécuter de manière synchrone
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(parser.parse(pdf_path, doc_type))
    finally:
        loop.close()

    return result.to_dict()


async def parse_document_async(
    source: Union[str, bytes],
    doc_type: str = "MEL",
    backend: str = None
) -> ParsingResult:
    """
    Parse un document MEL ou MMEL de manière asynchrone.

    Args:
        source: Chemin vers le fichier PDF ou contenu bytes
        doc_type: Type de document ("MEL" ou "MMEL")
        backend: Backend à utiliser (optionnel)

    Returns:
        ParsingResult avec les items extraits
    """
    parser = get_parser(backend)
    return await parser.parse(source, doc_type)


def save_result(result: dict, output_path: str):
    """Sauvegarde le résultat en JSON"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info(f"Résultat sauvegardé: {output_path}")


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Parser MEL/MMEL avec Docling")
    parser.add_argument("pdf_path", help="Chemin vers le fichier PDF")
    parser.add_argument("--type", choices=["MEL", "MMEL"], default="MEL",
                        help="Type de document")
    parser.add_argument("--output", "-o", default=None,
                        help="Fichier de sortie JSON")
    parser.add_argument("--backend", choices=["local_docling", "remote_docling", "fallback"],
                        default=None, help="Backend de parsing")
    parser.add_argument("--service-url", default=None,
                        help="URL du service Docling distant")

    args = parser.parse_args()

    # Override service URL si spécifié
    if args.service_url and config:
        config.docling.service_url = args.service_url

    output_path = args.output or f"parsed_{args.type.lower()}.json"

    result = parse_document(args.pdf_path, args.type, args.backend)
    save_result(result, output_path)

    print(f"\n{'='*60}")
    print(f"PARSING {args.type} TERMINÉ")
    print(f"{'='*60}")
    print(f"Parser utilisé: {result.get('parser', 'unknown')}")
    print(f"Items extraits: {result['statistics'].get('total_items', 0)}")

    if result.get('error'):
        print(f"ERREUR: {result['error']}")
    else:
        print(f"Par chapitre ATA:")
        for ch, count in sorted(result['statistics'].get('by_chapter', {}).items()):
            print(f"  ATA {ch}: {count} items")
