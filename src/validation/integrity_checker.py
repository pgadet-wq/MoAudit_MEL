#!/usr/bin/env python3
"""
MoA_MEL - Integrity Checker avec Self-Healing
==============================================
Validation d'intégrité post-extraction avec capacité de ré-extraction ciblée.

Résout:
- Troncature du texte (Remarks/Conditions)
- Phrases incomplètes
- Conditions (a), (b), (c) manquantes ou fragmentées
- Cohérence sémantique
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Callable
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IntegrityChecker")


class IssueType(Enum):
    """Types de problèmes d'intégrité"""
    TRUNCATED_TEXT = "truncated_text"
    INCOMPLETE_CONDITION = "incomplete_condition"
    MISSING_CONDITION = "missing_condition"
    CATEGORY_INCONSISTENCY = "category_inconsistency"
    QUANTITY_INCONSISTENCY = "quantity_inconsistency"
    MISSING_PROCEDURE_MARKER = "missing_procedure_marker"
    INVALID_ATA = "invalid_ata"


class IssueSeverity(Enum):
    """Sévérité du problème"""
    ERROR = "error"      # Doit être corrigé
    WARNING = "warning"  # Devrait être vérifié
    INFO = "info"        # Information


@dataclass
class IntegrityIssue:
    """Problème d'intégrité détecté"""

    issue_type: IssueType
    severity: IssueSeverity
    field: str
    message: str
    original_value: str
    suggested_action: str
    auto_fixable: bool = False
    fixed_value: Optional[str] = None

    # Contexte pour ré-extraction
    source_page: Optional[int] = None
    extraction_hint: str = ""


@dataclass
class IntegrityReport:
    """Rapport d'intégrité pour un item"""

    item_number: str
    is_valid: bool
    issues: List[IntegrityIssue] = field(default_factory=list)
    auto_fixed_count: int = 0
    requires_reextraction: bool = False
    reextraction_hints: List[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)


