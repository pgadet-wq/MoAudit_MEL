#!/usr/bin/env python3
"""
MoA_MEL Comparator V2 - Comparaison intelligente avec gestion des variantes
"""

import json
import re
from datetime import datetime
from typing import Dict, List, Tuple
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComparatorV2")


class MELComparatorV2:
    """Comparateur intelligent MEL vs MMEL"""
    
    CAT_ORDER = {'A': 1, 'B': 2, 'C': 3, 'D': 4}
    
    def __init__(self, mel_data: dict, mmel_data: dict, operator_config: dict = None):
        self.mel_items = {item['item_number']: item for item in mel_data['items']}
        self.mmel_items = {item['item_number']: item for item in mmel_data['items']}
        
        # Grouper par item_base pour gérer les variantes
        self.mel_by_base = self._group_by_base(mel_data['items'])
        self.mmel_by_base = self._group_by_base(mmel_data['items'])
        
        # Config opérateur (MSN, type exploitation, etc.)
        self.operator_config = operator_config or {}
        
        self.comparisons = []
        self.hitl_items = []
    
    def _group_by_base(self, items: List[dict]) -> Dict[str, List[dict]]:
        """Groupe les items par item_base (sans suffixe)"""
        grouped = defaultdict(list)
        for item in items:
            base = item.get('item_base', item['item_number'].rstrip('ABCDEFGH'))
            grouped[base].append(item)
        return dict(grouped)
    
    def _compare_installed(self, mel_inst: str, mmel_inst: str) -> Tuple[str, bool, str]:
        """
        Compare Number Installed
        Retourne: (verdict, needs_hitl, reason)
        """
        mel_val = str(mel_inst).strip() if mel_inst else "-"
        mmel_val = str(mmel_inst).strip() if mmel_inst else "-"
        
        # MMEL = "-" signifie "dépend de l'opérateur" → MEL peut préciser
        if mmel_val == "-" and mel_val != "-":
            return "COMPLIANT", False, "MEL précise la valeur (OK)"
        
        # MEL = "-" mais MMEL a une valeur → vérifier
        if mel_val == "-" and mmel_val != "-":
            return "HITL", True, f"MEL non spécifié, MMEL={mmel_val} - vérifier config"
        
        # Valeurs identiques
        if mel_val == mmel_val:
            return "COMPLIANT", False, ""
        
        # Valeurs différentes - besoin HITL
        return "HITL", True, f"MEL={mel_val} vs MMEL={mmel_val} - vérifier"
    
    def _compare_categories(self, mel_cat: str, mmel_cat: str) -> Tuple[str, str]:
        """
        Compare les catégories
        Retourne: (verdict, severity)
        """
        mel_order = self.CAT_ORDER.get(mel_cat, 99)
        mmel_order = self.CAT_ORDER.get(mmel_cat, 99)
        
        if mel_order == mmel_order:
            return "COMPLIANT", "info"
        elif mel_order < mmel_order:
            return "MORE_RESTRICTIVE", "info"
        else:
            return "LESS_RESTRICTIVE", "critical"
    
    def _check_operation_types(self, mel_item: dict, mmel_item: dict) -> Tuple[bool, str]:
        """Vérifie les types d'exploitation"""
        mel_ops = mel_item.get('operation_types', [])
        mmel_ops = mmel_item.get('operation_types', [])
        
        if mmel_ops and not mel_ops:
            return True, f"MMEL spécifie exploitation {mmel_ops} - confirmer applicabilité"
        if mmel_ops and mel_ops and set(mel_ops) != set(mmel_ops):
            return True, f"Types exploitation différents: MEL={mel_ops}, MMEL={mmel_ops}"
        return False, ""
    
    def _check_msn(self, mel_item: dict, mmel_item: dict) -> Tuple[bool, str]:
        """Vérifie les MSN applicables"""
        mmel_msn = mmel_item.get('applicable_msn', 'ALL')
        
        if mmel_msn != "ALL":
            operator_msn = self.operator_config.get('msn', None)
            if operator_msn:
                # TODO: Parser la plage MSN et vérifier
                return True, f"Vérifier applicabilité {mmel_msn} pour MSN {operator_msn}"
            else:
                return True, f"MMEL limite à {mmel_msn} - confirmer MSN opérateur"
        return False, ""
    
    def _find_best_mmel_variant(self, mel_item: dict, mmel_variants: List[dict]) -> dict:
        """
        Trouve la meilleure variante MMEL correspondante.
        Logique: même suffixe > même catégorie > première variante
        """
        mel_suffix = mel_item.get('variant_suffix', '')
        mel_cat = mel_item.get('category', '')
        
        # 1. Chercher même suffixe
        for v in mmel_variants:
            if v.get('variant_suffix', '') == mel_suffix:
                return v
        
        # 2. Chercher même catégorie
        for v in mmel_variants:
            if v.get('category', '') == mel_cat:
                return v
        
        # 3. Retourner la plus restrictive (plus petit ordre)
        sorted_variants = sorted(mmel_variants, key=lambda x: self.CAT_ORDER.get(x.get('category', 'D'), 4))
        return sorted_variants[0] if sorted_variants else None
    
    def compare(self) -> dict:
        """Exécute la comparaison complète"""
        logger.info(f"Comparaison: {len(self.mel_items)} MEL vs {len(self.mmel_items)} MMEL")
        
        processed_mel = set()
        processed_mmel_bases = set()
        
        # 1. Comparer les items MEL avec MMEL
        for item_num, mel_item in self.mel_items.items():
            item_base = mel_item.get('item_base', item_num.rstrip('ABCDEFGH'))
            processed_mel.add(item_num)
            
            comparison = {
                'item_number': item_num,
                'item_base': item_base,
                'ata_chapter': mel_item.get('ata_chapter', ''),
                'item_description': mel_item.get('item_description', ''),
                'mel_category': mel_item.get('category', ''),
                'mel_installed': mel_item.get('number_installed', ''),
                'mel_required': mel_item.get('number_required', ''),
                'mel_remarks': mel_item.get('remarks', ''),
                'mmel_category': '',
                'mmel_installed': '',
                'mmel_required': '',
                'mmel_remarks': '',
                'verdict': '',
                'severity': 'info',
                'requires_hitl': False,
                'hitl_reasons': []
            }
            
            # Chercher dans MMEL
            mmel_variants = self.mmel_by_base.get(item_base, [])
            
            if not mmel_variants:
                # Pas de correspondance exacte - chercher par item_number
                if item_num in self.mmel_items:
                    mmel_variants = [self.mmel_items[item_num]]
            
            if mmel_variants:
                processed_mmel_bases.add(item_base)
                
                # Trouver la meilleure variante
                mmel_item = self._find_best_mmel_variant(mel_item, mmel_variants)
                
                if mmel_item:
                    comparison['mmel_category'] = mmel_item.get('category', '')
                    comparison['mmel_installed'] = mmel_item.get('number_installed', '')
                    comparison['mmel_required'] = mmel_item.get('number_required', '')
                    comparison['mmel_remarks'] = mmel_item.get('remarks', '')
                    comparison['mmel_item_number'] = mmel_item.get('item_number', '')
                    
                    # Signaler si plusieurs variantes MMEL
                    if len(mmel_variants) > 1:
                        variants_info = [f"{v['item_number']}(Cat {v['category']})" for v in mmel_variants]
                        comparison['hitl_reasons'].append(f"MMEL a {len(mmel_variants)} variantes: {', '.join(variants_info)}")
                        comparison['requires_hitl'] = True
                    
                    # Comparer catégories
                    cat_verdict, cat_severity = self._compare_categories(
                        mel_item.get('category', ''),
                        mmel_item.get('category', '')
                    )
                    
                    # Comparer Number Installed
                    inst_verdict, inst_hitl, inst_reason = self._compare_installed(
                        mel_item.get('number_installed', ''),
                        mmel_item.get('number_installed', '')
                    )
                    
                    if inst_hitl:
                        comparison['hitl_reasons'].append(inst_reason)
                        comparison['requires_hitl'] = True
                    
                    # Vérifier types d'exploitation
                    ops_hitl, ops_reason = self._check_operation_types(mel_item, mmel_item)
                    if ops_hitl:
                        comparison['hitl_reasons'].append(ops_reason)
                        comparison['requires_hitl'] = True
                    
                    # Vérifier MSN
                    msn_hitl, msn_reason = self._check_msn(mel_item, mmel_item)
                    if msn_hitl:
                        comparison['hitl_reasons'].append(msn_reason)
                        comparison['requires_hitl'] = True
                    
                    # Verdict final
                    if inst_verdict == "HITL" or comparison['requires_hitl']:
                        # Si HITL requis, le verdict catégorie est provisoire
                        comparison['verdict'] = cat_verdict
                        comparison['severity'] = "warning" if cat_verdict == "COMPLIANT" else cat_severity
                    else:
                        comparison['verdict'] = cat_verdict
                        comparison['severity'] = cat_severity
                else:
                    comparison['verdict'] = "NO_MATCH"
                    comparison['severity'] = "warning"
                    comparison['requires_hitl'] = True
                    comparison['hitl_reasons'].append("Pas de variante MMEL correspondante trouvée")
            else:
                comparison['verdict'] = "MISSING_IN_MMEL"
                comparison['severity'] = "info"
                comparison['hitl_reasons'].append("Item présent dans MEL mais absent de MMEL")
            
            self.comparisons.append(comparison)
        
        # 2. Items MMEL non présents dans MEL
        for item_base, mmel_variants in self.mmel_by_base.items():
            if item_base not in processed_mmel_bases:
                for mmel_item in mmel_variants:
                    if mmel_item['item_number'] not in [c.get('mmel_item_number') for c in self.comparisons]:
                        comparison = {
                            'item_number': mmel_item['item_number'],
                            'item_base': item_base,
                            'ata_chapter': mmel_item.get('ata_chapter', ''),
                            'item_description': mmel_item.get('item_description', ''),
                            'mel_category': '',
                            'mel_installed': '',
                            'mel_required': '',
                            'mel_remarks': '',
                            'mmel_category': mmel_item.get('category', ''),
                            'mmel_installed': mmel_item.get('number_installed', ''),
                            'mmel_required': mmel_item.get('number_required', ''),
                            'mmel_remarks': mmel_item.get('remarks', ''),
                            'verdict': "MISSING_IN_MEL",
                            'severity': "warning",
                            'requires_hitl': True,
                            'hitl_reasons': ["Item MMEL absent du MEL - vérifier si équipement installé"]
                        }
                        self.comparisons.append(comparison)
        
        return self._generate_report()
    
    def _generate_report(self) -> dict:
        """Génère le rapport final"""
        stats = {
            'compliant': sum(1 for c in self.comparisons if c['verdict'] == 'COMPLIANT'),
            'more_restrictive': sum(1 for c in self.comparisons if c['verdict'] == 'MORE_RESTRICTIVE'),
            'less_restrictive': sum(1 for c in self.comparisons if c['verdict'] == 'LESS_RESTRICTIVE'),
            'missing_in_mel': sum(1 for c in self.comparisons if c['verdict'] == 'MISSING_IN_MEL'),
            'missing_in_mmel': sum(1 for c in self.comparisons if c['verdict'] == 'MISSING_IN_MMEL'),
            'requires_hitl': sum(1 for c in self.comparisons if c['requires_hitl'])
        }
        
        total_matched = stats['compliant'] + stats['more_restrictive'] + stats['less_restrictive']
        compliance_rate = round((stats['compliant'] + stats['more_restrictive']) / max(total_matched, 1) * 100, 2)
        
        return {
            'audit_timestamp': datetime.now().isoformat(),
            'parser': 'docling_v2',
            'comparator': 'v2_intelligent',
            'statistics': stats,
            'total_comparisons': len(self.comparisons),
            'compliance_rate': compliance_rate,
            'critical_items': [c for c in self.comparisons if c['severity'] == 'critical'],
            'hitl_items': [c for c in self.comparisons if c['requires_hitl']],
            'comparisons': self.comparisons
        }


