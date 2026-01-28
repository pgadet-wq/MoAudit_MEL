#!/usr/bin/env python3
"""
MoA_MEL - Tree-Search Comparator
================================
Comparateur intelligent avec logique Tree-Search.

Remplace la comparaison linéaire (1 MEL = 1 MMEL) par:
1. Filtrage contextuel (MSN, Operation)
2. Matching de variante intelligente
3. Comparaison sémantique des conditions
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from datetime import datetime

# Import des modules locaux
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from matching.mmel_variant_tree import MMELVariantTree, AircraftContext, MatchConfidence, MatchResult as VariantMatchResult
except ImportError:
    MMELVariantTree = None
    AircraftContext = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TreeSearchComparator")


class Severity(Enum):
    """Sévérité des écarts"""
    INFO = "info"
    WARNING = "warning"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(Enum):
    """Verdicts de comparaison"""
    COMPLIANT = "COMPLIANT"
    MORE_RESTRICTIVE = "MORE_RESTRICTIVE"
    LESS_RESTRICTIVE = "LESS_RESTRICTIVE"
    MISSING_IN_MEL = "MISSING_IN_MEL"
    MISSING_IN_MMEL = "MISSING_IN_MMEL"
    VARIANT_MISMATCH = "VARIANT_MISMATCH"
    CONDITIONS_DEVIATION = "CONDITIONS_DEVIATION"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"


@dataclass
class ConditionComparison:
    """Résultat de comparaison des conditions"""

    mel_conditions: List[Dict[str, str]]
    mmel_conditions: List[Dict[str, str]]
    missing_in_mel: List[str]  # IDs des conditions MMEL absentes
    extra_in_mel: List[str]    # IDs des conditions MEL additionnelles
    modified: List[Dict[str, Any]]  # Conditions modifiées
    is_less_restrictive: bool
    is_more_restrictive: bool
    notes: str = ""


@dataclass
class ComparisonDetail:
    """Détail d'une comparaison de champ"""

    field: str
    mel_value: Any
    mmel_value: Any
    status: str  # "equal", "more_restrictive", "less_restrictive", "different"
    notes: str = ""
    severity: Severity = Severity.INFO


