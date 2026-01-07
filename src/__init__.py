"""
MoA_MEL Audit PoC
=================
Prototype d'audit automatisé MEL/MMEL.
"""

__version__ = "2.0.0-poc"
__author__ = "OPS Insight"

from .config import config, AppConfig
from .mel_indexer import MELIndexer, MatchResult, IndexingResult
from .mel_comparator import MELComparator, ComparisonResult, AuditResult, Verdict, Severity
from .pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

# New unified parser
from .parsers import UnifiedParser, ParsedDocument, ParserBackend

__all__ = [
    "config",
    "AppConfig",
    "MELIndexer",
    "MatchResult",
    "IndexingResult",
    "MELComparator",
    "ComparisonResult",
    "AuditResult",
    "Verdict",
    "Severity",
    "MoAMELPipelineV2",
    "PipelineConfigV2",
    "UnifiedParser",
    "ParsedDocument",
    "ParserBackend",
]