def run_comparison(mel_path: str, mmel_path: str, output_path: str, operator_config: dict = None):
    """Exécute la comparaison V2"""
    logger.info("Chargement des données...")
    
    with open(mel_path) as f:
        mel_data = json.load(f)
    with open(mmel_path) as f:
        mmel_data = json.load(f)
    
    logger.info(f"MEL: {len(mel_data['items'])} items | MMEL: {len(mmel_data['items'])} items")
    
    comparator = MELComparatorV2(mel_data, mmel_data, operator_config)
    report = comparator.compare()
    
    # Ajouter métadonnées
    report['mel_document'] = mel_data.get('document_name', '')
    report['mmel_document'] = mmel_data.get('document_name', '')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Rapport sauvegardé: {output_path}")
    
    return report


if __name__ == "__main__":
    import sys
    
    mel_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/parsed_mel_v2.json"
    mmel_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/parsed_mmel_v2.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "outputs/audit_result_v2.json"
    
    report = run_comparison(mel_path, mmel_path, output_path)
    
    print(f"\n{'='*60}")
    print("AUDIT V2 TERMINÉ")
    print(f"{'='*60}")
    print(f"Total comparaisons: {report['total_comparisons']}")
    print(f"✅ Conformes: {report['statistics']['compliant']}")
    print(f"↑  Plus restrictifs: {report['statistics']['more_restrictive']}")
    print(f"❌ Moins restrictifs: {report['statistics']['less_restrictive']} (CRITIQUE)")
    print(f"⚠  Absents MEL: {report['statistics']['missing_in_mel']}")
    print(f"○  Absents MMEL: {report['statistics']['missing_in_mmel']}")
    print(f"🔍 HITL requis: {report['statistics']['requires_hitl']}")
    print(f"\nTaux conformité: {report['compliance_rate']}%")
    
    if report['critical_items']:
        print(f"\n{'='*60}")
        print("🚨 ITEMS CRITIQUES")
        print(f"{'='*60}")
        for item in report['critical_items']:
            print(f"  {item['item_number']}: MEL={item['mel_category']} → MMEL={item['mmel_category']}")
            print(f"    {item['item_description'][:50]}")
            for reason in item['hitl_reasons']:
                print(f"    ⚠ {reason}")
