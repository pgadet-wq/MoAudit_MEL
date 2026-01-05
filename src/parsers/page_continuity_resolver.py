#!/usr/bin/env python3
"""
MoA_MEL - Page Continuity Resolver
==================================
Résout le problème de rupture de continuité multi-pages.

Ce module détecte et fusionne les blocs de texte/tableaux qui
s'étendent sur plusieurs pages dans les documents MEL/MMEL.

Patterns détectés:
- Marqueurs explicites: "continued", "(cont.)", "(suite)"
- Headers de colonnes répétés
- Items ATA fragmentés (suffixe seul en début de page)
- Remarques tronquées
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PageContinuityResolver")


class ContinuationType(Enum):
    """Types de continuité détectés"""
    NONE = "none"
    EXPLICIT_MARKER = "explicit_marker"  # "continued"
    REPEATED_HEADER = "repeated_header"   # Même en-têtes
    ITEM_FRAGMENT = "item_fragment"       # Suffixe seul
    TRUNCATED_TEXT = "truncated_text"     # Phrase incomplète


@dataclass
class PageBlock:
    """Bloc de contenu d'une page"""

    page_number: int
    content: str
    block_type: str = "text"  # "text", "table", "header", "footer"

    # Métadonnées tableau si applicable
    table_index: Optional[int] = None
    column_headers: Optional[List[str]] = None
    row_count: int = 0

    # État de fusion
    is_continuation: bool = False
    continuation_type: ContinuationType = ContinuationType.NONE
    merged_from_pages: List[int] = field(default_factory=list)

    # Texte de l'en-tête/pied détecté
    header_text: str = ""
    footer_text: str = ""

    @property
    def first_line(self) -> str:
        """Première ligne du contenu"""
        lines = self.content.strip().split('\n')
        return lines[0] if lines else ""

    @property
    def last_line(self) -> str:
        """Dernière ligne du contenu"""
        lines = self.content.strip().split('\n')
        return lines[-1] if lines else ""


@dataclass
class MergedBlock:
    """Bloc fusionné à partir de plusieurs pages"""

    content: str
    source_pages: List[int]
    block_type: str = "text"

    # Pour les tableaux
    column_headers: Optional[List[str]] = None
    total_rows: int = 0

    # Métadonnées de fusion
    merge_count: int = 1
    continuation_types: List[ContinuationType] = field(default_factory=list)

    def add_content(self, new_content: str, page_number: int,
                   continuation_type: ContinuationType):
        """Ajoute du contenu au bloc fusionné"""
        self.content += "\n" + new_content
        self.source_pages.append(page_number)
        self.continuation_types.append(continuation_type)
        self.merge_count += 1