@dataclass
class ComparisonResultV2:
    """Résultat enrichi de comparaison"""

    # Identifiants
    mel_item_id: str
    mmel_item_id: Optional[str]
    mel_item_base: str
    mmel_variant_suffix: str

    # Contexte
    aircraft_context: Optional[Dict[str, Any]]
    match_confidence: str  # exact, variant, partial, inferred, none

    # Verdict
    verdict: Verdict
    severity: Severity
    compliance_score: float  # 0.0 à 1.0

    # Détails
    details: List[ComparisonDetail] = field(default_factory=list)
    conditions_comparison: Optional[ConditionComparison] = None

    # Données comparées
    mel_data: Dict[str, Any] = field(default_factory=dict)
    mmel_data: Dict[str, Any] = field(default_factory=dict)

    # HITL
    requires_hitl: bool = False
    hitl_reasons: List[str] = field(default_factory=list)
    sla_hours: int = 0

    # Métadonnées
    compared_at: str = ""
    alternatives_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Conversion en dictionnaire"""
        return {
            "mel_item_id": self.mel_item_id,
            "mmel_item_id": self.mmel_item_id,
            "mel_item_base": self.mel_item_base,
            "mmel_variant_suffix": self.mmel_variant_suffix,
            "aircraft_context": self.aircraft_context,
            "match_confidence": self.match_confidence,
            "verdict": self.verdict.value,
            "severity": self.severity.value,
            "compliance_score": self.compliance_score,
            "details": [
                {
                    "field": d.field,
                    "mel_value": d.mel_value,
                    "mmel_value": d.mmel_value,
                    "status": d.status,
                    "notes": d.notes
                }
                for d in self.details
            ],
            "requires_hitl": self.requires_hitl,
            "hitl_reasons": self.hitl_reasons,
            "sla_hours": self.sla_hours,
            "compared_at": self.compared_at
        }


@dataclass
class AuditResultV2:
    """Résultat global d'audit V2"""

    mel_document: str
    mmel_document: str
    aircraft_context: Dict[str, Any]
    audit_timestamp: str

    # Statistiques
    total_comparisons: int = 0
    compliant_count: int = 0
    more_restrictive_count: int = 0
    less_restrictive_count: int = 0
    variant_issues_count: int = 0
    missing_count: int = 0
    not_applicable_count: int = 0  # Items MMEL non applicables aux operations de la compagnie

    # Par sévérité
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    # HITL
    hitl_required_count: int = 0

    # Scores
    overall_compliance_rate: float = 0.0

    # Détails
    comparisons: List[ComparisonResultV2] = field(default_factory=list)

    def compute_statistics(self):
        """Calcule les statistiques depuis les comparaisons"""
        self.total_comparisons = len(self.comparisons)

        for comp in self.comparisons:
            if comp.verdict == Verdict.COMPLIANT:
                self.compliant_count += 1
            elif comp.verdict == Verdict.MORE_RESTRICTIVE:
                self.more_restrictive_count += 1
            elif comp.verdict == Verdict.LESS_RESTRICTIVE:
                self.less_restrictive_count += 1
            elif comp.verdict in [Verdict.MISSING_IN_MEL, Verdict.MISSING_IN_MMEL]:
                self.missing_count += 1
            elif comp.verdict == Verdict.VARIANT_MISMATCH:
                self.variant_issues_count += 1
            elif comp.verdict == Verdict.CONTEXT_MISMATCH:
                self.not_applicable_count += 1  # Items non applicables (operations differentes)

            # Sévérité
            if comp.severity == Severity.CRITICAL:
                self.critical_count += 1
            elif comp.severity == Severity.HIGH:
                self.high_count += 1
            elif comp.severity == Severity.MEDIUM:
                self.medium_count += 1
            elif comp.severity == Severity.WARNING:
                self.warning_count += 1
            else:
                self.info_count += 1

            if comp.requires_hitl:
                self.hitl_required_count += 1

        # Taux de conformité (exclut les items non applicables)
        applicable_items = self.total_comparisons - self.not_applicable_count
        if applicable_items > 0:
            conforming = self.compliant_count + self.more_restrictive_count
            self.overall_compliance_rate = round(
                conforming / applicable_items * 100, 2
            )


