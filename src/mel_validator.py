#!/usr/bin/env python3
"""
MoA_MEL Validator - Validation sémantique et détection d'erreurs
"""

import json
import re
import os
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Validator")


@dataclass
class ValidationIssue:
    """Issue détectée lors de la validation"""
    item_number: str
    issue_type: str  # TRUNCATED_TEXT, SEMANTIC_MISMATCH, MISSING_CONDITION, etc.
    severity: str    # critical, high, medium, warning
    field: str       # remarks, description, category, etc.
    mel_value: str
    mmel_value: str
    description: str
    suggestion: str = ""
    
    def to_dict(self):
        return asdict(self)


class MELValidator:
    """Validateur sémantique MEL/MMEL"""
    
    # Patterns de fin de phrase normale
    SENTENCE_ENDINGS = ['.', ':', 'use.', 'with.', 'required.', 'conditions.', 'flight.']
    
    # Mots qui ne devraient pas terminer une phrase
    INCOMPLETE_ENDINGS = [
        'the', 'a', 'an', 'and', 'or', 'with', 'where', 'that', 'which',
        'is', 'are', 'be', 'to', 'for', 'in', 'on', 'at', 'by', 'of',
        'TCAS', 'VFR', 'IFR', 'MEL', 'MMEL'
    ]
    
    # Patterns de conditions standard MEL/MMEL
    STANDARD_PATTERNS = [
        r'\(O\)',           # Operation limitation
        r'\(M\)',           # Maintenance procedure
        r'\(M\)\s*\(O\)',   # Both
        r'May be inoperative provided',
        r'provided:',
        r'\([a-z]\)',       # Lettered conditions (a), (b), (c)
    ]
    
    def __init__(self, mel_data: dict, mmel_data: dict, api_key: str = None):
        self.mel_items = {item['item_number']: item for item in mel_data['items']}
        self.mmel_items = {item['item_number']: item for item in mmel_data['items']}
        self.api_key = api_key or os.environ.get('MISTRAL_API_KEY')
        self.issues: List[ValidationIssue] = []
    
    def _is_text_truncated(self, text: str) -> Tuple[bool, str]:
        """
        Détecte si un texte est tronqué (phrase incomplète).
        Retourne: (is_truncated, reason)
        """
        if not text or len(text.strip()) < 10:
            return False, ""
        
        text = text.strip()
        
        # Vérifier la fin
        last_word = text.split()[-1] if text.split() else ""
        last_word_clean = re.sub(r'[.,;:]$', '', last_word)
        
        # Se termine par un mot incomplet ?
        if last_word_clean.upper() in [w.upper() for w in self.INCOMPLETE_ENDINGS]:
            return True, f"Se termine par '{last_word}' - phrase probablement incomplète"
        
        # Ne se termine pas par une ponctuation normale ?
        if not any(text.endswith(e) for e in ['.', ':', ')', '0', '1', '2']):
            # Vérifier si c'est une liste avec des conditions
            if re.search(r'\([a-z]\)\s*\w+$', text):
                return True, "Dernière condition semble incomplète"
        
        return False, ""
    
    def _compare_remarks_structure(self, mel_remarks: str, mmel_remarks: str) -> List[str]:
        """
        Compare la structure des remarks MEL vs MMEL.
        Retourne une liste de différences détectées.
        """
        differences = []
        
        if not mel_remarks or not mmel_remarks:
            return differences
        
        # Extraire les conditions (a), (b), (c), etc.
        mel_conditions = re.findall(r'\([a-z]\)[^(]+', mel_remarks, re.IGNORECASE)
        mmel_conditions = re.findall(r'\([a-z]\)[^(]+', mmel_remarks, re.IGNORECASE)
        
        # Comparer le nombre de conditions
        if len(mel_conditions) != len(mmel_conditions):
            differences.append(f"Nombre de conditions différent: MEL={len(mel_conditions)}, MMEL={len(mmel_conditions)}")
        
        # Comparer chaque condition
        for i, (mel_cond, mmel_cond) in enumerate(zip(mel_conditions, mmel_conditions)):
            mel_clean = re.sub(r'\s+', ' ', mel_cond.strip().lower())
            mmel_clean = re.sub(r'\s+', ' ', mmel_cond.strip().lower())
            
            # Vérifier si MEL est un sous-ensemble tronqué de MMEL
            if mel_clean != mmel_clean:
                if mmel_clean.startswith(mel_clean.rstrip('.')):
                    differences.append(f"Condition ({chr(97+i)}) tronquée dans MEL")
                elif mel_clean not in mmel_clean and mmel_clean not in mel_clean:
                    differences.append(f"Condition ({chr(97+i)}) différente")
        
        return differences
    
    def _check_operation_markers(self, mel_remarks: str, mmel_remarks: str) -> List[str]:
        """
        Vérifie la cohérence des marqueurs (O) et (M).
        """
        issues = []
        
        mel_has_o = '(O)' in mel_remarks
        mel_has_m = '(M)' in mel_remarks
        mmel_has_o = '(O)' in mmel_remarks
        mmel_has_m = '(M)' in mmel_remarks
        
        if mmel_has_o and not mel_has_o:
            issues.append("MMEL requiert (O) mais absent dans MEL")
        if mmel_has_m and not mel_has_m:
            issues.append("MMEL requiert (M) mais absent dans MEL")
        
        return issues
    
    def validate_item(self, mel_item: dict, mmel_item: dict) -> List[ValidationIssue]:
        """Valide un item MEL contre son équivalent MMEL"""
        issues = []
        item_num = mel_item.get('item_number', '')
        
        mel_remarks = mel_item.get('remarks', '') or ''
        mmel_remarks = mmel_item.get('remarks', '') or ''
        
        # 1. Vérifier texte tronqué dans MEL
        is_truncated, truncate_reason = self._is_text_truncated(mel_remarks)
        if is_truncated:
            issues.append(ValidationIssue(
                item_number=item_num,
                issue_type="TRUNCATED_TEXT",
                severity="critical",
                field="remarks",
                mel_value=mel_remarks[-50:] if len(mel_remarks) > 50 else mel_remarks,
                mmel_value=mmel_remarks[-50:] if len(mmel_remarks) > 50 else mmel_remarks,
                description=f"Texte MEL probablement tronqué: {truncate_reason}",
                suggestion="Vérifier le document source et compléter le texte"
            ))
        
        # 2. Comparer structure des remarks
        struct_diffs = self._compare_remarks_structure(mel_remarks, mmel_remarks)
        for diff in struct_diffs:
            severity = "critical" if "tronquée" in diff.lower() else "high"
            issues.append(ValidationIssue(
                item_number=item_num,
                issue_type="STRUCTURE_MISMATCH",
                severity=severity,
                field="remarks",
                mel_value=mel_remarks[:100],
                mmel_value=mmel_remarks[:100],
                description=diff,
                suggestion="Comparer manuellement les conditions MEL vs MMEL"
            ))
        
        # 3. Vérifier marqueurs (O) et (M)
        marker_issues = self._check_operation_markers(mel_remarks, mmel_remarks)
        for issue in marker_issues:
            issues.append(ValidationIssue(
                item_number=item_num,
                issue_type="MISSING_MARKER",
                severity="high",
                field="remarks",
                mel_value=mel_remarks[:50],
                mmel_value=mmel_remarks[:50],
                description=issue,
                suggestion="Ajouter le marqueur manquant dans la MEL"
            ))
        
        # 4. Vérifier cohérence Number Installed/Required
        mel_inst = str(mel_item.get('number_installed', '-'))
        mmel_inst = str(mmel_item.get('number_installed', '-'))
        mel_req = str(mel_item.get('number_required', '-'))
        mmel_req = str(mmel_item.get('number_required', '-'))
        
        # MEL required > MMEL required = problème
        try:
            if mel_req != '-' and mmel_req != '-':
                if int(mel_req) > int(mmel_req):
                    issues.append(ValidationIssue(
                        item_number=item_num,
                        issue_type="REQUIRED_MISMATCH",
                        severity="warning",
                        field="number_required",
                        mel_value=mel_req,
                        mmel_value=mmel_req,
                        description=f"MEL requiert plus que MMEL: {mel_req} > {mmel_req}",
                        suggestion="Vérifier si c'est intentionnel (plus restrictif)"
                    ))
        except ValueError:
            pass
        
        return issues
    
    def validate_all(self) -> Dict:
        """Valide tous les items MEL contre MMEL"""
        logger.info(f"Validation de {len(self.mel_items)} items MEL...")
        
        all_issues = []
        
        for item_num, mel_item in self.mel_items.items():
            # Chercher l'item MMEL correspondant
            mmel_item = self.mmel_items.get(item_num)
            
            if not mmel_item:
                # Chercher par item_base
                item_base = mel_item.get('item_base', item_num.rstrip('ABCDEFGH'))
                for mmel_num, mmel in self.mmel_items.items():
                    if mmel.get('item_base', '') == item_base:
                        mmel_item = mmel
                        break
            
            if mmel_item:
                issues = self.validate_item(mel_item, mmel_item)
                all_issues.extend(issues)
        
        # Stats
        stats = {
            'total_items_validated': len(self.mel_items),
            'total_issues': len(all_issues),
            'critical': sum(1 for i in all_issues if i.severity == 'critical'),
            'high': sum(1 for i in all_issues if i.severity == 'high'),
            'medium': sum(1 for i in all_issues if i.severity == 'medium'),
            'warning': sum(1 for i in all_issues if i.severity == 'warning'),
            'by_type': {}
        }
        
        for issue in all_issues:
            stats['by_type'][issue.issue_type] = stats['by_type'].get(issue.issue_type, 0) + 1
        
        logger.info(f"Validation terminée: {len(all_issues)} issues détectées")
        
        return {
            'validation_stats': stats,
            'issues': [i.to_dict() for i in all_issues]
        }
    
    def validate_with_llm(self, item_num: str) -> Dict:
        """
        Utilise Mistral pour une analyse sémantique approfondie d'un item.
        """
        if not self.api_key:
            return {'error': 'API key not configured'}
        
        mel_item = self.mel_items.get(item_num)
        mmel_item = self.mmel_items.get(item_num)
        
        if not mel_item or not mmel_item:
            return {'error': f'Item {item_num} not found'}
        
        import requests
        
        prompt = f"""Analyse la conformité de cet item MEL par rapport à la MMEL de référence.

ITEM: {item_num}

MEL (Opérateur):
- Catégorie: {mel_item.get('category')}
- Installé: {mel_item.get('number_installed')}
- Requis: {mel_item.get('number_required')}
- Remarks: {mel_item.get('remarks', '')[:500]}

MMEL (Référence):
- Catégorie: {mmel_item.get('category')}
- Installé: {mmel_item.get('number_installed')}
- Requis: {mmel_item.get('number_required')}
- Remarks: {mmel_item.get('remarks', '')[:500]}

Analyse:
1. Le texte MEL est-il complet ou tronqué ?
2. Les conditions MEL couvrent-elles toutes les conditions MMEL ?
3. Y a-t-il des différences sémantiques importantes ?
4. La MEL est-elle conforme, plus restrictive, ou moins restrictive ?

Réponds en JSON avec: {{
  "text_complete": true/false,
  "truncation_details": "...",
  "conditions_match": true/false,
  "missing_conditions": [...],
  "semantic_differences": [...],
  "verdict": "COMPLIANT/MORE_RESTRICTIVE/LESS_RESTRICTIVE/NEEDS_REVIEW",
  "recommendations": [...]
}}"""

        try:
            response = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "mistral-small-latest",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                },
                timeout=30
            )
            
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                # Extraire le JSON de la réponse
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    return json.loads(json_match.group())
                return {'raw_response': content}
            else:
                return {'error': f'API error: {response.status_code}'}
        except Exception as e:
            return {'error': str(e)}


