#!/usr/bin/env python3
"""
Test du Pipeline V2
===================
Script de validation du pipeline V2 avec les données sample.
"""

import json
import sys
from pathlib import Path

# Ajouter le répertoire src au path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2


def test_with_sample_data():
    """Test avec les données sample existantes"""
    print("=" * 60)
    print("TEST PIPELINE V2 - Données Sample")
    print("=" * 60)

    # Chemins des fichiers sample
    data_dir = Path(__file__).parent / "data"
    mel_path = data_dir / "sample_mel.json"
    mmel_path = data_dir / "sample_mmel.json"

    # Vérifier que les fichiers existent
    if not mel_path.exists():
        print(f"❌ Fichier MEL non trouvé: {mel_path}")
        return False
    if not mmel_path.exists():
        print(f"❌ Fichier MMEL non trouvé: {mmel_path}")
        return False

    print(f"\n📂 MEL: {mel_path}")
    print(f"📂 MMEL: {mmel_path}")

    # Configuration de test
    config = PipelineConfigV2(
        aircraft_msn=1280,           # MSN de test
        operation_type="CAT",         # Commercial Air Transport
        aircraft_type="A320-214",
        output_dir="outputs/test_v2",
        use_llm_parser=False,         # Pas de LLM pour le test
        enable_self_healing=True
    )

    print(f"\n🛫 Contexte avion:")
    print(f"   MSN: {config.aircraft_msn}")
    print(f"   Opération: {config.operation_type}")
    print(f"   Type: {config.aircraft_type}")

    # Créer et exécuter le pipeline
    pipeline = MoAMELPipelineV2(config)

    try:
        result = pipeline.run_full_pipeline(
            mel_source=str(mel_path),
            mmel_source=str(mmel_path),
            mel_is_json=True,
            mmel_is_json=True
        )

        # Afficher les résultats
        print("\n" + "=" * 60)
        print("✅ RÉSULTATS DU TEST")
        print("=" * 60)

        summary = result["summary"]
        print(f"\n📊 Statistiques:")
        print(f"   Items comparés: {summary['total_items_compared']}")
        print(f"   Conformes: {summary['compliant']}")
        print(f"   Plus restrictifs: {summary['more_restrictive']}")
        print(f"   Moins restrictifs (CRITIQUE): {summary['less_restrictive_critical']}")
        print(f"   Manquants: {summary['missing_items']}")
        print(f"   Taux de conformité: {summary['compliance_rate']}%")

        print(f"\n🚦 Par sévérité:")
        severity = result["severity_breakdown"]
        print(f"   Critique: {severity['critical']}")
        print(f"   Haut: {severity['high']}")
        print(f"   Moyen: {severity['medium']}")
        print(f"   Warning: {severity['warning']}")

        if result["critical_findings"]:
            print(f"\n⚠️  FINDINGS CRITIQUES:")
            for finding in result["critical_findings"]:
                print(f"   - {finding['mel_item']} → {finding['mmel_item']}")
                print(f"     Verdict: {finding['verdict']}")
                for reason in finding.get('reasons', []):
                    print(f"     Raison: {reason}")

        if result["recommendations"]:
            print(f"\n📋 Recommandations:")
            for rec in result["recommendations"]:
                print(f"   [{rec['priority']}] {rec['action']}")
                print(f"            SLA: {rec['sla']}")

        print(f"\n📁 Fichiers générés:")
        for name, path in result["output_files"].items():
            print(f"   {name}: {path}")

        return True

    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mmel_variant_tree():
    """Test de l'arbre de variantes MMEL"""
    print("\n" + "=" * 60)
    print("TEST MMEL VARIANT TREE")
    print("=" * 60)

    try:
        from matching.mmel_variant_tree import MMELVariantTree, AircraftContext

        tree = MMELVariantTree()

        # Données de test avec variantes
        test_items = [
            {
                "item_number": "21-30-01A",
                "item_base": "21-30-01",
                "item_description": "Ice Detection System",
                "category": "C",
                "applicable_msn": ["MSN 101-544"],
                "operation_scope": ["CAT"]
            },
            {
                "item_number": "21-30-01B",
                "item_base": "21-30-01",
                "item_description": "Ice Detection System",
                "category": "B",
                "applicable_msn": ["MSN 545 and up"],
                "operation_scope": ["CAT"]
            },
            {
                "item_number": "21-30-01C",
                "item_base": "21-30-01",
                "item_description": "Ice Detection System",
                "category": "C",
                "applicable_msn": ["MSN 545 and up"],
                "operation_scope": ["SPO", "NCO"]
            }
        ]

        tree.build_from_items(test_items)

        print(f"\n📊 Arbre construit: {tree.total_items} items")

        # Tests de matching
        test_cases = [
            {"msn": 300, "operation": "CAT", "expected": "21-30-01A"},
            {"msn": 1280, "operation": "CAT", "expected": "21-30-01B"},
            {"msn": 1280, "operation": "SPO", "expected": "21-30-01C"},
        ]

        print(f"\n🧪 Tests de matching:")
        all_passed = True

        for tc in test_cases:
            mel_item = {"item_number": "21-30-01", "item_base": "21-30-01"}
            result = tree.match_mel_item(mel_item, msn=tc["msn"], operation=tc["operation"])

            matched = result.matched_variant.item_number if result.matched_variant else "None"
            passed = matched == tc["expected"]

            status = "✅" if passed else "❌"
            print(f"   {status} MSN {tc['msn']}, {tc['operation']} → {matched} (attendu: {tc['expected']})")

            if not passed:
                all_passed = False

        return all_passed

    except ImportError as e:
        print(f"⚠️  Module non disponible: {e}")
        return False


