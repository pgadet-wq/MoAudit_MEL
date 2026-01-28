#!/usr/bin/env python3
"""
MoA_MEL - MMEL Variant Tree
===========================
Index structuré des variantes MMEL avec contexte d'applicabilité.

Résout le problème de "cécité contextuelle" en permettant:
- Recherche par MSN
- Recherche par type d'opération (CAT, SPO, NCO)
- Matching de variante intelligente
"""

import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MMELVariantTree")


class MatchConfidence(Enum):
    """Niveau de confiance du match"""
    EXACT = "exact"           # Match parfait (item + contexte)
    VARIANT = "variant"       # Match sur variante différente
    PARTIAL = "partial"       # Match partiel (item_base seul)
    INFERRED = "inferred"     # Match inféré (pas de contexte explicite)
    NONE = "none"


@dataclass
class MSNRange:
    """Plage de MSN pour filtrage"""

    start: Optional[int] = None
    end: Optional[int] = None
    explicit_list: List[int] = field(default_factory=list)
    raw_text: str = ""

    def matches(self, msn: int) -> bool:
        """Vérifie si un MSN est dans cette plage"""
        if self.explicit_list and msn in self.explicit_list:
            return True

        if self.start is not None and self.end is not None:
            return self.start <= msn <= self.end

        if self.start is not None and self.end is None:
            return msn >= self.start

        # Pas de restriction
        return True

    @classmethod
    def parse(cls, text: str) -> "MSNRange":
        """Parse une mention MSN en objet structuré"""
        text = text.strip().upper()

        # Pattern: MSN 545-999
        range_match = re.search(r'MSN\s*(\d+)\s*[-–]\s*(\d+)', text, re.IGNORECASE)
        if range_match:
            return cls(
                start=int(range_match.group(1)),
                end=int(range_match.group(2)),
                raw_text=text
            )

        # Pattern: MSN 1001 and up
        open_match = re.search(r'MSN\s*(\d+)\s*(?:and\s*up|\+)', text, re.IGNORECASE)
        if open_match:
            return cls(start=int(open_match.group(1)), raw_text=text)

        # Pattern: MSN 101, 102, 103
        list_match = re.search(r'MSN\s*([\d,\s]+)', text, re.IGNORECASE)
        if list_match:
            numbers = re.findall(r'\d+', list_match.group(1))
            return cls(explicit_list=[int(n) for n in numbers], raw_text=text)

        return cls(raw_text=text or "ALL")

    def __str__(self) -> str:
        if self.explicit_list:
            return f"MSN {', '.join(map(str, self.explicit_list))}"
        if self.start and self.end:
            return f"MSN {self.start}-{self.end}"
        if self.start:
            return f"MSN {self.start}+"
        return "ALL MSN"


@dataclass
class VariantContext:
    """Contexte d'applicabilité d'une variante"""

    msn_ranges: List[MSNRange] = field(default_factory=list)
    operation_types: List[str] = field(default_factory=list)  # CAT, SPO, NCO, NCC
    aircraft_variants: List[str] = field(default_factory=list)  # A320-214, A320neo
    etops_applicable: Optional[bool] = None

    def matches(self, msn: int, operation: str, aircraft: str = "") -> bool:
        """Vérifie si le contexte correspond"""
        # Vérifier MSN
        if self.msn_ranges:
            if not any(r.matches(msn) for r in self.msn_ranges):
                return False

        # Vérifier operation
        if self.operation_types:
            if operation.upper() not in [o.upper() for o in self.operation_types]:
                return False

        # Vérifier aircraft variant
        if self.aircraft_variants and aircraft:
            if aircraft not in self.aircraft_variants:
                return False

        return True

    def specificity_score(self) -> int:
        """Score de spécificité (plus élevé = plus spécifique)"""
        score = 0
        if self.msn_ranges:
            score += len(self.msn_ranges) * 2
        if self.operation_types:
            score += len(self.operation_types)
        if self.aircraft_variants:
            score += len(self.aircraft_variants)
        return score


@dataclass
class MMELVariant:
    """Une variante d'item MMEL avec son contexte"""

    item_number: str       # Numéro complet: 21-30-01D
    item_base: str         # Base sans suffixe: 21-30-01
    suffix: str            # Suffixe seul: D
    item_data: Dict[str, Any]
    context: VariantContext

    @property
    def category(self) -> str:
        return self.item_data.get("category", "C")

    @property
    def description(self) -> str:
        return self.item_data.get("item_description", "")