def run_validation(mel_path: str, mmel_path: str, output_path: str):
    """Exécute la validation complète"""
    with open(mel_path) as f:
        mel_data = json.load(f)
    with open(mmel_path) as f:
        mmel_data = json.load(f)
    
    validator = MELValidator(mel_data, mmel_data)
    results = validator.validate_all()
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print("VALIDATION TERMINÉE")
    print(f"{'='*60}")
    print(f"Items validés: {results['validation_stats']['total_items_validated']}")
    print(f"Issues détectées: {results['validation_stats']['total_issues']}")
    print(f"  🔴 Critiques: {results['validation_stats']['critical']}")
    print(f"  🟠 Élevées: {results['validation_stats']['high']}")
    print(f"  🟡 Moyennes: {results['validation_stats']['medium']}")
    print(f"  ⚠️  Warnings: {results['validation_stats']['warning']}")
    print(f"\nPar type:")
    for issue_type, count in results['validation_stats']['by_type'].items():
        print(f"  {issue_type}: {count}")
    
    if results['validation_stats']['critical'] > 0:
        print(f"\n{'='*60}")
        print("🚨 ISSUES CRITIQUES")
        print(f"{'='*60}")
        for issue in results['issues']:
            if issue['severity'] == 'critical':
                print(f"\n{issue['item_number']} - {issue['issue_type']}")
                print(f"  {issue['description']}")
                print(f"  MEL: ...{issue['mel_value']}")
                print(f"  MMEL: ...{issue['mmel_value']}")
                print(f"  → {issue['suggestion']}")
    
    return results


if __name__ == "__main__":
    import sys
    
    mel_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/parsed_mel_v2.json"
    mmel_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/parsed_mmel_v2.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "outputs/validation_report.json"
    
    run_validation(mel_path, mmel_path, output_path)
