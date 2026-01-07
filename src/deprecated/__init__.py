"""
DEPRECATED PARSERS
==================
Ces parsers sont obsolètes et conservés uniquement pour référence.

Utilisez à la place:
    from parsers.unified_parser import UnifiedParser

Migration:
    # Ancien code:
    from mel_parser import MELParser
    parser = MELParser(api_key)
    result = parser.parse_pdf(path)

    # Nouveau code:
    from parsers.unified_parser import UnifiedParser
    parser = UnifiedParser.create(api_key=api_key)
    result = parser.parse_document(path, doc_type="MEL")
"""

import warnings

warnings.warn(
    "Les modules dans deprecated/ sont obsolètes. "
    "Utilisez parsers.unified_parser.UnifiedParser à la place.",
    DeprecationWarning,
    stacklevel=2
)
