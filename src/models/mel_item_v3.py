#!/usr/bin/env python3
"""
MoA_MEL - Modèles de données enrichis V3
=========================================
Modèles Pydantic avec contexte d'applicabilité complet pour résoudre:
- Cécité contextuelle (MSN, Operation Types)
- Troncature des conditions
- Variantes multiples d'un même item
"""

from __future__ import annotations
from typing import List, Optional, Literal, Any, Dict
from pydantic import BaseModel, Field, field_validator, model_validator
import re


class MSNRange(BaseModel):
    """Plage de MSN (Manufacturer Serial Number) applicable"""

    start: Optional[int] = None
    end: Optional[int] = None
    explicit_list: List[int] = Field(default_factory=list)
    raw_text: str = ""

    def matches(self, msn: int) -> bool:
        """Vérifie si un MSN est dans cette plage"""
        # Liste explicite
        if self.explicit_list and msn in self.explicit_list:
            return True

        # Plage avec bornes
        if self.start is not None and self.end is not None:
            return self.start <= msn <= self.end

        # Plage ouverte (start and up)
        if self.start is not None and self.end is None:
            return msn >= self.start

        # Pas de restriction = ALL
        return True

    @classmethod
    def parse_from_text(cls, text: str) -> "MSNRange":
        """Parse un texte MSN en objet structuré"""
        text = text.strip().upper()

        # Pattern: MSN 545-999
        range_match = re.search(r'MSN\s*(\d+)\s*[-–]\s*(\d+)', text, re.IGNORECASE)
        if range_match:
            return cls(
                start=int(range_match.group(1)),
                end=int(range_match.group(2)),
                raw_text=text
            )

        # Pattern: MSN 1001 and up / MSN 1001+
        open_match = re.search(r'MSN\s*(\d+)\s*(?:and\s*up|\+|et\s*suivants)', text, re.IGNORECASE)
        if open_match:
            return cls(
                start=int(open_match.group(1)),
                end=None,
                raw_text=text
            )

        # Pattern: MSN 101, 102, 103
        list_match = re.search(r'MSN\s*([\d,\s]+)', text, re.IGNORECASE)
        if list_match:
            numbers = re.findall(r'\d+', list_match.group(1))
            return cls(
                explicit_list=[int(n) for n in numbers],
                raw_text=text
            )

        # ALL ou non spécifié
        return cls(raw_text=text or "ALL")

    def __str__(self) -> str:
        if self.explicit_list:
            return f"MSN {', '.join(map(str, self.explicit_list))}"
        if self.start and self.end:
            return f"MSN {self.start}-{self.end}"
        if self.start:
            return f"MSN {self.start} and up"
        return "ALL MSN"