@dataclass
class MatchResult:
    """Résultat d'un match MEL → MMEL"""

    mel_item: Dict[str, Any]
    matched_variant: Optional[MMELVariant]
    confidence: MatchConfidence
    score: float
    alternatives: List[MMELVariant] = field(default_factory=list)
    reason: str = ""


class MMELVariantTree:
    """
    Index structuré des variantes MMEL.

    Structure:
        item_base → {suffix → [variants avec contextes]}

    Permet de répondre à: "Pour l'item 21-30-01, MSN 1280, opération CAT,
    quelle variante MMEL appliquer?"
    """

    def __init__(self):
        # Structure principale: item_base → suffix → [variantes]
        self.tree: Dict[str, Dict[str, List[MMELVariant]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Index secondaires pour recherche rapide
        self.by_item_number: Dict[str, MMELVariant] = {}
        self.by_msn_start: Dict[int, Set[str]] = defaultdict(set)
        self.by_operation: Dict[str, Set[str]] = defaultdict(set)
        self.by_category: Dict[str, Set[str]] = defaultdict(set)

        # Statistiques
        self.total_items = 0
        self.total_variants = 0

    def add_item(self, item_data: Dict[str, Any]):
        """Ajoute un item MMEL à l'arbre"""
        item_number = item_data.get("item_number", "")
        if not item_number:
            return

        # Parser le numéro d'item
        parsed = self._parse_item_number(item_number)
        if not parsed:
            return

        item_base = parsed["item_base"]
        suffix = parsed.get("suffix", "")

        # Construire le contexte
        context = self._build_context(item_data)

        # Créer la variante
        variant = MMELVariant(
            item_number=item_number,
            item_base=item_base,
            suffix=suffix,
            item_data=item_data,
            context=context
        )

        # Ajouter à l'arbre
        self.tree[item_base][suffix].append(variant)

        # Mettre à jour les index secondaires
        self.by_item_number[item_number] = variant

        for msn_range in context.msn_ranges:
            if msn_range.start:
                self.by_msn_start[msn_range.start].add(item_base)

        for op in context.operation_types:
            self.by_operation[op.upper()].add(item_base)

        category = item_data.get("category", "C")
        self.by_category[category].add(item_number)

        self.total_items += 1
        self.total_variants += 1

    def _parse_item_number(self, item_number: str) -> Optional[Dict[str, str]]:
        """Parse un numéro d'item en composants"""
        cleaned = re.sub(r'\s+', '', str(item_number).strip())
        pattern = r'^(\d{2})-(\d{2})-?(\d{2,3})([A-Z])?$'
        match = re.match(pattern, cleaned)

        if match:
            chapter, section, item, suffix = match.groups()
            return {
                "chapter": chapter,
                "section": section,
                "item_base": f"{chapter}-{section}-{item.zfill(2)}",
                "suffix": suffix or ""
            }

        return None

    def _build_context(self, item_data: Dict[str, Any]) -> VariantContext:
        """Construit le contexte d'applicabilité depuis les données"""
        context = VariantContext()

        # Extraire MSN depuis applicable_msn ou depuis la description
        msn_data = item_data.get("applicable_msn", [])
        if isinstance(msn_data, list):
            for msn in msn_data:
                if isinstance(msn, str):
                    context.msn_ranges.append(MSNRange.parse(msn))

        # Chercher dans la description aussi
        description = item_data.get("item_description", "")
        msn_mentions = re.findall(r'MSN\s*[\d,\s\-+andupetsuivants]+', description, re.IGNORECASE)
        for mention in msn_mentions:
            if not any(mention in str(r) for r in context.msn_ranges):
                context.msn_ranges.append(MSNRange.parse(mention))

        # Extraire operation types
        op_data = item_data.get("operation_scope", [])
        if isinstance(op_data, list):
            context.operation_types = [str(o).upper() for o in op_data]

        # Chercher dans les remarks et description avec patterns étendus
        remarks = item_data.get("remarks", "") or item_data.get("remarks_raw", "")
        full_text = f"{description} {remarks}"

        # Patterns étendus pour capturer toutes les mentions
        operation_patterns = [
            # Avec parenthèses
            (r'\(CAT\)', "CAT"), (r'\(SPO\)', "SPO"),
            (r'\(NCO\)', "NCO"), (r'\(NCC\)', "NCC"),
            # Sans parenthèses (mots complets)
            (r'\bCAT\b', "CAT"), (r'\bSPO\b', "SPO"),
            (r'\bNCO\b', "NCO"), (r'\bNCC\b', "NCC"),
            # Mots-clés additionnels
            (r'\bCOMMERCIAL\b', "CAT"), (r'\bPRIVATE\b', "NCC"),
            (r'\bCARGO\b', "CAT"),
        ]

        for pattern, op in operation_patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                if op not in context.operation_types:
                    context.operation_types.append(op)

        # ETOPS
        if "etops" in remarks.lower() or "etops" in description.lower():
            if "prohibited" in remarks.lower():
                context.etops_applicable = False
            else:
                context.etops_applicable = True

        return context

    def get_item(self, item_number: str) -> Optional[MMELVariant]:
        """Récupère un item par son numéro exact"""
        return self.by_item_number.get(item_number)

    def get_all_variants(self, item_base: str) -> List[MMELVariant]:
        """Récupère toutes les variantes d'un item de base"""
        variants = []
        if item_base in self.tree:
            for suffix_variants in self.tree[item_base].values():
                variants.extend(suffix_variants)
        return variants

    def find_applicable_variant(self, item_base: str, msn: int,
                               operation: str, aircraft: str = "") -> Optional[MMELVariant]:
        """
        Trouve la variante applicable au contexte donné.

        Args:
            item_base: Item de base sans suffixe (21-30-01)
            msn: MSN de l'avion
            operation: Type d'opération (CAT, SPO, etc.)
            aircraft: Variante avion optionnelle

        Returns:
            La variante MMEL applicable ou None
        """
        if item_base not in self.tree:
            return None

        candidates = []

        for suffix, variants in self.tree[item_base].items():
            for variant in variants:
                if variant.context.matches(msn, operation, aircraft):
                    candidates.append(variant)

        if not candidates:
            # Aucun match direct, essayer sans contexte
            all_variants = self.get_all_variants(item_base)
            # Prendre les variantes sans contexte restrictif
            for v in all_variants:
                if not v.context.msn_ranges and not v.context.operation_types:
                    candidates.append(v)

        if not candidates:
            return None

        # Trier par spécificité décroissante
        candidates.sort(key=lambda v: v.context.specificity_score(), reverse=True)

        return candidates[0]

    def match_mel_item(self, mel_item: Dict[str, Any], msn: int,
                      operation: str, aircraft: str = "") -> MatchResult:
        """
        Matche un item MEL avec la variante MMEL appropriée.

        Args:
            mel_item: Item MEL à matcher
            msn: MSN de l'avion
            operation: Type d'opération
            aircraft: Variante avion

        Returns:
            MatchResult avec la variante trouvée et les alternatives
        """
        mel_item_number = mel_item.get("item_number", "")
        mel_item_base = mel_item.get("item_base", "")

        # Essayer d'extraire item_base si non fourni
        if not mel_item_base:
            parsed = self._parse_item_number(mel_item_number)
            if parsed:
                mel_item_base = parsed["item_base"]

        if not mel_item_base:
            return MatchResult(
                mel_item=mel_item,
                matched_variant=None,
                confidence=MatchConfidence.NONE,
                score=0.0,
                reason="Impossible de parser le numéro d'item MEL"
            )

        # 1. Essayer match exact sur item_number
        exact_match = self.get_item(mel_item_number)
        if exact_match:
            if exact_match.context.matches(msn, operation, aircraft):
                return MatchResult(
                    mel_item=mel_item,
                    matched_variant=exact_match,
                    confidence=MatchConfidence.EXACT,
                    score=1.0,
                    reason=f"Match exact sur {mel_item_number}"
                )

        # 2. Chercher variante applicable par contexte
        applicable = self.find_applicable_variant(mel_item_base, msn, operation, aircraft)

        if applicable:
            # Vérifier si c'est la même variante ou une différente
            if applicable.item_number == mel_item_number:
                confidence = MatchConfidence.EXACT
                score = 1.0
            else:
                confidence = MatchConfidence.VARIANT
                score = 0.85

            # Récupérer les alternatives
            all_variants = self.get_all_variants(mel_item_base)
            alternatives = [v for v in all_variants if v.item_number != applicable.item_number]

            return MatchResult(
                mel_item=mel_item,
                matched_variant=applicable,
                confidence=confidence,
                score=score,
                alternatives=alternatives,
                reason=f"Variante {applicable.item_number} applicable pour MSN {msn}, {operation}"
            )

        # 3. Match partiel sur item_base (sans contexte)
        all_variants = self.get_all_variants(mel_item_base)
        if all_variants:
            # Prendre la première variante (généralement sans suffixe)
            default_variant = all_variants[0]

            return MatchResult(
                mel_item=mel_item,
                matched_variant=default_variant,
                confidence=MatchConfidence.PARTIAL,
                score=0.6,
                alternatives=all_variants[1:] if len(all_variants) > 1 else [],
                reason=f"Match partiel sur {mel_item_base}, aucune variante spécifique pour le contexte"
            )

        # 4. Aucun match
        return MatchResult(
            mel_item=mel_item,
            matched_variant=None,
            confidence=MatchConfidence.NONE,
            score=0.0,
            reason=f"Aucun item MMEL trouvé pour {mel_item_base}"
        )

    def build_from_items(self, items: List[Dict[str, Any]]):
        """Construit l'arbre depuis une liste d'items"""
        for item in items:
            self.add_item(item)

        logger.info(f"Arbre construit: {self.total_items} items, "
                   f"{len(self.tree)} items de base uniques")

    def get_statistics(self) -> Dict[str, Any]:
        """Retourne les statistiques de l'arbre"""
        variants_per_base = []
        for item_base, suffixes in self.tree.items():
            total = sum(len(v) for v in suffixes.values())
            variants_per_base.append(total)

        return {
            "total_items": self.total_items,
            "unique_base_items": len(self.tree),
            "items_by_category": {
                cat: len(items) for cat, items in self.by_category.items()
            },
            "items_by_operation": {
                op: len(items) for op, items in self.by_operation.items()
            },
            "max_variants_per_item": max(variants_per_base) if variants_per_base else 0,
            "avg_variants_per_item": sum(variants_per_base) / len(variants_per_base) if variants_per_base else 0
        }


@dataclass
class AircraftContext:
    """Contexte complet d'un avion pour la comparaison"""

    msn: int
    operation_type: str  # CAT, SPO, NCO, NCC
    aircraft_type: str = ""  # A320-214, A320neo
    etops_certified: bool = False
    rvsm_certified: bool = True
    installed_equipment: Dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        return f"MSN {self.msn}, {self.operation_type}, {self.aircraft_type}"


# === TESTS ===
if __name__ == "__main__":
    # Créer un arbre de test
    tree = MMELVariantTree()

    # Ajouter des items de test
    test_items = [
        {
            "item_number": "21-30-01A",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System (MSN 101-544)",
            "category": "C",
            "remarks": "(O) May be inoperative for CAT operations.",
            "applicable_msn": ["MSN 101-544"],
            "operation_scope": ["CAT"]
        },
        {
            "item_number": "21-30-01B",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System (MSN 101-544)",
            "category": "C",
            "remarks": "(O) May be inoperative for SPO/NCO operations.",
            "applicable_msn": ["MSN 101-544"],
            "operation_scope": ["SPO", "NCO"]
        },
        {
            "item_number": "21-30-01C",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System (MSN 545 and up)",
            "category": "B",
            "remarks": "(O)(M) May be inoperative for CAT.",
            "applicable_msn": ["MSN 545 and up"],
            "operation_scope": ["CAT"]
        },
        {
            "item_number": "21-30-01D",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System (MSN 545 and up)",
            "category": "C",
            "remarks": "(O) May be inoperative for SPO/NCO. ETOPS prohibited.",
            "applicable_msn": ["MSN 545 and up"],
            "operation_scope": ["SPO", "NCO"]
        }
    ]

    tree.build_from_items(test_items)

    # Tests de matching
    print("=" * 60)
    print("Tests de matching MMEL Variant Tree")
    print("=" * 60)

    # Test 1: MSN 300, CAT -> devrait matcher 21-30-01A
    mel_item_1 = {"item_number": "21-30-01", "item_base": "21-30-01"}
    result = tree.match_mel_item(mel_item_1, msn=300, operation="CAT")
    print(f"\nTest 1: MSN 300, CAT")
    print(f"  Matched: {result.matched_variant.item_number if result.matched_variant else 'None'}")
    print(f"  Confidence: {result.confidence.value}")
    print(f"  Reason: {result.reason}")

    # Test 2: MSN 1280, CAT -> devrait matcher 21-30-01C
    result = tree.match_mel_item(mel_item_1, msn=1280, operation="CAT")
    print(f"\nTest 2: MSN 1280, CAT")
    print(f"  Matched: {result.matched_variant.item_number if result.matched_variant else 'None'}")
    print(f"  Confidence: {result.confidence.value}")

    # Test 3: MSN 1280, SPO -> devrait matcher 21-30-01D
    result = tree.match_mel_item(mel_item_1, msn=1280, operation="SPO")
    print(f"\nTest 3: MSN 1280, SPO")
    print(f"  Matched: {result.matched_variant.item_number if result.matched_variant else 'None'}")
    print(f"  Category MMEL: {result.matched_variant.category if result.matched_variant else 'N/A'}")

    # Statistiques
    print(f"\nStatistiques de l'arbre:")
    stats = tree.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