class PageContinuityResolver:
    """
    Résolveur de continuité multi-pages.

    Fusionne les blocs de texte/tableaux fragmentés sur plusieurs pages.
    """

    # Marqueurs explicites de continuation
    CONTINUATION_MARKERS = [
        r'\bcontinued\b',
        r'\(cont\.?\)',
        r'\(continued\)',
        r'\bsuite\b',
        r'\(suite\)',
        r"\bcont['']?d\b",
        r'→\s*$',  # Flèche en fin de ligne
    ]

    # Patterns de fin de page à ignorer (footers)
    FOOTER_PATTERNS = [
        r'page\s+\d+\s+of\s+\d+',
        r'revision\s+\d+',
        r'rev\.?\s*\d+',
        r'effectivity\s*:',
        r'^\d+\s*$',  # Numéro de page seul
        r'confidential',
        r'copyright',
    ]

    # Patterns de début de page à ignorer (headers)
    HEADER_PATTERNS = [
        r'minimum\s+equipment\s+list',
        r'mmel',
        r'mel\b',
        r'master\s+minimum',
        r'chapter\s+\d+',
        r'ata\s+\d+',
    ]

    # Patterns d'item ATA fragmenté
    ITEM_FRAGMENT_PATTERNS = [
        r'^[A-Z]\s',                    # Suffixe seul: "B ..."
        r'^[A-Z]\)\s',                  # Avec parenthèse: "B) ..."
        r'^\(\s*[a-z]\s*\)',            # Condition seule: "(a) ..."
        r'^[a-z]\)\s',                  # Condition: "a) ..."
    ]

    # Terminaisons de phrase incomplètes
    INCOMPLETE_ENDINGS = [
        r'\band\s*$',
        r'\bor\s*$',
        r'\bwith\s*$',
        r'\bthe\s*$',
        r'\bto\s*$',
        r'\bfor\s*$',
        r'\bprovided\s*$',
        r'\bif\s*$',
        r'\bthat\s*$',
        r'\bwhen\s*$',
        r'\bwhere\s*$',
        r',\s*$',
        r':\s*$',
    ]

    def __init__(self, header_similarity_threshold: float = 0.8):
        self.header_similarity_threshold = header_similarity_threshold

    def detect_continuation(self, current_block: PageBlock,
                          previous_block: Optional[PageBlock]) -> Tuple[bool, ContinuationType]:
        """
        Détecte si current_block continue previous_block.

        Returns:
            Tuple[is_continuation, continuation_type]
        """
        if previous_block is None:
            return False, ContinuationType.NONE

        # 1. Marqueur explicite dans le bloc actuel
        if self._has_continuation_marker(current_block.content):
            return True, ContinuationType.EXPLICIT_MARKER

        # 2. Marqueur explicite à la fin du bloc précédent
        if self._has_continuation_marker(previous_block.last_line):
            return True, ContinuationType.EXPLICIT_MARKER

        # 3. Headers de colonnes répétés (pour tableaux)
        if (current_block.column_headers and previous_block.column_headers):
            if self._headers_match(current_block.column_headers,
                                  previous_block.column_headers):
                return True, ContinuationType.REPEATED_HEADER

        # 4. Item ATA fragmenté (commence par suffixe seul)
        if self._is_item_fragment(current_block.first_line):
            return True, ContinuationType.ITEM_FRAGMENT

        # 5. Phrase tronquée (fin incomplète dans bloc précédent)
        if self._is_truncated_text(previous_block.last_line):
            return True, ContinuationType.TRUNCATED_TEXT

        return False, ContinuationType.NONE

    def _has_continuation_marker(self, text: str) -> bool:
        """Vérifie la présence d'un marqueur de continuation"""
        text_lower = text.lower()
        for pattern in self.CONTINUATION_MARKERS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _headers_match(self, headers1: List[str], headers2: List[str]) -> bool:
        """Compare deux listes d'en-têtes de colonnes"""
        if len(headers1) != len(headers2):
            return False

        matches = 0
        for h1, h2 in zip(headers1, headers2):
            # Normaliser et comparer
            h1_norm = re.sub(r'\s+', ' ', h1.lower().strip())
            h2_norm = re.sub(r'\s+', ' ', h2.lower().strip())

            if h1_norm == h2_norm:
                matches += 1
            elif self._string_similarity(h1_norm, h2_norm) > self.header_similarity_threshold:
                matches += 1

        return matches / len(headers1) >= self.header_similarity_threshold

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calcule la similarité entre deux chaînes (Jaccard simple)"""
        if not s1 or not s2:
            return 0.0

        words1 = set(s1.split())
        words2 = set(s2.split())

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _is_item_fragment(self, text: str) -> bool:
        """Vérifie si le texte commence par un fragment d'item"""
        text = text.strip()
        for pattern in self.ITEM_FRAGMENT_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_truncated_text(self, text: str) -> bool:
        """Vérifie si le texte se termine de manière incomplète"""
        text = text.strip()
        for pattern in self.INCOMPLETE_ENDINGS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_footer(self, text: str) -> bool:
        """Vérifie si le texte est un footer de page"""
        text_lower = text.lower().strip()
        for pattern in self.FOOTER_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _is_header(self, text: str) -> bool:
        """Vérifie si le texte est un header de page"""
        text_lower = text.lower().strip()
        for pattern in self.HEADER_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _clean_block_content(self, content: str) -> str:
        """Nettoie le contenu d'un bloc (retire headers/footers)"""
        lines = content.split('\n')
        cleaned_lines = []

        for i, line in enumerate(lines):
            # Skip headers au début
            if i < 3 and self._is_header(line):
                continue
            # Skip footers à la fin
            if i > len(lines) - 4 and self._is_footer(line):
                continue
            # Retirer les marqueurs de continuation
            cleaned = line
            for pattern in self.CONTINUATION_MARKERS:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            cleaned_lines.append(cleaned.strip())

        return '\n'.join(cleaned_lines)

    def merge_blocks(self, blocks: List[PageBlock]) -> List[MergedBlock]:
        """
        Fusionne les blocs consécutifs appartenant au même item logique.

        Args:
            blocks: Liste de PageBlock triée par numéro de page

        Returns:
            Liste de MergedBlock fusionnés
        """
        if not blocks:
            return []

        merged_blocks = []
        current_merged: Optional[MergedBlock] = None

        for i, block in enumerate(blocks):
            previous_block = blocks[i - 1] if i > 0 else None

            is_continuation, cont_type = self.detect_continuation(block, previous_block)

            if is_continuation and current_merged is not None:
                # Fusionner avec le bloc précédent
                cleaned_content = self._clean_block_content(block.content)
                current_merged.add_content(cleaned_content, block.page_number, cont_type)

                logger.debug(f"Page {block.page_number} fusionnée avec précédente "
                           f"(type: {cont_type.value})")
            else:
                # Nouveau bloc logique
                if current_merged is not None:
                    merged_blocks.append(current_merged)

                current_merged = MergedBlock(
                    content=self._clean_block_content(block.content),
                    source_pages=[block.page_number],
                    block_type=block.block_type,
                    column_headers=block.column_headers,
                    total_rows=block.row_count
                )

        # Ajouter le dernier bloc
        if current_merged is not None:
            merged_blocks.append(current_merged)

        logger.info(f"Fusion: {len(blocks)} blocs → {len(merged_blocks)} blocs logiques")

        return merged_blocks

    def process_markdown_pages(self, markdown_pages: List[str]) -> List[MergedBlock]:
        """
        Traite des pages Markdown et les fusionne intelligemment.

        Args:
            markdown_pages: Liste de strings Markdown, une par page

        Returns:
            Liste de MergedBlock fusionnés
        """
        blocks = []

        for page_num, page_content in enumerate(markdown_pages, 1):
            # Détecter les tableaux dans le Markdown
            tables = self._extract_tables_from_markdown(page_content)

            if tables:
                for table_idx, (headers, rows, table_text) in enumerate(tables):
                    blocks.append(PageBlock(
                        page_number=page_num,
                        content=table_text,
                        block_type="table",
                        table_index=table_idx,
                        column_headers=headers,
                        row_count=len(rows)
                    ))
            else:
                blocks.append(PageBlock(
                    page_number=page_num,
                    content=page_content,
                    block_type="text"
                ))

        return self.merge_blocks(blocks)

    def _extract_tables_from_markdown(self, markdown: str) -> List[Tuple[List[str], List[str], str]]:
        """
        Extrait les tableaux d'un Markdown.

        Returns:
            Liste de (headers, rows, table_text)
        """
        tables = []

        # Pattern pour tableau Markdown
        # | Header 1 | Header 2 |
        # |----------|----------|
        # | Cell 1   | Cell 2   |

        table_pattern = r'(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)'

        for match in re.finditer(table_pattern, markdown):
            table_text = match.group(1)
            lines = table_text.strip().split('\n')

            if len(lines) >= 2:
                # Première ligne = headers
                headers = [cell.strip() for cell in lines[0].split('|') if cell.strip()]

                # Lignes suivantes (skip separator)
                rows = []
                for line in lines[2:]:
                    cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                    if cells:
                        rows.append(line)

                tables.append((headers, rows, table_text))

        return tables


