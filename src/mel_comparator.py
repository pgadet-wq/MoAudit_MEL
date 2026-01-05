"""
MoA_MEL_Comparator - Comparaison MEL ↔ MMEL
============================================
Compare les items MEL avec les items MMEL pour détecter:
- Conformité (MEL = MMEL)
- Plus restrictif (MEL plus strict que MMEL) 
- Écart majeur (MEL moins restrictif que MMEL)
- Items manquants
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_Comparator")


class Severity(Enum):
    """Niveaux de sévérité des écarts"""
    INFO = "info"
    WARNING = "warning"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(Enum):
    """Verdicts possibles de la comparaison"""
    COMPLIANT = "COMPLIANT"
    MORE_RESTRICTIVE = "MORE_RESTRICTIVE"
    LESS_RESTRICTIVE = "LESS_RESTRICTIVE"  # Écart majeur!
    MISSING_IN_MEL = "MISSING_IN_MEL"
    MISSING_IN_MMEL = "MISSING_IN_MMEL"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    REMARKS_DEVIATION = "REMARKS_DEVIATION"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    INTERVAL_DEVIATION = "INTERVAL_DEVIATION"


@dataclass
class ComparisonDetail:
    """Détail d'une comparaison spécifique"""
    field: str
    mel_value: Any
    mmel_value: Any
    status: str  # "equal", "more_restrictive", "less_restrictive", "different"
    notes: str = ""


@dataclass
class ComparisonResult:
    """Résultat de la comparaison d'un item"""
    # Identifiants
    mel_item_id: str
    mmel_item_id: Optional[str]
    ata_chapter: str
    item_number: str
    item_description: str
    
    # Verdict principal
    verdict: str
    severity: str
    
    # Détails
    details: List[ComparisonDetail] = field(default_factory=list)
    
    # Valeurs comparées
    mel_category: str = ""
    mmel_category: str = ""
    mel_remarks: str = ""
    mmel_remarks: str = ""
    mel_quantity_required: str = ""
    mmel_quantity_required: str = ""
    mel_repair_interval: str = ""
    mmel_repair_interval: str = ""
    
    # Analyse LLM (optionnel)
    llm_analysis: str = ""
    
    # Flags
    requires_hitl_review: bool = False
    hitl_reason: str = ""
    sla_hours: int = 0
    
    # Timestamps
    compared_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["details"] = [asdict(d) for d in self.details]
        return result


@dataclass
class AuditResult:
    """Résultat global de l'audit MEL/MMEL"""
    mel_document: str
    mmel_document: str
    audit_timestamp: str
    
    # Statistiques globales
    total_comparisons: int = 0
    compliant_count: int = 0
    more_restrictive_count: int = 0
    less_restrictive_count: int = 0  # Écarts majeurs
    missing_in_mel_count: int = 0
    missing_in_mmel_count: int = 0
    other_deviations_count: int = 0
    
    # Statistiques par sévérité
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    
    # Items HITL
    hitl_required_count: int = 0
    
    # Détails
    comparisons: List[ComparisonResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["comparisons"] = [c.to_dict() for c in self.comparisons]
        return result
    
    def get_summary(self) -> Dict[str, Any]:
        """Retourne un résumé sans les détails"""
        return {
            "mel_document": self.mel_document,
            "mmel_document": self.mmel_document,
            "audit_timestamp": self.audit_timestamp,
            "statistics": {
                "total": self.total_comparisons,
                "compliant": self.compliant_count,
                "more_restrictive": self.more_restrictive_count,
                "less_restrictive": self.less_restrictive_count,
                "missing_in_mel": self.missing_in_mel_count,
                "missing_in_mmel": self.missing_in_mmel_count,
                "other_deviations": self.other_deviations_count,
                "hitl_required": self.hitl_required_count
            },
            "severity_breakdown": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "warning": self.warning_count,
                "info": self.info_count
            },
            "compliance_rate": round(
                (self.compliant_count + self.more_restrictive_count) / max(self.total_comparisons, 1) * 100, 2
            )
        }


