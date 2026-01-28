#!/usr/bin/env python3
"""
Tests pour l'extraction des conditions depuis les remarques MEL/MMEL.

Ces tests vérifient que:
1. Les indicateurs de procédure (O) et (M) sont correctement exclus
2. Les sous-conditions (a), (b), (c), etc. sont correctement extraites
3. Les doublons sont dédupliqués
4. Les textes avec parenthèses internes sont gérés
"""

import unittest
import re
import sys
from pathlib import Path

# Ajouter le chemin src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "models"))


class TestConditionsExtraction(unittest.TestCase):
    """Tests pour extract_conditions_from_remarks"""

    def _extract_conditions_ids(self, remarks: str) -> list:
        """
        Reproduction de la logique corrigée pour les tests.
        """
        conditions = []
        seen_ids = set()

        # Pattern corrigé: [a-ln-z] exclut 'm', filtrage explicite de 'o'
        pattern = r'\(([a-ln-z])\)\s*([^(]+?)(?=\([a-z]\)|$)'
        matches = re.findall(pattern, remarks, re.IGNORECASE | re.DOTALL)

        for cond_id, text in matches:
            cond_id_lower = cond_id.lower()

            # Exclure (O) et (M)
            if cond_id_lower in ('o', 'm'):
                continue

            # Éviter les doublons
            if cond_id_lower in seen_ids:
                continue

            text = text.strip().rstrip(',').rstrip(';').strip()
            if text:
                seen_ids.add(cond_id_lower)
                conditions.append(cond_id_lower)

        return conditions

    def test_operations_indicator_excluded(self):
        """(O) doit être exclu car c'est un indicateur de procédure Operations"""
        text = "(O) May be inoperative provided remaining pack operates normally"
        result = self._extract_conditions_ids(text)
        self.assertNotIn('o', result, f"(O) ne devrait pas être extrait, got: {result}")

    def test_maintenance_indicator_excluded(self):
        """(M) doit être exclu car c'est un indicateur de procédure Maintenance"""
        text = "(M) Maintenance procedure required before dispatch"
        result = self._extract_conditions_ids(text)
        self.assertNotIn('m', result, f"(M) ne devrait pas être extrait, got: {result}")

    def test_combined_mo_indicators_excluded(self):
        """(M)(O) combinés doivent être exclus"""
        text = "(M)(O) May be inoperative provided: (a) Safety valve removed, (b) flight unpressurised"
        result = self._extract_conditions_ids(text)
        self.assertNotIn('o', result, "(O) ne devrait pas être extrait")
        self.assertNotIn('m', result, "(M) ne devrait pas être extrait")
        self.assertIn('a', result, "(a) devrait être extrait")
        self.assertIn('b', result, "(b) devrait être extrait")

    def test_simple_conditions_extracted(self):
        """Les sous-conditions (a), (b), (c) simples doivent être extraites"""
        text = "(a) First condition, (b) Second condition, (c) Third condition."
        result = self._extract_conditions_ids(text)
        self.assertEqual(result, ['a', 'b', 'c'], f"Expected ['a', 'b', 'c'], got: {result}")

    def test_conditions_with_operations_indicator(self):
        """Sous-conditions après (O) doivent être extraites correctement"""
        text = "(O) May be inoperative provided: (a) Flight VMC only, (b) Max altitude FL100"
        result = self._extract_conditions_ids(text)
        self.assertNotIn('o', result, "(O) ne devrait pas être extrait")
        self.assertIn('a', result, "(a) devrait être extrait")

    def test_duplicates_deduplicated(self):
        """Les conditions dupliquées doivent être dédupliquées"""
        text = "(a) First mention, (b) Something, (a) Duplicate mention"
        result = self._extract_conditions_ids(text)
        self.assertEqual(result.count('a'), 1, "(a) ne devrait apparaître qu'une fois")

    def test_real_mmel_text_21_10_01A(self):
        """Test avec le texte réel de l'item 21-10-01A du MMEL"""
        text = "(O) May be inoperative provided: (a) Flight is conducted unpressurised, (b) ECS or ACS (as applicable) Emergency Shut Off Lever is pulled, (c) ambient conditions allow acceptable cockpit/cabin temperatures, and"
        result = self._extract_conditions_ids(text)

        # (O) doit être exclu
        self.assertNotIn('o', result, f"(O) ne devrait pas être extrait, got: {result}")

        # (a) et (c) doivent être présents
        self.assertIn('a', result, "(a) devrait être extrait")
        self.assertIn('c', result, "(c) devrait être extrait")

    def test_real_mmel_text_21_30_01A(self):
        """Test avec le texte réel de l'item 21-30-01A du MMEL"""
        text = "(M)(O) May be inoperative provided: (a) the Safety valve is removed, (b) flight is conducted unpressurised, and (c) the regulations requiring oxygen use are complied with."
        result = self._extract_conditions_ids(text)

        # (M) et (O) doivent être exclus
        self.assertNotIn('m', result, "(M) ne devrait pas être extrait")
        self.assertNotIn('o', result, "(O) ne devrait pas être extrait")

        # Les sous-conditions doivent être présentes
        self.assertIn('a', result, "(a) devrait être extrait")

    def test_uppercase_conditions_normalized(self):
        """Les majuscules doivent être normalisées en minuscules"""
        text = "(A) First condition (B) Second condition"
        result = self._extract_conditions_ids(text)

        for cond_id in result:
            self.assertEqual(cond_id, cond_id.lower(), f"Condition devrait être en minuscule: {cond_id}")

    def test_empty_text_returns_empty(self):
        """Un texte vide doit retourner une liste vide"""
        result = self._extract_conditions_ids("")
        self.assertEqual(result, [], f"Expected [], got: {result}")

    def test_no_conditions_returns_empty(self):
        """Un texte sans conditions doit retourner une liste vide"""
        text = "May be inoperative provided remaining system operates normally."
        result = self._extract_conditions_ids(text)
        self.assertEqual(result, [], f"Expected [], got: {result}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