def test_integrity_checker():
    """Test du vérificateur d'intégrité"""
    print("\n" + "=" * 60)
    print("TEST INTEGRITY CHECKER")
    print("=" * 60)

    try:
        from validation.integrity_checker import IntegrityChecker

        checker = IntegrityChecker()

        # Item valide
        valid_item = {
            "item_number": "21-30-01A",
            "category": "C",
            "remarks_raw": "(O) May be inoperative provided: (a) conditions met, (b) crew briefed.",
            "conditions": [
                {"id": "a", "text": "conditions met"},
                {"id": "b", "text": "crew briefed"}
            ],
            "has_operational_procedure": True
        }

        report = checker.validate_item(valid_item)
        print(f"\n✅ Item valide: {report.is_valid}")
        print(f"   Erreurs: {report.error_count}, Warnings: {report.warning_count}")

        # Item tronqué
        truncated_item = {
            "item_number": "21-30-01B",
            "category": "C",
            "remarks_raw": "(O) May be inoperative provided: (a) conditions and",
            "conditions": [
                {"id": "a", "text": "conditions and"}  # Tronqué!
            ]
        }

        report = checker.validate_item(truncated_item)
        print(f"\n❌ Item tronqué: {report.is_valid}")
        print(f"   Erreurs: {report.error_count}, Warnings: {report.warning_count}")
        for issue in report.issues[:3]:
            print(f"   - {issue.message}")

        return True

    except ImportError as e:
        print(f"⚠️  Module non disponible: {e}")
        return False


def main():
    """Exécute tous les tests"""
    print("\n" + "🔬 " * 20)
    print("SUITE DE TESTS PIPELINE V2")
    print("🔬 " * 20)

    results = {}

    # Test 1: Variant Tree
    results["variant_tree"] = test_mmel_variant_tree()

    # Test 2: Integrity Checker
    results["integrity_checker"] = test_integrity_checker()

    # Test 3: Pipeline complet
    results["pipeline"] = test_with_sample_data()

    # Résumé
    print("\n" + "=" * 60)
    print("RÉSUMÉ DES TESTS")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {test_name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 Tous les tests ont réussi!")
        return 0
    else:
        print("⚠️  Certains tests ont échoué")
        return 1


if __name__ == "__main__":
    sys.exit(main())