class IntegrityChecker:
    """
    Vérificateur d'intégrité avec capacités de self-healing.

    Vérifie:
    1. Complétude des phrases (terminaisons valides)
    2. Séquence des conditions (a), (b), (c)
    3. Cohérence catégorie/quantité
    4. Présence des marqueurs (O)/(M)
    5. Validité des formats ATA
    """

    # Terminaisons de phrase incomplètes
    INCOMPLETE_ENDINGS = [
        (r'\band\s*$', "se termine par 'and'"),
        (r'\bor\s*$', "se termine par 'or'"),
        (r'\bwith\s*$', "se termine par 'with'"),
        (r'\bthe\s*$', "se termine par 'the'"),
        (r'\bto\s*$', "se termine par 'to'"),
        (r'\bfor\s*$', "se termine par 'for'"),
        (r'\bprovided\s*$', "se termine par 'provided'"),
        (r'\bif\s*$', "se termine par 'if'"),
        (r'\bthat\s*$', "se termine par 'that'"),
        (r'\bwhen\s*$', "se termine par 'when'"),
        (r'\bwhere\s*$', "se termine par 'where'"),
        (r'\bbefore\s*$', "se termine par 'before'"),
        (r'\bafter\s*$', "se termine par 'after'"),
        (r'\bunless\s*$', "se termine par 'unless'"),
        (r',\s*$', "se termine par une virgule"),
        (r':\s*$', "se termine par deux-points sans suite"),
    ]

    # Terminaisons valides
    VALID_ENDINGS = ['.', '!', '?', ')', ']', '"']

    # Pattern de condition
    CONDITION_PATTERN = re.compile(r'\(([a-z])\)\s*([^(]+?)(?=\([a-z]\)|$)', re.IGNORECASE | re.DOTALL)

    # Pattern ATA
    ATA_PATTERN = re.compile(r'^\d{2}-\d{2}-\d{2,3}[A-Z]?$')

    def __init__(self, auto_fix: bool = True):
        self.auto_fix = auto_fix
        self.reextraction_callback: Optional[Callable] = None

    def set_reextraction_callback(self, callback: Callable):
        """Définit le callback pour la ré-extraction"""
        self.reextraction_callback = callback

    def check_sentence_completeness(self, text: str, field_name: str) -> List[IntegrityIssue]:
        """Vérifie qu'une phrase/texte est complet"""
        issues = []
        text = text.strip()

        if not text:
            return issues  # Vide est acceptable

        # Vérifier les terminaisons incomplètes
        for pattern, reason in self.INCOMPLETE_ENDINGS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append(IntegrityIssue(
                    issue_type=IssueType.TRUNCATED_TEXT,
                    severity=IssueSeverity.ERROR,
                    field=field_name,
                    message=f"Texte tronqué: {reason}",
                    original_value=text,
                    suggested_action="Ré-extraire avec fenêtre élargie",
                    auto_fixable=False,
                    extraction_hint=f"Texte se terminant par pattern incomplet, étendre la zone"
                ))
                break

        # Vérifier la terminaison valide (sauf textes courts)
        if len(text.split()) > 5 and not any(text.endswith(end) for end in self.VALID_ENDINGS):
            # Exception: listes numérotées peuvent ne pas avoir de point
            if not re.search(r'\d+\s*$', text):
                issues.append(IntegrityIssue(
                    issue_type=IssueType.TRUNCATED_TEXT,
                    severity=IssueSeverity.WARNING,
                    field=field_name,
                    message="Pas de ponctuation finale",
                    original_value=text,
                    suggested_action="Vérifier si le texte est complet",
                    auto_fixable=False
                ))

        return issues

    def check_conditions_sequence(self, conditions: List[Dict[str, str]],
                                 remarks_text: str) -> List[IntegrityIssue]:
        """Vérifie la séquence et complétude des conditions"""
        issues = []

        if not conditions and not remarks_text:
            return issues

        # Extraire les conditions du texte brut si nécessaire
        if not conditions and remarks_text:
            matches = self.CONDITION_PATTERN.findall(remarks_text)
            conditions = [{"id": m[0].lower(), "text": m[1].strip()} for m in matches]

        if not conditions:
            # Vérifier si le texte contient des marqueurs de condition sans extraction
            if re.search(r'\([a-d]\)', remarks_text, re.IGNORECASE):
                issues.append(IntegrityIssue(
                    issue_type=IssueType.MISSING_CONDITION,
                    severity=IssueSeverity.ERROR,
                    field="conditions",
                    message="Conditions détectées dans le texte mais non extraites",
                    original_value=remarks_text,
                    suggested_action="Ré-parser les conditions",
                    auto_fixable=True
                ))
            return issues

        # Vérifier la séquence
        expected = 'a'
        for cond in conditions:
            cond_id = cond.get("id", "").lower()

            if cond_id != expected:
                issues.append(IntegrityIssue(
                    issue_type=IssueType.MISSING_CONDITION,
                    severity=IssueSeverity.ERROR,
                    field="conditions",
                    message=f"Séquence rompue: attendu ({expected}), trouvé ({cond_id})",
                    original_value=f"Conditions: {[c.get('id') for c in conditions]}",
                    suggested_action="Vérifier si des conditions sont manquantes",
                    auto_fixable=False,
                    extraction_hint=f"Condition ({expected}) potentiellement manquante"
                ))

            expected = chr(ord(expected) + 1)

            # Vérifier la complétude de chaque condition
            cond_text = cond.get("text", "")
            text_issues = self.check_sentence_completeness(cond_text, f"condition_{cond_id}")
            for issue in text_issues:
                issue.message = f"Condition ({cond_id}): {issue.message}"
                issues.append(issue)

        return issues

    def check_category_consistency(self, category: str, number_installed: str,
                                  number_required: str) -> List[IntegrityIssue]:
        """Vérifie la cohérence catégorie/quantités"""
        issues = []

        try:
            installed = self._parse_quantity(number_installed)
            required = self._parse_quantity(number_required)
        except ValueError:
            return issues  # Quantités non parsables, pas d'erreur

        if category == "A":
            # Cat A: Go item, required doit égaler installed
            if installed is not None and required is not None:
                if required != installed:
                    issues.append(IntegrityIssue(
                        issue_type=IssueType.CATEGORY_INCONSISTENCY,
                        severity=IssueSeverity.WARNING,
                        field="category",
                        message=f"Cat A mais required ({required}) != installed ({installed})",
                        original_value=f"Category: {category}, Req: {required}, Inst: {installed}",
                        suggested_action="Vérifier si la catégorie est correcte",
                        auto_fixable=False
                    ))

        elif category == "D":
            # Cat D: Optional, required devrait être 0 ou -
            if required is not None and required > 0:
                issues.append(IntegrityIssue(
                    issue_type=IssueType.CATEGORY_INCONSISTENCY,
                    severity=IssueSeverity.INFO,
                    field="category",
                    message=f"Cat D avec required > 0 ({required})",
                    original_value=f"Category: {category}, Required: {required}",
                    suggested_action="Vérifier le nombre requis",
                    auto_fixable=False
                ))

        return issues

    def check_procedure_markers(self, remarks: str, has_operational: bool,
                               has_maintenance: bool) -> List[IntegrityIssue]:
        """Vérifie la cohérence des marqueurs (O) et (M)"""
        issues = []
        remarks_lower = remarks.lower()

        # Vérifier (O)
        has_o_in_text = bool(re.search(r'\(o\)', remarks_lower))
        if has_o_in_text != has_operational:
            issues.append(IntegrityIssue(
                issue_type=IssueType.MISSING_PROCEDURE_MARKER,
                severity=IssueSeverity.WARNING,
                field="has_operational_procedure",
                message=f"Incohérence (O): texte={has_o_in_text}, flag={has_operational}",
                original_value=remarks,
                suggested_action="Synchroniser le flag avec le texte",
                auto_fixable=True,
                fixed_value=str(has_o_in_text)
            ))

        # Vérifier (M)
        has_m_in_text = bool(re.search(r'\(m\)', remarks_lower))
        if has_m_in_text != has_maintenance:
            issues.append(IntegrityIssue(
                issue_type=IssueType.MISSING_PROCEDURE_MARKER,
                severity=IssueSeverity.WARNING,
                field="has_maintenance_procedure",
                message=f"Incohérence (M): texte={has_m_in_text}, flag={has_maintenance}",
                original_value=remarks,
                suggested_action="Synchroniser le flag avec le texte",
                auto_fixable=True,
                fixed_value=str(has_m_in_text)
            ))

        return issues

    def check_ata_format(self, item_number: str) -> List[IntegrityIssue]:
        """Vérifie le format du numéro ATA"""
        issues = []

        if not item_number:
            issues.append(IntegrityIssue(
                issue_type=IssueType.INVALID_ATA,
                severity=IssueSeverity.ERROR,
                field="item_number",
                message="Numéro d'item vide",
                original_value="",
                suggested_action="Ré-extraire l'item",
                auto_fixable=False
            ))
            return issues

        if not self.ATA_PATTERN.match(item_number):
            # Tenter de corriger
            cleaned = re.sub(r'\s+', '-', item_number.strip())
            cleaned = re.sub(r'-+', '-', cleaned)

            if self.ATA_PATTERN.match(cleaned):
                issues.append(IntegrityIssue(
                    issue_type=IssueType.INVALID_ATA,
                    severity=IssueSeverity.WARNING,
                    field="item_number",
                    message=f"Format ATA non standard, corrigé",
                    original_value=item_number,
                    suggested_action="Appliquer la correction",
                    auto_fixable=True,
                    fixed_value=cleaned
                ))
            else:
                issues.append(IntegrityIssue(
                    issue_type=IssueType.INVALID_ATA,
                    severity=IssueSeverity.ERROR,
                    field="item_number",
                    message=f"Format ATA invalide: {item_number}",
                    original_value=item_number,
                    suggested_action="Vérifier manuellement",
                    auto_fixable=False
                ))

        return issues

    def _parse_quantity(self, value: str) -> Optional[int]:
        """Parse une quantité depuis une chaîne"""
        if not value or value in ['-', 'N/A', 'As installed', 'AR']:
            return None

        match = re.search(r'(\d+)', str(value))
        if match:
            return int(match.group(1))

        return None

    def validate_item(self, item: Dict[str, Any]) -> IntegrityReport:
        """
        Valide un item MEL complet.

        Args:
            item: Dictionnaire avec les champs de l'item

        Returns:
            IntegrityReport avec tous les problèmes détectés
        """
        item_number = item.get("item_number", "UNKNOWN")
        issues = []

        # 1. Vérifier le format ATA
        issues.extend(self.check_ata_format(item_number))

        # 2. Vérifier les remarks
        remarks = item.get("remarks", "") or item.get("remarks_raw", "")
        issues.extend(self.check_sentence_completeness(remarks, "remarks"))

        # 3. Vérifier les conditions
        conditions = item.get("conditions", [])
        issues.extend(self.check_conditions_sequence(conditions, remarks))

        # 4. Vérifier la cohérence catégorie
        issues.extend(self.check_category_consistency(
            item.get("category", ""),
            item.get("number_installed", ""),
            item.get("number_required", "")
        ))

        # 5. Vérifier les marqueurs de procédure
        issues.extend(self.check_procedure_markers(
            remarks,
            item.get("has_operational_procedure", False),
            item.get("has_maintenance_procedure", False)
        ))

        # Appliquer les auto-fixes si activé
        auto_fixed = 0
        if self.auto_fix:
            for issue in issues:
                if issue.auto_fixable and issue.fixed_value is not None:
                    auto_fixed += 1
                    logger.debug(f"Auto-fix: {issue.field} = {issue.fixed_value}")

        # Déterminer si ré-extraction nécessaire
        requires_reextraction = any(
            i.severity == IssueSeverity.ERROR and not i.auto_fixable
            for i in issues
        )

        reextraction_hints = [
            i.extraction_hint for i in issues
            if i.extraction_hint and not i.auto_fixable
        ]

        return IntegrityReport(
            item_number=item_number,
            is_valid=not any(i.severity == IssueSeverity.ERROR for i in issues),
            issues=issues,
            auto_fixed_count=auto_fixed,
            requires_reextraction=requires_reextraction,
            reextraction_hints=reextraction_hints
        )

    def validate_batch(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Valide un lot d'items.

        Returns:
            Résumé de validation avec statistiques
        """
        reports = []
        valid_count = 0
        error_count = 0
        warning_count = 0
        reextraction_needed = []

        for item in items:
            report = self.validate_item(item)
            reports.append(report)

            if report.is_valid:
                valid_count += 1
            else:
                error_count += 1

            warning_count += report.warning_count

            if report.requires_reextraction:
                reextraction_needed.append({
                    "item_number": report.item_number,
                    "hints": report.reextraction_hints
                })

        return {
            "total_items": len(items),
            "valid_items": valid_count,
            "items_with_errors": error_count,
            "total_warnings": warning_count,
            "items_needing_reextraction": len(reextraction_needed),
            "reextraction_details": reextraction_needed,
            "reports": reports
        }


class SelfHealingExtractor:
    """
    Extracteur avec capacité de self-healing.

    Utilise l'IntegrityChecker pour valider puis ré-extraire
    les items problématiques avec des paramètres ajustés.
    """

    def __init__(self, checker: IntegrityChecker, max_retries: int = 2):
        self.checker = checker
        self.max_retries = max_retries

    def extract_with_healing(self, source_content: str, page_number: int,
                            extractor_func: Callable) -> Tuple[List[Dict], List[IntegrityReport]]:
        """
        Extrait les items avec validation et ré-extraction si nécessaire.

        Args:
            source_content: Contenu source (Markdown, texte, etc.)
            page_number: Numéro de page source
            extractor_func: Fonction d'extraction à utiliser

        Returns:
            Tuple (items extraits valides, rapports d'intégrité)
        """
        # Première extraction
        items = extractor_func(source_content)

        all_reports = []
        valid_items = []

        for item in items:
            item['source_page'] = page_number

            # Valider
            report = self.checker.validate_item(item)
            all_reports.append(report)

            if report.is_valid:
                valid_items.append(item)
            elif report.requires_reextraction and self.max_retries > 0:
                # Tenter ré-extraction
                healed_item = self._attempt_reextraction(
                    item, report, source_content, extractor_func
                )
                if healed_item:
                    valid_items.append(healed_item)
                else:
                    # Garder l'original avec flag HITL
                    item['needs_hitl'] = True
                    item['hitl_reasons'] = [i.message for i in report.issues if i.severity == IssueSeverity.ERROR]
                    valid_items.append(item)
            else:
                # Garder l'original avec flag HITL
                item['needs_hitl'] = True
                item['hitl_reasons'] = [i.message for i in report.issues if i.severity == IssueSeverity.ERROR]
                valid_items.append(item)

        return valid_items, all_reports

    def _attempt_reextraction(self, original_item: Dict, report: IntegrityReport,
                             source_content: str, extractor_func: Callable) -> Optional[Dict]:
        """
        Tente de ré-extraire un item problématique.

        Stratégies:
        1. Étendre la fenêtre de texte
        2. Nettoyer le texte source
        3. Parser plus agressivement les conditions
        """
        logger.info(f"Tentative de ré-extraction pour {report.item_number}")

        for attempt in range(self.max_retries):
            # Stratégie basée sur les hints
            if "étendre la zone" in str(report.reextraction_hints):
                # Étendre la fenêtre autour de l'item
                extended_content = self._extend_context_window(
                    source_content, original_item, window_lines=5 + attempt * 2
                )
                new_items = extractor_func(extended_content)

                for new_item in new_items:
                    if self._items_match(new_item, original_item):
                        new_report = self.checker.validate_item(new_item)
                        if new_report.is_valid:
                            logger.info(f"Ré-extraction réussie (attempt {attempt + 1})")
                            return new_item

        return None

    def _extend_context_window(self, content: str, item: Dict,
                              window_lines: int = 5) -> str:
        """Étend la fenêtre de contexte autour d'un item"""
        lines = content.split('\n')
        item_number = item.get("item_number", "")

        # Trouver la ligne de l'item
        target_line = None
        for i, line in enumerate(lines):
            if item_number in line:
                target_line = i
                break

        if target_line is None:
            return content

        # Étendre la fenêtre
        start = max(0, target_line - 2)
        end = min(len(lines), target_line + window_lines)

        return '\n'.join(lines[start:end])

    def _items_match(self, item1: Dict, item2: Dict) -> bool:
        """Vérifie si deux items représentent le même élément"""
        return (
            item1.get("item_number") == item2.get("item_number") or
            item1.get("ata_chapter") == item2.get("ata_chapter") and
            item1.get("item_base") == item2.get("item_base")
        )


# === TESTS ===
if __name__ == "__main__":
    checker = IntegrityChecker()

    # Test item valide
    valid_item = {
        "item_number": "21-30-01A",
        "category": "C",
        "number_installed": "2",
        "number_required": "1",
        "remarks": "(O)(M) May be inoperative provided: (a) icing conditions not expected, (b) crew is briefed.",
        "conditions": [
            {"id": "a", "text": "icing conditions not expected"},
            {"id": "b", "text": "crew is briefed"}
        ],
        "has_operational_procedure": True,
        "has_maintenance_procedure": True
    }

    report = checker.validate_item(valid_item)
    print(f"Valid item: {report.is_valid}, Errors: {report.error_count}, Warnings: {report.warning_count}")

    # Test item tronqué
    truncated_item = {
        "item_number": "21-30-01B",
        "category": "C",
        "number_installed": "2",
        "number_required": "1",
        "remarks": "(O) May be inoperative provided: (a) remaining system operates normally, (b) flight conditions and",
        "conditions": [
            {"id": "a", "text": "remaining system operates normally"},
            {"id": "b", "text": "flight conditions and"}  # Tronqué!
        ],
        "has_operational_procedure": True,
        "has_maintenance_procedure": False
    }

    report = checker.validate_item(truncated_item)
    print(f"\nTruncated item: {report.is_valid}")
    for issue in report.issues:
        print(f"  - [{issue.severity.value}] {issue.field}: {issue.message}")

    # Test item avec séquence cassée
    broken_seq_item = {
        "item_number": "21-30-01C",
        "category": "C",
        "remarks": "(O) May be inoperative provided: (a) system A works, (c) system C works.",  # (b) manquant
        "conditions": [
            {"id": "a", "text": "system A works"},
            {"id": "c", "text": "system C works"}  # Séquence cassée!
        ]
    }

    report = checker.validate_item(broken_seq_item)
    print(f"\nBroken sequence: {report.is_valid}")
    for issue in report.issues:
        print(f"  - [{issue.severity.value}] {issue.field}: {issue.message}")
