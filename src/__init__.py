"""
MoA_MEL Audit PoC
=================
Prototype d'audit automatisé MEL/MMEL.
"""

__version__ = "1.0.0-poc"
__author__ = "OPS Insight"

from .config import config, AppConfig
from .mel_parser import MELParser, MELItem, ParsingResult
from .mel_indexer import MELIndexer, MatchResult, IndexingResult
from .mel_comparator import MELComparator, ComparisonResult, AuditResult, Verdict, Severity
from .pipeline import MoAMELPipeline

__all__ = [
    "config",
    "AppConfig",
    "MELParser",
    "MELItem",
    "ParsingResult",
    "MELIndexer",
    "MatchResult",
    "IndexingResult",
    "MELComparator",
    "ComparisonResult",
    "AuditResult",
    "Verdict",
    "Severity",
    "MoAMELPipeline"
]