class TreeSearchComparator:
    """
    Comparateur avec logique Tree-Search.

    Workflow:
    1. Recevoir le contexte avion (MSN, operation, etc.)
    2. Pour chaque item MEL:
       a. Trouver la variante MMEL applicable via VariantTree
       b. Comparer catégorie, quantités, conditions
       c. Générer verdict et sévérité
    3. Gérer les items MMEL non couverts par la MEL
    """

    # Hiérarchie des catégories (1 = plus restrictif)
    CATEGORY_HIERARCHY = {"A": 1, "B": 2, "C": 3, "D": 4, "-": 5, "": 5}

    # SLA par sévérité (heures)
    SLA_HOURS = {
        Severity.CRITICAL: 48,
        Severity.HIGH: 48,
        Severity.MEDIUM: 72,
        Severity.WARNING: 168,
        Severity.INFO: 0
    }

    def __init__(self, mmel_tree: Optional["MMELVariantTree"] = None):
        self.mmel_tree = mmel_tree
        self.comparison_count = 0

    def set_mmel_tree(self, tree: "MMELVariantTree"):
        """Définit l'arbre MMEL à utiliser"""
        self.mmel_tree = tree

    def compare_categories(self, mel_cat: str, mmel_cat: str) -> ComparisonDetail:
        """Compare deux catégories"""
        mel_rank = self.CATEGORY_HIERARCHY.get(mel_cat.upper().strip(), 5)
        mmel_rank = self.CATEGORY_HIERARCHY.get(mmel_cat.upper().strip(), 5)

        if mel_rank == mmel_rank:
            return ComparisonDetail(
                field="category",
                mel_value=mel_cat,
                mmel_value=mmel_cat,
                status="equal",
                notes="Catégories identiques",
                severity=Severity.INFO
            )
        elif mel_rank < mmel_rank:
            return ComparisonDetail(
                field="category",
                mel_value=mel_cat,
                mmel_value=mmel_cat,
                status="more_restrictive",
                notes=f"MEL ({mel_cat}) plus restrictive que MMEL ({mmel_cat})",
                severity=Severity.INFO
            )
        else:
            return ComparisonDetail(
                field="category",
                mel_value=mel_cat,
                mmel_value=mmel_cat,
                status="less_restrictive",
                notes=f"MEL ({mel_cat}) MOINS restrictive que MMEL ({mmel_cat}) - VIOLATION",
                severity=Severity.CRITICAL
            )

    def compare_quantities(self, mel_required: str, mmel_required: str,
                          mel_installed: str = "", mmel_installed: str = "") -> ComparisonDetail:
        """Compare les quantités requises"""
        mel_val = self._parse_quantity(mel_required)
        mmel_val = self._parse_quantity(mmel_required)

        if mel_val is None or mmel_val is None:
            return ComparisonDetail(
                field="number_required",
                mel_value=mel_required,
                mmel_value=mmel_required,
                status="unknown",
                notes="Impossible de parser les quantités",
                severity=Severity.WARNING
            )

        if mel_val == mmel_val:
            return ComparisonDetail(
                field="number_required",
                mel_value=mel_required,
                mmel_value=mmel_required,
                status="equal",
                notes=f"Quantités identiques ({mel_val})",
                severity=Severity.INFO
            )
        elif mel_val > mmel_val:
            return ComparisonDetail(
                field="number_required",
                mel_value=mel_required,
                mmel_value=mmel_required,
                status="more_restrictive",
                notes=f"MEL exige plus ({mel_val}) que MMEL ({mmel_val})",
                severity=Severity.INFO
            )
        else:
            return ComparisonDetail(
                field="number_required",
                mel_value=mel_required,
                mmel_value=mmel_required,
                status="less_restrictive",
                notes=f"MEL exige moins ({mel_val}) que MMEL ({mmel_val})",
                severity=Severity.HIGH
            )

    def compare_conditions(self, mel_conditions: List[Dict],
                          mmel_conditions: List[Dict]) -> ConditionComparison:
        """Compare les conditions d'applicabilité"""
        mel_ids = {c.get("id", "").lower(): c.get("text", "") for c in mel_conditions}
        mmel_ids = {c.get("id", "").lower(): c.get("text", "") for c in mmel_conditions}

        # Conditions MMEL manquantes dans MEL
        missing_in_mel = [
            cid for cid in mmel_ids.keys()
            if cid not in mel_ids
        ]

        # Conditions supplémentaires dans MEL
        extra_in_mel = [
            cid for cid in mel_ids.keys()
            if cid not in mmel_ids
        ]

        # Conditions modifiées
        modified = []
        for cid in set(mel_ids.keys()) & set(mmel_ids.keys()):
            mel_text = mel_ids[cid].lower().strip()
            mmel_text = mmel_ids[cid].lower().strip()

            if mel_text != mmel_text:
                # Analyser si plus ou moins restrictif
                modified.append({
                    "id": cid,
                    "mel_text": mel_ids[cid],
                    "mmel_text": mmel_ids[cid],
                    "analysis": self._analyze_condition_change(mel_ids[cid], mmel_ids[cid])
                })

        is_less = len(missing_in_mel) > 0
        is_more = len(extra_in_mel) > 0 and len(missing_in_mel) == 0

        notes = []
        if missing_in_mel:
            notes.append(f"Conditions MMEL absentes: {missing_in_mel}")
        if extra_in_mel:
            notes.append(f"Conditions MEL additionnelles: {extra_in_mel}")
        if modified:
            notes.append(f"{len(modified)} condition(s) modifiée(s)")

        return ConditionComparison(
            mel_conditions=mel_conditions,
            mmel_conditions=mmel_conditions,
            missing_in_mel=missing_in_mel,
            extra_in_mel=extra_in_mel,
            modified=modified,
            is_less_restrictive=is_less,
            is_more_restrictive=is_more,
            notes="; ".join(notes) if notes else "Conditions identiques"
        )

    def _analyze_condition_change(self, mel_text: str, mmel_text: str) -> str:
        """Analyse le changement entre deux textes de condition"""
        mel_words = set(mel_text.lower().split())
        mmel_words = set(mmel_text.lower().split())

        mel_only = mel_words - mmel_words
        mmel_only = mmel_words - mel_words

        if not mel_only and not mmel_only:
            return "reformulation_mineure"
        elif len(mel_only) > len(mmel_only):
            return "mel_plus_detaille"
        elif len(mmel_only) > len(mel_only):
            return "mel_moins_detaille"
        else:
            return "modification_significative"

    def _parse_quantity(self, value: str) -> Optional[int]:
        """Parse une quantité depuis une chaîne"""
        if not value or value in ['-', 'N/A', 'As installed', 'AR', '']:
            return None
        match = re.search(r'(\d+)', str(value))
        return int(match.group(1)) if match else None

    def compare_item(self, mel_item: Dict[str, Any],
                    aircraft_context: "AircraftContext") -> ComparisonResultV2:
        """
        Compare un item MEL avec la variante MMEL applicable.

        Args:
            mel_item: Item MEL à comparer
            aircraft_context: Contexte de l'avion

        Returns:
            ComparisonResultV2 avec verdict et détails
        """
        mel_item_id = mel_item.get("item_number", "")
        mel_item_base = mel_item.get("item_base", "")

        if not mel_item_base:
            # Tenter extraction
            parsed = self._parse_item_number(mel_item_id)
            if parsed:
                mel_item_base = parsed["item_base"]

        # Trouver la variante MMEL applicable
        if self.mmel_tree:
            match_result = self.mmel_tree.match_mel_item(
                mel_item,
                msn=aircraft_context.msn,
                operations=aircraft_context.operation_types,  # Liste d'operations
                aircraft=aircraft_context.aircraft_type
            )
            mmel_variant = match_result.matched_variant
            match_confidence = match_result.confidence.value
            alternatives_count = len(match_result.alternatives)
        else:
            mmel_variant = None
            match_confidence = "none"
            alternatives_count = 0

        # Cas: pas de MMEL correspondant
        if mmel_variant is None:
            return ComparisonResultV2(
                mel_item_id=mel_item_id,
                mmel_item_id=None,
                mel_item_base=mel_item_base,
                mmel_variant_suffix="",
                aircraft_context={"msn": aircraft_context.msn, "operations": aircraft_context.operation_types},
                match_confidence=match_confidence,
                verdict=Verdict.MISSING_IN_MMEL,
                severity=Severity.INFO,
                compliance_score=1.0,
                mel_data=mel_item,
                mmel_data={},
                compared_at=datetime.now().isoformat(),
                alternatives_count=0
            )

        mmel_data = mmel_variant.item_data

        # Comparer les attributs
        details = []
        verdicts = []

        # 1. Catégories
        cat_detail = self.compare_categories(
            mel_item.get("category", ""),
            mmel_data.get("category", "")
        )
        details.append(cat_detail)
        verdicts.append(cat_detail.status)

        # 2. Quantités
        qty_detail = self.compare_quantities(
            mel_item.get("number_required", ""),
            mmel_data.get("number_required", ""),
            mel_item.get("number_installed", ""),
            mmel_data.get("number_installed", "")
        )
        details.append(qty_detail)
        if qty_detail.status != "unknown":
            verdicts.append(qty_detail.status)

        # 3. Conditions
        mel_conditions = mel_item.get("conditions", [])
        mmel_conditions = mmel_data.get("conditions", [])

        # Si pas de conditions structurées, tenter extraction des remarks
        if not mel_conditions and mel_item.get("remarks_raw"):
            mel_conditions = self._extract_conditions(mel_item.get("remarks_raw", ""))
        if not mmel_conditions and mmel_data.get("remarks_raw"):
            mmel_conditions = self._extract_conditions(mmel_data.get("remarks_raw", ""))

        cond_comparison = None
        if mel_conditions or mmel_conditions:
            cond_comparison = self.compare_conditions(mel_conditions, mmel_conditions)
            if cond_comparison.is_less_restrictive:
                verdicts.append("less_restrictive")
            elif cond_comparison.is_more_restrictive:
                verdicts.append("more_restrictive")

        # 4. Procédures (O) et (M)
        mel_has_m = mel_item.get("has_maintenance_procedure", False)
        mmel_has_m = mmel_data.get("has_maintenance_procedure", False)
        if mmel_has_m and not mel_has_m:
            details.append(ComparisonDetail(
                field="maintenance_procedure",
                mel_value=mel_has_m,
                mmel_value=mmel_has_m,
                status="less_restrictive",
                notes="Procédure maintenance (M) MMEL absente dans MEL",
                severity=Severity.MEDIUM
            ))
            verdicts.append("less_restrictive")

        # Déterminer le verdict final
        if "less_restrictive" in verdicts:
            final_verdict = Verdict.LESS_RESTRICTIVE
            severity = Severity.CRITICAL
        elif all(v == "equal" for v in verdicts):
            final_verdict = Verdict.COMPLIANT
            severity = Severity.INFO
        elif "more_restrictive" in verdicts and "less_restrictive" not in verdicts:
            final_verdict = Verdict.MORE_RESTRICTIVE
            severity = Severity.INFO
        elif match_confidence in ["partial", "inferred"]:
            final_verdict = Verdict.VARIANT_MISMATCH
            severity = Severity.WARNING
        else:
            final_verdict = Verdict.COMPLIANT
            severity = Severity.INFO

        # Score de conformité
        compliance_score = 1.0
        if final_verdict == Verdict.LESS_RESTRICTIVE:
            compliance_score = 0.0
        elif final_verdict == Verdict.VARIANT_MISMATCH:
            compliance_score = 0.7
        elif final_verdict == Verdict.MORE_RESTRICTIVE:
            compliance_score = 1.0

        # HITL requis?
        requires_hitl = severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM]
        hitl_reasons = []
        if requires_hitl:
            if final_verdict == Verdict.LESS_RESTRICTIVE:
                hitl_reasons.append("CRITIQUE: MEL moins restrictive que MMEL")
            if match_confidence == "partial":
                hitl_reasons.append(f"Match partiel: vérifier variante {mmel_variant.item_number}")
            if cond_comparison and cond_comparison.missing_in_mel:
                hitl_reasons.append(f"Conditions MMEL manquantes: {cond_comparison.missing_in_mel}")

        return ComparisonResultV2(
            mel_item_id=mel_item_id,
            mmel_item_id=mmel_variant.item_number,
            mel_item_base=mel_item_base,
            mmel_variant_suffix=mmel_variant.suffix,
            aircraft_context={
                "msn": aircraft_context.msn,
                "operations": aircraft_context.operation_types,  # Liste d'operations
                "aircraft": aircraft_context.aircraft_type
            },
            match_confidence=match_confidence,
            verdict=final_verdict,
            severity=severity,
            compliance_score=compliance_score,
            details=details,
            conditions_comparison=cond_comparison,
            mel_data=mel_item,
            mmel_data=mmel_data,
            requires_hitl=requires_hitl,
            hitl_reasons=hitl_reasons,
            sla_hours=self.SLA_HOURS.get(severity, 0),
            compared_at=datetime.now().isoformat(),
            alternatives_count=alternatives_count
        )

    def _parse_item_number(self, item_number: str) -> Optional[Dict[str, str]]:
        """Parse un numéro d'item"""
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

    def _extract_conditions(self, remarks: str) -> List[Dict[str, str]]:
        """
        Extrait les conditions depuis les remarks.

        Note: (O) et (M) sont des indicateurs de procédure (Operations/Maintenance),
        PAS des conditions. Les vraies conditions sont (a), (b), (c), (d), etc.
        """
        conditions = []
        seen_ids = set()

        # Pattern pour capturer (lettre) suivi du texte
        # Exclut O et M qui sont des indicateurs de procédure
        pattern = r'\(([a-ln-z])\)\s*([^(]+?)(?=\([a-z]\)|$)'
        matches = re.findall(pattern, remarks, re.IGNORECASE | re.DOTALL)

        for cid, text in matches:
            cid_lower = cid.lower()
            # Double vérification: exclure o et m
            if cid_lower in ('o', 'm'):
                continue
            # Éviter les doublons
            if cid_lower in seen_ids:
                continue

            text = text.strip().rstrip(',').rstrip(';').strip()
            # Ignorer les textes trop courts ou vides
            if text and len(text) > 3:
                seen_ids.add(cid_lower)
                conditions.append({
                    "id": cid_lower,
                    "text": text
                })

        return conditions

    def run_audit(self, mel_items: List[Dict[str, Any]],
                 aircraft_context: "AircraftContext",
                 mel_document: str = "MEL",
                 mmel_document: str = "MMEL") -> AuditResultV2:
        """
        Exécute l'audit complet avec Tree-Search.

        Args:
            mel_items: Liste des items MEL
            aircraft_context: Contexte de l'avion
            mel_document: Nom du document MEL
            mmel_document: Nom du document MMEL

        Returns:
            AuditResultV2 avec tous les résultats
        """
        result = AuditResultV2(
            mel_document=mel_document,
            mmel_document=mmel_document,
            aircraft_context={
                "msn": aircraft_context.msn,
                "operations": aircraft_context.operation_types,  # Liste d'operations
                "aircraft": aircraft_context.aircraft_type,
                "etops": aircraft_context.etops_certified
            },
            audit_timestamp=datetime.now().isoformat()
        )

        # Comparer chaque item MEL
        matched_mmel_items = set()

        for mel_item in mel_items:
            comparison = self.compare_item(mel_item, aircraft_context)
            result.comparisons.append(comparison)

            if comparison.mmel_item_id:
                matched_mmel_items.add(comparison.mmel_item_id)

        # Identifier les items MMEL non couverts
        if self.mmel_tree:
            all_mmel_items = set(self.mmel_tree.by_item_number.keys())
            uncovered_mmel = all_mmel_items - matched_mmel_items

            for mmel_item_id in uncovered_mmel:
                mmel_variant = self.mmel_tree.get_item(mmel_item_id)
                if mmel_variant:
                    # Vérifier applicabilité aux operations de la compagnie
                    is_applicable = mmel_variant.context.matches(
                        aircraft_context.msn,
                        aircraft_context.operation_types,  # Liste d'operations
                        aircraft_context.aircraft_type
                    )

                    if is_applicable:
                        # Item applicable non couvert → WARNING/CRITIQUE
                        severity = Severity.WARNING
                        verdict = Verdict.MISSING_IN_MEL
                        hitl_reason = "Item MMEL applicable non couvert par la MEL"
                        compliance_score = 0.5
                        requires_hitl = True
                    else:
                        # Item non applicable → INFO (ignoré)
                        severity = Severity.INFO
                        verdict = Verdict.CONTEXT_MISMATCH
                        item_ops = mmel_variant.context.operation_types
                        hitl_reason = f"Item MMEL ignoré - concerne {item_ops}, compagnie: {aircraft_context.operation_types}"
                        compliance_score = 1.0  # Ne compte pas contre la conformité
                        requires_hitl = False

                    result.comparisons.append(ComparisonResultV2(
                        mel_item_id="",
                        mmel_item_id=mmel_item_id,
                        mel_item_base=mmel_variant.item_base,
                        mmel_variant_suffix=mmel_variant.suffix,
                        aircraft_context={
                            "msn": aircraft_context.msn,
                            "operations": aircraft_context.operation_types
                        },
                        match_confidence="none",
                        verdict=verdict,
                        severity=severity,
                        compliance_score=compliance_score,
                        mmel_data=mmel_variant.item_data,
                        requires_hitl=requires_hitl,
                        hitl_reasons=[hitl_reason],
                        sla_hours=self.SLA_HOURS.get(severity, 0),
                        compared_at=datetime.now().isoformat()
                    ))

        # Calculer les statistiques
        result.compute_statistics()

        logger.info(f"Audit terminé: {result.total_comparisons} comparaisons, "
                   f"Conformité: {result.overall_compliance_rate}%")

        return result