class MELComparator:
    """Comparateur MEL ↔ MMEL avec détection d'écarts"""
    
    # Hiérarchie des catégories (1 = plus restrictif)
    CATEGORY_HIERARCHY = {
        "A": 1,
        "B": 2, 
        "C": 3,
        "D": 4,
        "-": 5,
        "": 5
    }
    
    # Mapping verdict -> sévérité
    VERDICT_SEVERITY = {
        Verdict.COMPLIANT: Severity.INFO,
        Verdict.MORE_RESTRICTIVE: Severity.INFO,
        Verdict.LESS_RESTRICTIVE: Severity.CRITICAL,
        Verdict.MISSING_IN_MEL: Severity.WARNING,
        Verdict.MISSING_IN_MMEL: Severity.INFO,
        Verdict.CATEGORY_MISMATCH: Severity.HIGH,
        Verdict.REMARKS_DEVIATION: Severity.MEDIUM,
        Verdict.QUANTITY_MISMATCH: Severity.MEDIUM,
        Verdict.INTERVAL_DEVIATION: Severity.MEDIUM
    }
    
    # SLA en heures par sévérité
    SLA_HOURS = {
        Severity.CRITICAL: 48,
        Severity.HIGH: 48,
        Severity.MEDIUM: 24,
        Severity.WARNING: 24,
        Severity.INFO: 0
    }
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.llm_enabled = bool(api_key)
    
    def parse_quantity(self, value: str) -> Optional[int]:
        """Parse une quantité depuis une chaîne"""
        if not value:
            return None
        # Chercher le premier nombre
        match = re.search(r'(\d+)', str(value))
        return int(match.group(1)) if match else None
    
    def parse_interval_days(self, interval: str) -> Optional[int]:
        """Parse un intervalle de réparation en jours"""
        if not interval:
            return None
        
        interval = str(interval).lower().strip()
        
        # Patterns courants
        patterns = [
            (r'(\d+)\s*day', lambda m: int(m.group(1))),
            (r'(\d+)\s*d\b', lambda m: int(m.group(1))),
            (r'(\d+)\s*hour', lambda m: int(m.group(1)) / 24),
            (r'(\d+)\s*h\b', lambda m: int(m.group(1)) / 24),
            (r'(\d+)\s*month', lambda m: int(m.group(1)) * 30),
            (r'(\d+)\s*flight', lambda m: int(m.group(1))),  # Approximation
            (r'a\s*check', lambda m: 400),  # A-check ~400 days
            (r'b\s*check', lambda m: 120),  # B-check ~120 days
            (r'c\s*check', lambda m: 600),  # C-check ~600 days
        ]
        
        for pattern, converter in patterns:
            match = re.search(pattern, interval)
            if match:
                return int(converter(match))
        
        return None
    
    def compare_categories(self, mel_cat: str, mmel_cat: str) -> Tuple[str, str]:
        """Compare deux catégories MEL"""
        mel_rank = self.CATEGORY_HIERARCHY.get(mel_cat.upper().strip(), 5)
        mmel_rank = self.CATEGORY_HIERARCHY.get(mmel_cat.upper().strip(), 5)
        
        if mel_rank == mmel_rank:
            return "equal", "Categories match"
        elif mel_rank < mmel_rank:
            return "more_restrictive", f"MEL ({mel_cat}) is more restrictive than MMEL ({mmel_cat})"
        else:
            return "less_restrictive", f"MEL ({mel_cat}) is LESS restrictive than MMEL ({mmel_cat}) - VIOLATION"
    
    def compare_quantities(self, mel_qty: str, mmel_qty: str) -> Tuple[str, str]:
        """Compare les quantités requises"""
        mel_val = self.parse_quantity(mel_qty)
        mmel_val = self.parse_quantity(mmel_qty)
        
        if mel_val is None or mmel_val is None:
            return "unknown", "Could not parse quantities"
        
        if mel_val == mmel_val:
            return "equal", f"Quantities match ({mel_val})"
        elif mel_val > mmel_val:
            return "more_restrictive", f"MEL requires more ({mel_val}) than MMEL ({mmel_val})"
        else:
            return "less_restrictive", f"MEL requires fewer ({mel_val}) than MMEL ({mmel_val})"
    
    def compare_intervals(self, mel_interval: str, mmel_interval: str) -> Tuple[str, str]:
        """Compare les intervalles de réparation"""
        mel_days = self.parse_interval_days(mel_interval)
        mmel_days = self.parse_interval_days(mmel_interval)
        
        if mel_days is None or mmel_days is None:
            if mel_interval and not mmel_interval:
                return "more_restrictive", "MEL has repair interval, MMEL doesn't specify"
            elif mmel_interval and not mel_interval:
                return "less_restrictive", "MMEL requires repair interval, MEL doesn't specify"
            return "unknown", "Could not parse intervals"
        
        if mel_days == mmel_days:
            return "equal", f"Intervals match ({mel_days} days)"
        elif mel_days < mmel_days:
            return "more_restrictive", f"MEL interval ({mel_days}d) shorter than MMEL ({mmel_days}d)"
        else:
            return "less_restrictive", f"MEL interval ({mel_days}d) longer than MMEL ({mmel_days}d)"
    
    def compare_remarks(self, mel_remarks: str, mmel_remarks: str) -> Tuple[str, str]:
        """Compare les remarques/conditions"""
        mel_r = str(mel_remarks).strip().lower()
        mmel_r = str(mmel_remarks).strip().lower()
        
        if not mel_r and not mmel_r:
            return "equal", "No remarks in either"
        
        if mel_r == mmel_r:
            return "equal", "Remarks identical"
        
        # Vérifier les annotations (O) et (M)
        mel_has_o = "(o)" in mel_r
        mel_has_m = "(m)" in mel_r
        mmel_has_o = "(o)" in mmel_r
        mmel_has_m = "(m)" in mmel_r
        
        if mel_has_m and not mmel_has_m:
            return "more_restrictive", "MEL adds maintenance requirement (M)"
        if mmel_has_m and not mel_has_m:
            return "less_restrictive", "MEL removes maintenance requirement (M) from MMEL"
        
        # Si les remarques sont différentes mais contiennent les mêmes mots-clés
        mel_words = set(mel_r.split())
        mmel_words = set(mmel_r.split())
        
        if mel_words.issuperset(mmel_words):
            return "more_restrictive", "MEL has additional conditions"
        elif mmel_words.issuperset(mel_words):
            return "less_restrictive", "MEL has fewer conditions than MMEL"
        else:
            return "different", "Remarks differ - requires review"
    
    def analyze_with_llm(self, mel_item: Dict, mmel_item: Dict) -> str:
        """Analyse approfondie via LLM pour cas complexes"""
        if not self.llm_enabled:
            return ""
        
        import requests
        
        prompt = f"""Analyze the following MEL vs MMEL comparison for aviation safety compliance.

MEL (Operator's Minimum Equipment List):
- Item: {mel_item.get('ata_chapter')} - {mel_item.get('item_number')}
- Description: {mel_item.get('item_description')}
- Category: {mel_item.get('category')}
- Repair Interval: {mel_item.get('repair_interval')}
- Quantity Required: {mel_item.get('number_required')}
- Remarks: {mel_item.get('remarks')}

MMEL (Master Minimum Equipment List - Reference):
- Item: {mmel_item.get('ata_chapter')} - {mmel_item.get('item_number')}
- Description: {mmel_item.get('item_description')}
- Category: {mmel_item.get('category')}
- Repair Interval: {mmel_item.get('repair_interval')}
- Quantity Required: {mmel_item.get('number_required')}
- Remarks: {mmel_item.get('remarks')}

Analyze:
1. Is the MEL compliant with the MMEL?
2. Is the MEL more or less restrictive?
3. Are there any safety concerns?
4. Any operational limitations missed or incorrectly applied?

Provide a brief, structured analysis in 2-3 sentences."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "mistral-large-latest",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 500
        }
        
        try:
            response = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM analysis error: {e}")
            return ""
    
    def compare_item(self, mel_item: Dict[str, Any], mmel_item: Optional[Dict[str, Any]], 
                    match_info: Optional[Dict[str, Any]] = None) -> ComparisonResult:
        """Compare un item MEL avec son équivalent MMEL"""
        
        mel_key = f"{mel_item.get('ata_chapter', '')}|{mel_item.get('item_number', '')}"
        mmel_key = f"{mmel_item.get('ata_chapter', '')}|{mmel_item.get('item_number', '')}" if mmel_item else None
        
        # Cas: pas de MMEL correspondant
        if not mmel_item:
            return ComparisonResult(
                mel_item_id=mel_key,
                mmel_item_id=None,
                ata_chapter=mel_item.get("ata_chapter", ""),
                item_number=mel_item.get("item_number", ""),
                item_description=mel_item.get("item_description", ""),
                verdict=Verdict.MISSING_IN_MMEL.value,
                severity=Severity.INFO.value,
                mel_category=mel_item.get("category", ""),
                mel_remarks=mel_item.get("remarks", ""),
                compared_at=datetime.now().isoformat(),
                details=[ComparisonDetail(
                    field="mmel_item",
                    mel_value="present",
                    mmel_value="missing",
                    status="different",
                    notes="Item exists in MEL but not in MMEL - operator-specific item"
                )]
            )
        
        details = []
        verdicts = []
        
        # 1. Comparer les catégories
        cat_status, cat_notes = self.compare_categories(
            mel_item.get("category", ""),
            mmel_item.get("category", "")
        )
        details.append(ComparisonDetail(
            field="category",
            mel_value=mel_item.get("category", ""),
            mmel_value=mmel_item.get("category", ""),
            status=cat_status,
            notes=cat_notes
        ))
        verdicts.append(cat_status)
        
        # 2. Comparer les quantités
        qty_status, qty_notes = self.compare_quantities(
            mel_item.get("number_required", ""),
            mmel_item.get("number_required", "")
        )
        details.append(ComparisonDetail(
            field="number_required",
            mel_value=mel_item.get("number_required", ""),
            mmel_value=mmel_item.get("number_required", ""),
            status=qty_status,
            notes=qty_notes
        ))
        if qty_status != "unknown":
            verdicts.append(qty_status)
        
        # 3. Comparer les intervalles
        int_status, int_notes = self.compare_intervals(
            mel_item.get("repair_interval", ""),
            mmel_item.get("repair_interval", "")
        )
        details.append(ComparisonDetail(
            field="repair_interval",
            mel_value=mel_item.get("repair_interval", ""),
            mmel_value=mmel_item.get("repair_interval", ""),
            status=int_status,
            notes=int_notes
        ))
        if int_status != "unknown":
            verdicts.append(int_status)
        
        # 4. Comparer les remarques
        rem_status, rem_notes = self.compare_remarks(
            mel_item.get("remarks", ""),
            mmel_item.get("remarks", "")
        )
        details.append(ComparisonDetail(
            field="remarks",
            mel_value=mel_item.get("remarks", ""),
            mmel_value=mmel_item.get("remarks", ""),
            status=rem_status,
            notes=rem_notes
        ))
        if rem_status not in ["unknown", "equal"]:
            verdicts.append(rem_status)
        
        # Déterminer le verdict final
        if "less_restrictive" in verdicts:
            final_verdict = Verdict.LESS_RESTRICTIVE
        elif all(v == "equal" for v in verdicts):
            final_verdict = Verdict.COMPLIANT
        elif "more_restrictive" in verdicts and "less_restrictive" not in verdicts:
            final_verdict = Verdict.MORE_RESTRICTIVE
        elif "different" in verdicts:
            final_verdict = Verdict.REMARKS_DEVIATION
        else:
            final_verdict = Verdict.COMPLIANT
        
        severity = self.VERDICT_SEVERITY.get(final_verdict, Severity.INFO)
        sla = self.SLA_HOURS.get(severity, 0)
        
        # Déterminer si HITL requis
        requires_hitl = severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM]
        hitl_reason = ""
        if requires_hitl:
            if final_verdict == Verdict.LESS_RESTRICTIVE:
                hitl_reason = "CRITICAL: MEL less restrictive than MMEL"
            elif "different" in verdicts:
                hitl_reason = "Remarks differ - manual review required"
            else:
                hitl_reason = f"Deviation detected: {final_verdict.value}"
        
        # Analyse LLM pour cas complexes
        llm_analysis = ""
        if requires_hitl and self.llm_enabled:
            llm_analysis = self.analyze_with_llm(mel_item, mmel_item)
        
        return ComparisonResult(
            mel_item_id=mel_key,
            mmel_item_id=mmel_key,
            ata_chapter=mel_item.get("ata_chapter", ""),
            item_number=mel_item.get("item_number", ""),
            item_description=mel_item.get("item_description", ""),
            verdict=final_verdict.value,
            severity=severity.value,
            details=details,
            mel_category=mel_item.get("category", ""),
            mmel_category=mmel_item.get("category", ""),
            mel_remarks=mel_item.get("remarks", ""),
            mmel_remarks=mmel_item.get("remarks", ""),
            mel_quantity_required=mel_item.get("number_required", ""),
            mmel_quantity_required=mmel_item.get("number_required", ""),
            mel_repair_interval=mel_item.get("repair_interval", ""),
            mmel_repair_interval=mmel_item.get("repair_interval", ""),
            llm_analysis=llm_analysis,
            requires_hitl_review=requires_hitl,
            hitl_reason=hitl_reason,
            sla_hours=sla,
            compared_at=datetime.now().isoformat()
        )
    
    def run_audit(self, mel_items: List[Dict], mmel_items: List[Dict],
                 matches: List[Dict]) -> AuditResult:
        """Exécute l'audit complet MEL vs MMEL"""
        
        # Créer un index MMEL
        mmel_index = {}
        for item in mmel_items:
            key = f"{item.get('ata_chapter', '')}|{item.get('item_number', '')}"
            mmel_index[key] = item
        
        # Créer un index des matches
        match_index = {}
        for match in matches:
            match_index[match.get("mel_item_id")] = match
        
        comparisons = []
        matched_mmel_keys = set()
        
        # Comparer chaque item MEL
        for mel_item in mel_items:
            mel_key = f"{mel_item.get('ata_chapter', '')}|{mel_item.get('item_number', '')}"
            match_info = match_index.get(mel_key)
            
            mmel_key = match_info.get("mmel_item_id") if match_info else mel_key
            mmel_item = mmel_index.get(mmel_key)
            
            comparison = self.compare_item(mel_item, mmel_item, match_info)
            comparisons.append(comparison)
            
            if mmel_key:
                matched_mmel_keys.add(mmel_key)
        
        # Identifier les items MMEL manquants dans MEL
        for mmel_key, mmel_item in mmel_index.items():
            if mmel_key not in matched_mmel_keys:
                comparisons.append(ComparisonResult(
                    mel_item_id="",
                    mmel_item_id=mmel_key,
                    ata_chapter=mmel_item.get("ata_chapter", ""),
                    item_number=mmel_item.get("item_number", ""),
                    item_description=mmel_item.get("item_description", ""),
                    verdict=Verdict.MISSING_IN_MEL.value,
                    severity=Severity.WARNING.value,
                    mmel_category=mmel_item.get("category", ""),
                    mmel_remarks=mmel_item.get("remarks", ""),
                    requires_hitl_review=True,
                    hitl_reason="MMEL item not found in MEL - verify if equipment installed",
                    sla_hours=48,
                    compared_at=datetime.now().isoformat()
                ))
        
        # Calculer les statistiques
        result = AuditResult(
            mel_document=mel_items[0].get("source_document", "MEL") if mel_items else "MEL",
            mmel_document=mmel_items[0].get("source_document", "MMEL") if mmel_items else "MMEL",
            audit_timestamp=datetime.now().isoformat(),
            comparisons=comparisons
        )
        
        # Compter par verdict
        for comp in comparisons:
            result.total_comparisons += 1
            
            if comp.verdict == Verdict.COMPLIANT.value:
                result.compliant_count += 1
            elif comp.verdict == Verdict.MORE_RESTRICTIVE.value:
                result.more_restrictive_count += 1
            elif comp.verdict == Verdict.LESS_RESTRICTIVE.value:
                result.less_restrictive_count += 1
            elif comp.verdict == Verdict.MISSING_IN_MEL.value:
                result.missing_in_mel_count += 1
            elif comp.verdict == Verdict.MISSING_IN_MMEL.value:
                result.missing_in_mmel_count += 1
            else:
                result.other_deviations_count += 1
            
            # Compter par sévérité
            if comp.severity == Severity.CRITICAL.value:
                result.critical_count += 1
            elif comp.severity == Severity.HIGH.value:
                result.high_count += 1
            elif comp.severity == Severity.MEDIUM.value:
                result.medium_count += 1
            elif comp.severity == Severity.WARNING.value:
                result.warning_count += 1
            else:
                result.info_count += 1
            
            if comp.requires_hitl_review:
                result.hitl_required_count += 1
        
        logger.info(f"Audit complete: {result.total_comparisons} items compared")
        logger.info(f"  Compliant: {result.compliant_count}")
        logger.info(f"  More restrictive: {result.more_restrictive_count}")
        logger.info(f"  Less restrictive (CRITICAL): {result.less_restrictive_count}")
        logger.info(f"  Missing in MEL: {result.missing_in_mel_count}")
        logger.info(f"  HITL required: {result.hitl_required_count}")
        
        return result
    
    def save_audit_result(self, result: AuditResult, output_path: str) -> str:
        """Sauvegarde le résultat de l'audit"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Audit result saved to: {output_path}")
        return str(output_path)
    
    def generate_hitl_log(self, result: AuditResult, log_path: str) -> str:
        """Génère le log HITL pour les écarts nécessitant review"""
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        hitl_items = [c for c in result.comparisons if c.requires_hitl_review]
        
        log_data = {
            "generated_at": datetime.now().isoformat(),
            "mel_document": result.mel_document,
            "mmel_document": result.mmel_document,
            "total_items_for_review": len(hitl_items),
            "by_severity": {
                "critical": sum(1 for c in hitl_items if c.severity == "critical"),
                "high": sum(1 for c in hitl_items if c.severity == "high"),
                "medium": sum(1 for c in hitl_items if c.severity == "medium"),
                "warning": sum(1 for c in hitl_items if c.severity == "warning")
            },
            "items": []
        }
        
        # Trier par sévérité
        severity_order = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "info": 4}
        hitl_items.sort(key=lambda x: severity_order.get(x.severity, 4))
        
        for comp in hitl_items:
            log_data["items"].append({
                "id": f"{comp.ata_chapter}-{comp.item_number}",
                "verdict": comp.verdict,
                "severity": comp.severity,
                "sla_hours": comp.sla_hours,
                "reason": comp.hitl_reason,
                "mel_data": {
                    "item_id": comp.mel_item_id,
                    "category": comp.mel_category,
                    "remarks": comp.mel_remarks,
                    "quantity_required": comp.mel_quantity_required,
                    "repair_interval": comp.mel_repair_interval
                },
                "mmel_data": {
                    "item_id": comp.mmel_item_id,
                    "category": comp.mmel_category,
                    "remarks": comp.mmel_remarks,
                    "quantity_required": comp.mmel_quantity_required,
                    "repair_interval": comp.mmel_repair_interval
                },
                "details": [d.notes for d in comp.details if d.status != "equal"],
                "llm_analysis": comp.llm_analysis,
                "validation": {
                    "status": "PENDING",
                    "decision": None,  # ACCEPT, REJECT, ESCALATE
                    "corrective_action": None,
                    "validated_by": None,
                    "validated_at": None,
                    "comments": None
                }
            })
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"HITL comparison log generated: {log_path}")
        return str(log_path)


if __name__ == "__main__":
    # Test avec données mock
    mel_items = [
        {
            "ata_chapter": "21",
            "item_number": "21-51-01",
            "item_description": "Air Conditioning Pack",
            "category": "C",
            "repair_interval": "10 days",
            "number_required": "1",
            "remarks": "(O) May be inoperative",
            "source_document": "test_mel.pdf"
        },
        {
            "ata_chapter": "24",
            "item_number": "24-10-01",
            "item_description": "Main Battery",
            "category": "B",  # Moins restrictif que MMEL (A)
            "repair_interval": "",
            "number_required": "1",
            "remarks": "",
            "source_document": "test_mel.pdf"
        }
    ]
    
    mmel_items = [
        {
            "ata_chapter": "21",
            "item_number": "21-51-01",
            "item_description": "Air Conditioning Pack Assembly",
            "category": "C",
            "repair_interval": "10 days",
            "number_required": "1",
            "remarks": "(O) May be inoperative provided remaining pack operates",
            "source_document": "test_mmel.pdf"
        },
        {
            "ata_chapter": "24",
            "item_number": "24-10-01",
            "item_description": "Main Battery",
            "category": "A",  # Catégorie de référence
            "repair_interval": "",
            "number_required": "1",
            "remarks": "",
            "source_document": "test_mmel.pdf"
        },
        {
            "ata_chapter": "32",
            "item_number": "32-40-01",
            "item_description": "Nose Wheel Steering",
            "category": "B",
            "repair_interval": "3 days",
            "number_required": "0",
            "remarks": "",
            "source_document": "test_mmel.pdf"
        }
    ]
    
    matches = [
        {"mel_item_id": "21|21-51-01", "mmel_item_id": "21|21-51-01"},
        {"mel_item_id": "24|24-10-01", "mmel_item_id": "24|24-10-01"}
    ]
    
    comparator = MELComparator()
    result = comparator.run_audit(mel_items, mmel_items, matches)
    
    print(f"\nAudit Summary:")
    print(json.dumps(result.get_summary(), indent=2))
