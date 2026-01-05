#!/usr/bin/env python3
"""
MoA_MEL - Script de test du pipeline complet
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mel_indexer import MELIndexer
from mel_comparator import MELComparator


def run_test():
    print("=" * 60)
    print("MoA_MEL - Test du Pipeline")
    print("=" * 60)
    
    # Charger les données
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "sample_mel.json") as f:
        mel_items = json.load(f)["items"]
    with open(data_dir / "sample_mmel.json") as f:
        mmel_items = json.load(f)["items"]
    
    print(f"\n📂 MEL: {len(mel_items)} items | MMEL: {len(mmel_items)} items")
    
    # Indexation
    indexer = MELIndexer()
    result = indexer.index_documents(mel_items, mmel_items)
    print(f"🔍 Matched: {result.matched_items}")
    
    # Comparaison
    comparator = MELComparator()
    matches = [m.to_dict() for m in result.matches]
    audit = comparator.run_audit(mel_items, mmel_items, matches)
    
    # Résultats
    s = audit.get_summary()["statistics"]
    print(f"\n📊 Conformes: {s['compliant']} | Plus restrictifs: {s['more_restrictive']}")
    print(f"⚠️ Moins restrictifs: {s['less_restrictive']} | HITL: {s['hitl_required']}")
    print(f"Taux conformité: {audit.get_summary()['compliance_rate']}%")
    
    # Sauvegarder
    output_dir = Path(__file__).parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    comparator.save_audit_result(audit, str(output_dir / "test_result.json"))
    comparator.generate_hitl_log(audit, str(output_dir / "test_hitl.json"))
    
    print(f"\n💾 Résultats: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    run_test()