class ApplicabilityCondition(BaseModel):
    """Condition d'applicabilité extraite des remarques (a), (b), (c)..."""

    id: str = Field(..., description="Identifiant de condition: a, b, c...")
    text: str = Field(..., description="Texte complet de la condition")
    is_complete: bool = Field(default=True, description="La condition est-elle complète?")
    condition_type: Optional[Literal["operational", "maintenance", "equipment", "restriction"]] = None

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Normalise l'ID de condition"""
        v = v.strip().lower()
        if not re.match(r'^[a-z]$', v):
            # Accepter aussi les formats (a), (1), etc.
            match = re.search(r'[a-z]|\d', v.lower())
            if match:
                return match.group()
        return v

    @field_validator('text')
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Nettoie le texte de la condition"""
        return v.strip()

    def check_completeness(self) -> tuple[bool, str]:
        """Vérifie si la condition semble complète"""
        incomplete_patterns = [
            r'\band\s*$',
            r'\bwith\s*$',
            r'\bthe\s*$',
            r'\bor\s*$',
            r'\bto\s*$',
            r'\bfor\s*$',
            r'\bprovided\s*$',
            r'\bif\s*$',
            r',\s*$',
        ]

        text = self.text.strip()
        if not text:
            return False, "Condition vide"

        for pattern in incomplete_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False, f"Se termine par mot incomplet"

        # Doit se terminer par ponctuation valide
        if not re.search(r'[.!?;)]$', text):
            # Acceptable si c'est une condition courte
            if len(text.split()) > 3:
                return False, "Pas de ponctuation finale"

        return True, ""


class RectificationInterval(BaseModel):
    """Intervalle de rectification structuré"""

    category: Literal["A", "B", "C", "D"]
    days: Optional[int] = None
    flight_hours: Optional[int] = None
    cycles: Optional[int] = None
    calendar_days: Optional[int] = None
    raw_text: str = ""

    @classmethod
    def from_category(cls, category: str) -> "RectificationInterval":
        """Crée un intervalle par défaut selon la catégorie"""
        defaults = {
            "A": {"days": 0},  # Mandatory - pas de dispatch
            "B": {"days": 3},
            "C": {"days": 10},
            "D": {"days": 120}
        }
        cat = category.upper().strip()
        if cat in defaults:
            return cls(category=cat, **defaults[cat])
        return cls(category="C", days=10, raw_text="default")

    @classmethod
    def parse_from_text(cls, text: str, category: str = "C") -> "RectificationInterval":
        """Parse un intervalle depuis un texte"""
        text_lower = text.lower().strip()

        # Pattern: X days
        days_match = re.search(r'(\d+)\s*(?:days?|d\b|jours?)', text_lower)
        if days_match:
            return cls(
                category=category,
                days=int(days_match.group(1)),
                raw_text=text
            )

        # Pattern: X flight hours / FH
        fh_match = re.search(r'(\d+)\s*(?:flight\s*hours?|fh|heures?\s*de\s*vol)', text_lower)
        if fh_match:
            return cls(
                category=category,
                flight_hours=int(fh_match.group(1)),
                raw_text=text
            )

        # Pattern: X cycles
        cycles_match = re.search(r'(\d+)\s*(?:cycles?|fc)', text_lower)
        if cycles_match:
            return cls(
                category=category,
                cycles=int(cycles_match.group(1)),
                raw_text=text
            )

        # Checks (A, B, C, D check)
        check_patterns = {
            r'a[\s-]?check': 400,
            r'b[\s-]?check': 120,
            r'c[\s-]?check': 600,
            r'd[\s-]?check': 2000,
        }
        for pattern, days in check_patterns.items():
            if re.search(pattern, text_lower):
                return cls(category=category, days=days, raw_text=text)

        return cls.from_category(category)


OperationType = Literal["CAT", "NCC", "NCO", "SPO", "COMMERCIAL", "PRIVATE", "CARGO"]


class MELItemV3(BaseModel):
    """
    Item MEL/MMEL enrichi avec contexte d'applicabilité complet.

    Résout les problèmes:
    - Cécité contextuelle (MSN, Operation Types)
    - Variantes multiples (suffixes A, B, C, D)
    - Conditions structurées vs texte brut
    """

    # === IDENTIFICATION ===
    ata_chapter: str = Field(..., pattern=r'^\d{2}$', description="Chapitre ATA (ex: 21)")
    ata_section: str = Field(..., pattern=r'^\d{2}$', description="Section ATA (ex: 30)")
    item_base: str = Field(..., pattern=r'^\d{2}-\d{2}-\d{2,3}$', description="Item sans suffixe (ex: 21-30-01)")
    variant_suffix: Optional[str] = Field(None, pattern=r'^[A-Z]?$', description="Suffixe de variante (ex: D)")

    @property
    def item_number(self) -> str:
        """Numéro d'item complet avec suffixe"""
        return f"{self.item_base}{self.variant_suffix or ''}"

    @property
    def full_ata(self) -> str:
        """Format ATA complet XX-YY-ZZ[A]"""
        return self.item_number

    # === DESCRIPTION ===
    item_description: str = Field(..., min_length=1, description="Description de l'équipement")

    # === CATÉGORIE ET DISPATCH ===
    category: Literal["A", "B", "C", "D"] = Field(..., description="Catégorie de dispatch")
    number_installed: str = Field(default="-", description="Nombre installé")
    number_required: str = Field(default="-", description="Nombre requis pour dispatch")
    rectification_interval: Optional[RectificationInterval] = None

    # === REMARQUES STRUCTURÉES ===
    remarks_raw: str = Field(default="", description="Remarques brutes")
    conditions: List[ApplicabilityCondition] = Field(
        default_factory=list,
        description="Conditions extraites (a), (b), (c)..."
    )
    has_operational_procedure: bool = Field(default=False, description="Contient (O)")
    has_maintenance_procedure: bool = Field(default=False, description="Contient (M)")

    # === CONTEXTE D'APPLICABILITÉ ===
    applicable_msn: List[MSNRange] = Field(
        default_factory=list,
        description="Plages MSN applicables"
    )
    operation_scope: List[OperationType] = Field(
        default_factory=list,
        description="Types d'opération: CAT, NCO, SPO, NCC"
    )
    aircraft_variants: List[str] = Field(
        default_factory=list,
        description="Variantes avion: A320-214, A320neo, etc."
    )

    # === RESTRICTIONS ===
    etops_restriction: Optional[str] = Field(None, description="Restriction ETOPS")
    altitude_restriction: Optional[str] = Field(None, description="Restriction altitude (ex: FL310)")
    rvsm_restriction: Optional[str] = Field(None, description="Restriction RVSM")
    icing_restriction: Optional[str] = Field(None, description="Restriction givrage")

    # === MÉTADONNÉES ===
    source_document: str = Field(default="", description="Document source")
    source_page: int = Field(default=0, ge=0, description="Page source")
    source_table: int = Field(default=0, ge=0, description="Index du tableau source")
    extraction_confidence: float = Field(default=1.0, ge=0, le=1, description="Confiance d'extraction")
    integrity_validated: bool = Field(default=False, description="Validé par IntegrityChecker")

    # === FLAGS HITL ===
    needs_hitl: bool = Field(default=False, description="Nécessite revue humaine")
    hitl_reasons: List[str] = Field(default_factory=list, description="Raisons HITL")

    @field_validator('ata_chapter', 'ata_section', mode='before')
    @classmethod
    def normalize_ata(cls, v: Any) -> str:
        """Normalise les chapitres/sections ATA"""
        return str(v).strip().zfill(2)

    @field_validator('category', mode='before')
    @classmethod
    def normalize_category(cls, v: Any) -> str:
        """Normalise la catégorie"""
        return str(v).strip().upper()

    @field_validator('remarks_raw', mode='before')
    @classmethod
    def normalize_remarks(cls, v: Any) -> str:
        """Nettoie les remarques"""
        if v is None:
            return ""
        return str(v).strip()

    @model_validator(mode='after')
    def extract_procedures_from_remarks(self) -> "MELItemV3":
        """Extrait les marqueurs (O) et (M) des remarques"""
        remarks_lower = self.remarks_raw.lower()

        if not self.has_operational_procedure:
            self.has_operational_procedure = bool(re.search(r'\(o\)', remarks_lower))

        if not self.has_maintenance_procedure:
            self.has_maintenance_procedure = bool(re.search(r'\(m\)', remarks_lower))

        return self

    @model_validator(mode='after')
    def validate_conditions_sequence(self) -> "MELItemV3":
        """Vérifie la séquence des conditions"""
        if not self.conditions:
            return self

        expected = 'a'
        for i, cond in enumerate(self.conditions):
            if cond.id != expected and cond.id != str(i + 1):
                self.hitl_reasons.append(
                    f"Séquence conditions rompue: attendu {expected}, trouvé {cond.id}"
                )
                self.needs_hitl = True
            expected = chr(ord(expected) + 1)

        return self

    def is_applicable_to(self, msn: int, operation: str) -> bool:
        """Vérifie si cet item s'applique au contexte donné"""
        # Vérifier MSN
        if self.applicable_msn:
            msn_match = any(r.matches(msn) for r in self.applicable_msn)
            if not msn_match:
                return False

        # Vérifier operation
        if self.operation_scope:
            if operation.upper() not in self.operation_scope:
                return False

        return True

    def get_category_rank(self) -> int:
        """Retourne le rang de restrictivité (1 = plus restrictif)"""
        return {"A": 1, "B": 2, "C": 3, "D": 4}.get(self.category, 5)

    def to_comparison_key(self) -> str:
        """Clé pour la comparaison MEL/MMEL"""
        return f"{self.ata_chapter}|{self.item_number}"

    def to_dict_legacy(self) -> Dict[str, Any]:
        """Conversion vers format legacy pour compatibilité"""
        return {
            "ata_chapter": self.ata_chapter,
            "ata_section": self.ata_section,
            "item_number": self.item_number,
            "item_description": self.item_description,
            "category": self.category,
            "number_installed": self.number_installed,
            "number_required": self.number_required,
            "repair_interval": self.rectification_interval.raw_text if self.rectification_interval else "",
            "remarks": self.remarks_raw,
            "source_page": self.source_page,
            "source_table": self.source_table,
            "extraction_confidence": self.extraction_confidence,
            # Champs enrichis
            "applicable_msn": [str(m) for m in self.applicable_msn],
            "operation_scope": list(self.operation_scope),
            "conditions": [{"id": c.id, "text": c.text} for c in self.conditions],
            "has_operational_procedure": self.has_operational_procedure,
            "has_maintenance_procedure": self.has_maintenance_procedure,
        }