# === TESTS ===
if __name__ == "__main__":
    from matching.mmel_variant_tree import MMELVariantTree, AircraftContext

    # Créer l'arbre MMEL
    tree = MMELVariantTree()

    mmel_items = [
        {
            "item_number": "21-30-01A",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System",
            "category": "C",
            "number_installed": "2",
            "number_required": "1",
            "remarks_raw": "(O) May be inoperative provided: (a) icing not expected, (b) crew briefed.",
            "conditions": [
                {"id": "a", "text": "icing not expected"},
                {"id": "b", "text": "crew briefed"}
            ],
            "applicable_msn": ["MSN 101-544"],
            "operation_scope": ["CAT"]
        },
        {
            "item_number": "21-30-01B",
            "item_base": "21-30-01",
            "item_description": "Ice Detection System",
            "category": "B",  # Plus restrictif
            "number_installed": "2",
            "number_required": "1",
            "remarks_raw": "(O)(M) May be inoperative provided: (a) icing not expected, (b) crew briefed, (c) maintenance check done.",
            "conditions": [
                {"id": "a", "text": "icing not expected"},
                {"id": "b", "text": "crew briefed"},
                {"id": "c", "text": "maintenance check done"}
            ],
            "has_maintenance_procedure": True,
            "applicable_msn": ["MSN 545 and up"],
            "operation_scope": ["CAT"]
        }
    ]

    tree.build_from_items(mmel_items)

    # Créer le comparateur
    comparator = TreeSearchComparator(tree)

    # Contexte avion
    aircraft = AircraftContext(
        msn=1280,
        operation_types=["CAT"],  # Liste d'operations
        aircraft_type="A320-214"
    )

    # Item MEL à tester (moins restrictif que MMEL)
    mel_item = {
        "item_number": "21-30-01",
        "item_base": "21-30-01",
        "item_description": "Ice Detection System",
        "category": "C",  # MMEL exige B pour ce MSN!
        "number_installed": "2",
        "number_required": "1",
        "remarks_raw": "(O) May be inoperative provided: (a) icing not expected.",
        "conditions": [
            {"id": "a", "text": "icing not expected"}
            # Manque (b) et (c)!
        ],
        "has_maintenance_procedure": False  # Manque (M)!
    }

    # Exécuter la comparaison
    result = comparator.compare_item(mel_item, aircraft)

    print("=" * 60)
    print("Test Tree-Search Comparator")
    print("=" * 60)
    print(f"\nContexte: {aircraft.describe()}")
    print(f"\nMEL Item: {mel_item['item_number']}")
    print(f"MMEL Matched: {result.mmel_item_id}")
    print(f"Match Confidence: {result.match_confidence}")
    print(f"\nVerdict: {result.verdict.value}")
    print(f"Severity: {result.severity.value}")
    print(f"Compliance Score: {result.compliance_score}")

    print(f"\nDétails:")
    for detail in result.details:
        print(f"  - {detail.field}: {detail.status} - {detail.notes}")

    if result.conditions_comparison:
        print(f"\nConditions:")
        print(f"  Missing in MEL: {result.conditions_comparison.missing_in_mel}")
        print(f"  Extra in MEL: {result.conditions_comparison.extra_in_mel}")

    if result.hitl_reasons:
        print(f"\nHITL Reasons:")
        for reason in result.hitl_reasons:
            print(f"  - {reason}")