class TableRowMerger:
    """
    Fusionne les lignes de tableau fragmentées sur plusieurs pages.

    Gère spécifiquement le cas où un item MEL est coupé entre deux pages.
    """

    def __init__(self):
        self.ata_pattern = re.compile(r'^\d{2}-\d{2}-\d{2,3}[A-Z]?')

    def merge_table_rows(self, merged_blocks: List[MergedBlock]) -> List[Dict[str, Any]]:
        """
        Reconstitue les lignes de tableau à partir des blocs fusionnés.

        Returns:
            Liste de dicts représentant les lignes reconstituées
        """
        all_rows = []

        for block in merged_blocks:
            if block.block_type != "table":
                continue

            # Parser le contenu comme tableau
            rows = self._parse_table_content(block.content, block.column_headers)

            # Fusionner les lignes fragmentées
            merged_rows = self._merge_fragmented_rows(rows)

            for row in merged_rows:
                row['source_pages'] = block.source_pages
                row['was_merged'] = block.merge_count > 1

            all_rows.extend(merged_rows)

        return all_rows

    def _parse_table_content(self, content: str,
                            headers: Optional[List[str]]) -> List[Dict[str, str]]:
        """Parse le contenu en lignes de tableau"""
        rows = []
        lines = content.strip().split('\n')

        for line in lines:
            # Skip lignes vides et séparateurs
            if not line.strip() or re.match(r'^[-|:\s]+$', line):
                continue

            cells = [cell.strip() for cell in line.split('|') if cell.strip()]

            if headers and len(cells) == len(headers):
                row = dict(zip(headers, cells))
                rows.append(row)
            elif cells:
                # Ligne sans correspondance exacte aux headers
                rows.append({'_raw_cells': cells, '_line': line})

        return rows

    def _merge_fragmented_rows(self, rows: List[Dict]) -> List[Dict]:
        """Fusionne les lignes fragmentées"""
        if not rows:
            return []

        merged = []
        current_row = None

        for row in rows:
            # Vérifier si c'est une nouvelle ligne ATA
            first_cell = list(row.values())[0] if row else ""

            if isinstance(first_cell, str) and self.ata_pattern.match(first_cell):
                # Nouvelle ligne complète
                if current_row:
                    merged.append(current_row)
                current_row = row.copy()
            elif current_row:
                # Fragment - fusionner avec la ligne courante
                self._merge_row_fragment(current_row, row)
            else:
                # Première ligne, fragment orphelin
                current_row = row.copy()

        if current_row:
            merged.append(current_row)

        return merged

    def _merge_row_fragment(self, main_row: Dict, fragment: Dict):
        """Fusionne un fragment dans la ligne principale"""
        for key, value in fragment.items():
            if key.startswith('_'):
                continue

            if key in main_row:
                # Concaténer les valeurs
                main_row[key] = main_row[key] + " " + value
            else:
                main_row[key] = value


# === TESTS ===
if __name__ == "__main__":
    resolver = PageContinuityResolver()

    # Test détection continuation
    block1 = PageBlock(
        page_number=1,
        content="21-30-01A Ice Detection System\n(O) May be inoperative provided:",
        block_type="table",
        column_headers=["Item", "Description", "Category"]
    )

    block2 = PageBlock(
        page_number=2,
        content="(continued)\n(a) icing conditions not expected,\n(b) crew briefed.",
        block_type="table",
        column_headers=["Item", "Description", "Category"]
    )

    is_cont, cont_type = resolver.detect_continuation(block2, block1)
    print(f"Block2 continues Block1: {is_cont} ({cont_type.value})")

    # Test fusion
    merged = resolver.merge_blocks([block1, block2])
    print(f"Merged blocks: {len(merged)}")
    for mb in merged:
        print(f"  Pages: {mb.source_pages}")
        print(f"  Content preview: {mb.content[:100]}...")