class ParsingResultV3(BaseModel):
    """Résultat de parsing enrichi"""

    document_name: str
    document_type: Literal["MEL", "MMEL", "CS-MMEL"]
    aircraft_type: Optional[str] = None
    authority: Optional[str] = None  # EASA, FAA, etc.
    revision: Optional[str] = None
    effective_date: Optional[str] = None

    parsing_timestamp: str
    parser_version: str = "v3"

    statistics: Dict[str, Any] = Field(default_factory=dict)
    items: List[MELItemV3] = Field(default_factory=list)

    integrity_issues: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Problèmes d'intégrité détectés"
    )

    def get_by_item_number(self, item_number: str) -> Optional[MELItemV3]:
        """Recherche un item par son numéro"""
        for item in self.items:
            if item.item_number == item_number:
                return item
        return None

    def get_all_variants(self, item_base: str) -> List[MELItemV3]:
        """Retourne toutes les variantes d'un item de base"""
        return [item for item in self.items if item.item_base == item_base]

    def filter_by_context(self, msn: int, operation: str) -> List[MELItemV3]:
        """Filtre les items applicables au contexte"""
        return [
            item for item in self.items
            if item.is_applicable_to(msn, operation)
        ]


# === FONCTIONS UTILITAIRES ===

def parse_item_number(raw: str) -> Dict[str, Any]:
    """Parse un numéro d'item ATA en composants"""
    cleaned = re.sub(r'\s+', '', str(raw).strip())

    # Pattern: XX-YY-ZZ[A]
    pattern = r'^(\d{2})-(\d{2})-?(\d{2,3})([A-Z])?$'
    match = re.match(pattern, cleaned)

    if match:
        chapter, section, item, suffix = match.groups()
        item_base = f"{chapter}-{section}-{item.zfill(2)}"
        return {
            'valid': True,
            'chapter': chapter,
            'section': section,
            'item_base': item_base,
            'item_number': item_base + (suffix or ''),
            'suffix': suffix or ''
        }

    return {'valid': False, 'raw': raw}


