"""
MoA_MEL - Parsers V2
====================
Enhanced parsing with multi-page continuity and semantic extraction.

Usage recommandé:
    from parsers import UnifiedParser
    parser = UnifiedParser.create(api_key="...")
    result = parser.parse_document("doc.pdf", doc_type="MEL")
"""

from .page_continuity_resolver import (
    PageContinuityResolver,
    PageBlock,
    MergedBlock,
    ContinuationType,
    TableRowMerger,
)

from .semantic_parser import (
    SemanticMELParser,
    HybridParser,
    ExtractionResult,
)

from .unified_parser import (
    UnifiedParser,
    ParsedDocument,
    ParserBackend,
    parse_mel_document,
    parse_mmel_document,
)

__all__ = [
    # Unified Parser (recommandé)
    "UnifiedParser",
    "ParsedDocument",
    "ParserBackend",
    "parse_mel_document",
    "parse_mmel_document",
    # Components
    "PageContinuityResolver",
    "PageBlock",
    "MergedBlock",
    "ContinuationType",
    "TableRowMerger",
    "SemanticMELParser",
    "HybridParser",
    "ExtractionResult",
]
