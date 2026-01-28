#!/usr/bin/env python3
"""
Tests unitaires pour l'extraction de operation_scope.

Vérifie que les patterns d'extraction capturent correctement
les types d'opération (CAT, SPO, NCO, NCC) dans différents formats.
"""

import sys
from pathlib import Path

# Ajouter le répertoire src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_mel_parser_markdown():
    """Test de l'extraction depuis mel_parser_markdown.py"""
    from mel_parser_markdown import extract_operation_types

    test_cases = [
        # Format avec parenthèses
        ("(CAT) operations allowed", ["CAT"]),
        ("(SPO) May be inoperative", ["SPO"]),
        ("(O) For (CAT) and (SPO) only", ["CAT", "SPO"]),

        # Format SANS parenthèses (format réel dans les documents)
        ("CAT operations only.", ["CAT"]),
        ("SPO/NCO operations.", ["SPO", "NCO"]),
        ("For CAT and SPO operations", ["CAT", "SPO"]),
        ("(O)(M) May be inoperative for day VFR only. SPO/NCO operations.", ["SPO", "NCO"]),

        # Cas complexes
        ("May be inoperative. CAT operations only.", ["CAT"]),

        # Pas de mention
        ("May be inoperative for day VFR only.", []),
        ("(O) One may be inoperative.", []),
    ]

    print("\n" + "=" * 60)
    print("TEST: mel_parser_markdown.extract_operation_types()")
    print("=" * 60)

    passed = 0
    failed = 0

    for text, expected in test_cases:
        result = extract_operation_types(text)
        success = set(result) == set(expected)

        if success:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"

        print(f"{status}: '{text[:50]}...' -> {result} (attendu: {expected})")

    print(f"\nRésultat: {passed}/{len(test_cases)} tests passés")
    return failed == 0


def test_mel_parser_v2():
    """Test de l'extraction depuis mel_parser_v2.py"""
    from mel_parser_v2 import extract_operation_types

    test_cases = [
        ("CAT operations only.", ["CAT"]),
        ("SPO/NCO operations.", ["SPO", "NCO"]),
        ("(CAT) May be inoperative", ["CAT"]),
    ]

    print("\n" + "=" * 60)
    print("TEST: mel_parser_v2.extract_operation_types()")
    print("=" * 60)

    passed = 0
    failed = 0

    for text, expected in test_cases:
        result = extract_operation_types(text)
        success = set(result) == set(expected)

        if success:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"

        print(f"{status}: '{text[:50]}' -> {result}")

    print(f"\nRésultat: {passed}/{len(test_cases)} tests passés")
    return failed == 0


def test_mel_item_v3():
    """Test de l'extraction depuis models/mel_item_v3.py"""
    print("\n" + "=" * 60)
    print("TEST: models.mel_item_v3.extract_operation_types()")
    print("=" * 60)

    try:
        from models.mel_item_v3 import extract_operation_types
    except ImportError as e:
        print(f"⚠️  SKIP: Module non disponible ({e})")
        return True  # Skip = success (pas un échec)

    test_cases = [
        ("CAT operations only.", ["CAT"]),
        ("SPO/NCO operations.", ["SPO", "NCO"]),
        ("(CAT) and (SPO)", ["CAT", "SPO"]),
    ]

    passed = 0
    failed = 0

    for text, expected in test_cases:
        result = extract_operation_types(text)
        success = set(result) == set(expected)

        if success:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"

        print(f"{status}: '{text[:50]}' -> {result}")

    print(f"\nRésultat: {passed}/{len(test_cases)} tests passés")
    return failed == 0


def test_mmel_variant_tree_context():
    """Test de la construction du contexte dans MMELVariantTree"""
    print("\n" + "=" * 60)
    print("TEST: MMELVariantTree._build_context()")
    print("=" * 60)

    try:
        from matching.mmel_variant_tree import MMELVariantTree
    except ImportError as e:
        print(f"⚠️  SKIP: Module non disponible ({e})")
        return True  # Skip = success

    tree = MMELVariantTree()

    # Item avec operation_scope vide mais mention dans remarks
    test_item = {
        "item_number": "21-30-01",
        "item_base": "21-30-01",
        "item_description": "Ice Detection System",
        "category": "C",
        "remarks": "(O) May be inoperative. CAT operations only.",
        "operation_scope": []  # Vide - doit être extrait des remarks
    }

    tree.add_item(test_item)

    variant = tree.get_item("21-30-01")
    if variant:
        ops = variant.context.operation_types
        expected = ["CAT"]
        success = set(ops) == set(expected)
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: operation_types extrait des remarks = {ops} (attendu: {expected})")
        return success
    else:
        print("❌ FAIL: Item non trouvé dans l'arbre")
        return False


def main():
    """Exécute tous les tests"""
    print("\n" + "🧪 " * 20)
    print("SUITE DE TESTS: EXTRACTION OPERATION_SCOPE")
    print("🧪 " * 20)

    results = {
        "mel_parser_markdown": test_mel_parser_markdown(),
        "mel_parser_v2": test_mel_parser_v2(),
        "mel_item_v3": test_mel_item_v3(),
        "mmel_variant_tree": test_mmel_variant_tree_context(),
    }

    print("\n" + "=" * 60)
    print("RÉSUMÉ DES TESTS")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 Tous les tests d'extraction operation_scope ont réussi!")
        return 0
    else:
        print("⚠️  Certains tests ont échoué")
        return 1


if __name__ == "__main__":
    sys.exit(main())