def extract_conditions_from_remarks(remarks: str) -> List[ApplicabilityCondition]:
    """
    Extrait les sous-conditions (a), (b), (c), (d) des remarques.

    Note: (O) et (M) sont des indicateurs de procédure (Operations/Maintenance),
    PAS des conditions d'applicabilité. Ils sont exclus de l'extraction.
    """
    conditions = []
    seen_ids = set()

    # Pattern: (a) texte, (b) texte, etc.
    # Utilise [a-ln-z] pour exclure 'm' du pattern initial
    pattern = r'\(([a-ln-z])\)\s*([^(]+?)(?=\([a-z]\)|$)'
    matches = re.findall(pattern, remarks, re.IGNORECASE | re.DOTALL)

    for cond_id, text in matches:
        cond_id_lower = cond_id.lower()

        # Exclure (O) et (M) qui sont des indicateurs de procédure, pas des conditions
        if cond_id_lower in ('o', 'm'):
            continue

        # Éviter les doublons
        if cond_id_lower in seen_ids:
            continue

        text = text.strip().rstrip(',').rstrip(';').strip()
        if text:
            seen_ids.add(cond_id_lower)
            cond = ApplicabilityCondition(id=cond_id_lower, text=text)
            is_complete, _ = cond.check_completeness()
            cond.is_complete = is_complete
            conditions.append(cond)

    return conditions


def extract_operation_types(text: str) -> List[OperationType]:
    """Extrait les types d'opération du texte"""
    patterns = {
        r'\(CAT\)': "CAT",
        r'\(SPO\)': "SPO",
        r'\(NCO\)': "NCO",
        r'\(NCC\)': "NCC",
        r'\bCAT\b': "CAT",
        r'\bSPO\b': "SPO",
        r'\bNCO\b': "NCO",
        r'\bNCC\b': "NCC",
        r'COMMERCIAL': "COMMERCIAL",
        r'PRIVATE': "PRIVATE",
        r'CARGO': "CARGO",
    }

    found = []
    for pattern, op_type in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            if op_type not in found:
                found.append(op_type)

    return found


def extract_msn_ranges(text: str) -> List[MSNRange]:
    """Extrait toutes les plages MSN d'un texte"""
    ranges = []

    # Pattern global pour détecter les mentions MSN
    msn_mentions = re.findall(
        r'MSN\s*[\d,\s\-+andupetsuivants]+',
        text,
        re.IGNORECASE
    )

    for mention in msn_mentions:
        ranges.append(MSNRange.parse_from_text(mention))

    return ranges


if __name__ == "__main__":
    # Test des modèles
    item = MELItemV3(
        ata_chapter="21",
        ata_section="30",
        item_base="21-30-01",
        variant_suffix="D",
        item_description="Ice Detection System",
        category="C",
        number_installed="2",
        number_required="1",
        remarks_raw="(O)(M) May be inoperative provided: (a) icing conditions not expected, (b) crew briefed.",
        applicable_msn=[MSNRange.parse_from_text("MSN 545 and up")],
        operation_scope=["CAT", "SPO"],
        conditions=[
            ApplicabilityCondition(id="a", text="icing conditions not expected"),
            ApplicabilityCondition(id="b", text="crew briefed"),
        ]
    )

    print(f"Item: {item.item_number}")
    print(f"Applicable to MSN 1280 CAT: {item.is_applicable_to(1280, 'CAT')}")
    print(f"Applicable to MSN 100 CAT: {item.is_applicable_to(100, 'CAT')}")
    print(f"Has (O): {item.has_operational_procedure}")
    print(f"Has (M): {item.has_maintenance_procedure}")
    print(f"Conditions: {[c.id for c in item.conditions]}")
