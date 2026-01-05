#!/usr/bin/env python3
"""
MoA_MEL - Semantic Parser (LLM-Driven)
======================================
Parser utilisant un LLM (Mistral Large) pour l'extraction structurée.

Remplace les regex rigides par une extraction sémantique avec validation Pydantic.
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import requests
from datetime import datetime

# Import des modèles V3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from models.mel_item_v3 import (
        MELItemV3, MSNRange, ApplicabilityCondition,
        RectificationInterval, parse_item_number,
        extract_conditions_from_remarks, extract_operation_types,
        extract_msn_ranges
    )
except ImportError:
    # Fallback pour tests
    MELItemV3 = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SemanticParser")


@dataclass
class ExtractionResult:
    """Résultat d'extraction d'un bloc"""

    success: bool
    items: List[Dict[str, Any]]
    raw_response: str = ""
    error: Optional[str] = None
    tokens_used: int = 0
    extraction_time_ms: int = 0


class SemanticMELParser:
    """
    Parser sémantique utilisant LLM pour extraction structurée.

    Avantages vs regex:
    - Comprend le contexte sémantique
    - Gère les variations de format
    - Extrait les relations implicites (MSN, operation types)
    - Reconstruit les informations fragmentées
    """

    # Prompt d'extraction structurée
    EXTRACTION_PROMPT = '''Tu es un expert en analyse de documents aéronautiques MEL/MMEL.
Analyse le bloc de texte suivant et extrais les informations en JSON strict.

# BLOC À ANALYSER:
```
{block_content}
```

# SCHÉMA JSON ATTENDU:
```json
{{
  "items": [
    {{
      "ata_chapter": "XX",
      "ata_section": "YY",
      "item_base": "XX-YY-ZZ",
      "variant_suffix": "A",
      "item_description": "Description de l'équipement",
      "category": "A|B|C|D",
      "number_installed": "2",
      "number_required": "1",
      "rectification_interval": "10 days",
      "remarks_raw": "Texte brut des remarques",
      "conditions": [
        {{"id": "a", "text": "condition a complète"}},
        {{"id": "b", "text": "condition b complète"}}
      ],
      "has_operational_procedure": true,
      "has_maintenance_procedure": false,
      "applicable_msn": ["MSN 545 and up"],
      "operation_scope": ["CAT", "SPO"],
      "etops_restriction": null,
      "altitude_restriction": "FL310"
    }}
  ]
}}
```

# INSTRUCTIONS CRITIQUES:
1. **Séparation ID/Suffixe**: Sépare toujours l'item_base (21-30-01) du variant_suffix (D)
2. **MSN**: Cherche les mentions "MSN XXX", "(MSN XXX and up)", "(MSN XXX-YYY)" dans le texte
3. **Operations**: Identifie (CAT), (SPO), (NCO), (NCC) près de l'item ou dans les remarques
4. **Conditions**: Décompose CHAQUE condition (a), (b), (c) séparément avec son texte COMPLET
5. **Procédures**: (O) = has_operational_procedure=true, (M) = has_maintenance_procedure=true
6. **ETOPS**: Si "ETOPS" mentionné, extrait la restriction
7. **Altitude**: Si "FL" ou altitude mentionnée, extrait la restriction

# RÈGLES DE VALIDATION:
- ata_chapter et ata_section doivent être des chaînes de 2 chiffres
- category doit être A, B, C ou D uniquement
- Si une condition semble tronquée, indique-le en ajoutant "[INCOMPLETE]" à la fin du texte
- Si plusieurs items sont dans le bloc, retourne-les tous dans le tableau "items"

RETOURNE UNIQUEMENT LE JSON, sans aucun texte avant ou après.'''

    # Prompt de correction/complétion
    REPAIR_PROMPT = '''Le JSON extrait contient des erreurs de validation.

JSON ORIGINAL:
```json
{original_json}
```

ERREURS DÉTECTÉES:
{errors}

BLOC SOURCE:
```
{source_block}
```

Corrige le JSON pour résoudre les erreurs. Retourne UNIQUEMENT le JSON corrigé.'''

    def __init__(self, api_key: str, model: str = "mistral-large-latest",
                 base_url: str = "https://api.mistral.ai/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

        # Cache pour éviter les appels répétés
        self._cache: Dict[str, ExtractionResult] = {}

    def _call_llm(self, prompt: str, temperature: float = 0.1,
                 max_tokens: int = 4096) -> tuple[str, int]:
        """Appelle le LLM et retourne la réponse"""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }

        try:
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=120
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            tokens = result.get("usage", {}).get("total_tokens", 0)

            return content, tokens

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API LLM: {e}")
            raise

    def _clean_json_response(self, response: str) -> str:
        """Nettoie la réponse JSON du LLM"""
        # Retirer les backticks markdown si présents
        response = re.sub(r'^```json\s*', '', response.strip())
        response = re.sub(r'\s*```$', '', response)
        response = re.sub(r'^```\s*', '', response)

        return response.strip()

    def _validate_and_convert(self, raw_items: List[Dict]) -> List[Dict[str, Any]]:
        """Valide et convertit les items extraits"""
        valid_items = []

        for raw_item in raw_items:
            try:
                # Normalisation basique
                item = {
                    "ata_chapter": str(raw_item.get("ata_chapter", "")).zfill(2),
                    "ata_section": str(raw_item.get("ata_section", "")).zfill(2),
                    "item_base": raw_item.get("item_base", ""),
                    "variant_suffix": raw_item.get("variant_suffix", "") or None,
                    "item_description": raw_item.get("item_description", ""),
                    "category": str(raw_item.get("category", "C")).upper(),
                    "number_installed": str(raw_item.get("number_installed", "-")),
                    "number_required": str(raw_item.get("number_required", "-")),
                    "rectification_interval": raw_item.get("rectification_interval", ""),
                    "remarks_raw": raw_item.get("remarks_raw", ""),
                    "conditions": raw_item.get("conditions", []),
                    "has_operational_procedure": bool(raw_item.get("has_operational_procedure", False)),
                    "has_maintenance_procedure": bool(raw_item.get("has_maintenance_procedure", False)),
                    "applicable_msn": raw_item.get("applicable_msn", []),
                    "operation_scope": raw_item.get("operation_scope", []),
                    "etops_restriction": raw_item.get("etops_restriction"),
                    "altitude_restriction": raw_item.get("altitude_restriction"),
                }

                # Construire item_number si manquant
                if not item["item_base"] and item["ata_chapter"] and item["ata_section"]:
                    # Tenter de reconstruire
                    pass

                # Validation catégorie
                if item["category"] not in ["A", "B", "C", "D"]:
                    item["category"] = "C"  # Défaut

                # Convertir conditions en format standard
                if isinstance(item["conditions"], list):
                    item["conditions"] = [
                        {"id": c.get("id", str(i)), "text": c.get("text", "")}
                        for i, c in enumerate(item["conditions"])
                        if isinstance(c, dict)
                    ]

                # Convertir MSN ranges
                if isinstance(item["applicable_msn"], list):
                    item["applicable_msn"] = [
                        msn if isinstance(msn, str) else str(msn)
                        for msn in item["applicable_msn"]
                    ]

                valid_items.append(item)

            except Exception as e:
                logger.warning(f"Erreur validation item: {e}")
                continue

        return valid_items

    def parse_block(self, block_content: str, source_page: int = 0,
                   source_table: int = 0) -> ExtractionResult:
        """
        Parse un bloc de texte avec le LLM.

        Args:
            block_content: Contenu Markdown/texte du bloc
            source_page: Numéro de page source
            source_table: Index du tableau source

        Returns:
            ExtractionResult avec les items extraits
        """
        # Vérifier le cache
        cache_key = hash(block_content)
        if cache_key in self._cache:
            return self._cache[cache_key]

        start_time = datetime.now()

        try:
            # Préparer le prompt
            prompt = self.EXTRACTION_PROMPT.format(block_content=block_content)

            # Appeler le LLM
            raw_response, tokens = self._call_llm(prompt)

            # Nettoyer et parser le JSON
            cleaned_response = self._clean_json_response(raw_response)

            try:
                parsed = json.loads(cleaned_response)
            except json.JSONDecodeError as e:
                logger.warning(f"Erreur parsing JSON: {e}")
                # Tenter réparation
                parsed = self._attempt_json_repair(cleaned_response, block_content)

            # Extraire les items
            raw_items = parsed.get("items", [])
            if not raw_items and isinstance(parsed, dict):
                # Le LLM a peut-être retourné un seul item
                if "ata_chapter" in parsed or "item_base" in parsed:
                    raw_items = [parsed]

            # Valider et convertir
            items = self._validate_and_convert(raw_items)

            # Ajouter les métadonnées source
            for item in items:
                item["source_page"] = source_page
                item["source_table"] = source_table
                item["extraction_method"] = "llm_semantic"

            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            result = ExtractionResult(
                success=True,
                items=items,
                raw_response=raw_response,
                tokens_used=tokens,
                extraction_time_ms=elapsed_ms
            )

            # Mettre en cache
            self._cache[cache_key] = result

            return result

        except Exception as e:
            logger.error(f"Erreur extraction: {e}")
            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return ExtractionResult(
                success=False,
                items=[],
                error=str(e),
                extraction_time_ms=elapsed_ms
            )

    def _attempt_json_repair(self, broken_json: str, source_block: str) -> Dict:
        """Tente de réparer un JSON cassé via LLM"""
        logger.info("Tentative de réparation JSON")

        repair_prompt = f'''Le JSON suivant contient des erreurs de syntaxe. Corrige-le.

JSON CASSÉ:
```
{broken_json}
```

Retourne UNIQUEMENT le JSON corrigé, sans explication.'''

        try:
            repaired, _ = self._call_llm(repair_prompt, temperature=0.0)
            cleaned = self._clean_json_response(repaired)
            return json.loads(cleaned)
        except Exception:
            # Retourner structure vide
            return {"items": []}

    def parse_markdown_document(self, markdown_content: str) -> List[Dict[str, Any]]:
        """
        Parse un document Markdown complet.

        Divise le document en blocs logiques et les parse individuellement.
        """
        all_items = []

        # Diviser par tableaux ou sections
        blocks = self._split_into_blocks(markdown_content)

        logger.info(f"Parsing {len(blocks)} blocs...")

        for i, block in enumerate(blocks):
            if not block.strip():
                continue

            result = self.parse_block(block, source_page=0, source_table=i)

            if result.success:
                all_items.extend(result.items)
                logger.debug(f"Bloc {i}: {len(result.items)} items extraits")
            else:
                logger.warning(f"Bloc {i}: échec - {result.error}")

        # Dédoublonner par item_number
        unique_items = {}
        for item in all_items:
            key = item.get("item_base", "") + (item.get("variant_suffix") or "")
            if key and key not in unique_items:
                unique_items[key] = item
            elif key:
                # Fusionner les informations
                existing = unique_items[key]
                # Garder le plus complet
                if len(item.get("remarks_raw", "")) > len(existing.get("remarks_raw", "")):
                    unique_items[key] = item

        return list(unique_items.values())

    def _split_into_blocks(self, markdown: str) -> List[str]:
        """Divise le Markdown en blocs parsables"""
        blocks = []

        # Séparer par tableaux
        # Un tableau Markdown commence par | et contient une ligne de séparation |---|
        table_pattern = r'(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)'

        # Trouver tous les tableaux
        last_end = 0
        for match in re.finditer(table_pattern, markdown):
            # Texte avant le tableau
            before = markdown[last_end:match.start()].strip()
            if before:
                blocks.append(before)

            # Le tableau lui-même
            blocks.append(match.group(1))
            last_end = match.end()

        # Texte après le dernier tableau
        after = markdown[last_end:].strip()
        if after:
            blocks.append(after)

        # Si pas de tableaux, diviser par sections (headers ##)
        if len(blocks) <= 1:
            blocks = re.split(r'\n(?=##\s)', markdown)

        return [b for b in blocks if b.strip()]


class HybridParser:
    """
    Parser hybride combinant extraction regex et LLM.

    Stratégie:
    1. Extraction regex rapide pour les items standards
    2. LLM pour les items complexes ou échoués
    3. Validation et fusion des résultats
    """

    def __init__(self, api_key: str):
        self.llm_parser = SemanticMELParser(api_key) if api_key else None
        self.ata_pattern = re.compile(r'(\d{2})-(\d{2})-(\d{2,3})([A-Z])?')

    def parse_table_row(self, row: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Parse une ligne de tableau avec regex d'abord, LLM si échec"""

        # Extraction regex
        item = self._regex_extraction(row)

        if item:
            # Vérifier la qualité
            if self._is_high_quality(item):
                return item

            # Qualité insuffisante, enrichir avec LLM si disponible
            if self.llm_parser:
                enriched = self._llm_enrichment(item, row)
                return enriched or item

        # Échec regex, tenter LLM complet
        if self.llm_parser:
            row_text = " | ".join(str(v) for v in row.values())
            result = self.llm_parser.parse_block(row_text)
            if result.success and result.items:
                return result.items[0]

        return item

    def _regex_extraction(self, row: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Extraction rapide par regex"""
        item_col = row.get("Item", row.get("item", row.get("System", "")))

        match = self.ata_pattern.search(str(item_col))
        if not match:
            return None

        chapter, section, item_num, suffix = match.groups()

        return {
            "ata_chapter": chapter,
            "ata_section": section,
            "item_base": f"{chapter}-{section}-{item_num.zfill(2)}",
            "variant_suffix": suffix,
            "item_description": row.get("Description", row.get("description", "")),
            "category": row.get("Category", row.get("category", row.get("Cat", "C"))),
            "number_installed": row.get("Installed", row.get("Number Installed", "-")),
            "number_required": row.get("Required", row.get("Number Required", "-")),
            "remarks_raw": row.get("Remarks", row.get("remarks", row.get("Exceptions", ""))),
            "conditions": extract_conditions_from_remarks(
                row.get("Remarks", row.get("remarks", ""))
            ) if 'extract_conditions_from_remarks' in dir() else [],
            "extraction_method": "regex"
        }

    def _is_high_quality(self, item: Dict) -> bool:
        """Vérifie si l'extraction est de bonne qualité"""
        # Critères de qualité
        has_description = bool(item.get("item_description", "").strip())
        has_category = item.get("category", "") in ["A", "B", "C", "D"]
        has_valid_ata = bool(item.get("item_base", ""))

        return has_description and has_category and has_valid_ata

    def _llm_enrichment(self, base_item: Dict, row: Dict) -> Optional[Dict]:
        """Enrichit un item basique avec le LLM"""
        # Construire un prompt ciblé pour enrichissement
        row_text = " | ".join(f"{k}: {v}" for k, v in row.items())

        prompt = f'''Enrichis les informations de cet item MEL.

ITEM DE BASE:
- Numéro: {base_item.get('item_base', 'N/A')}{base_item.get('variant_suffix', '')}
- Description: {base_item.get('item_description', 'N/A')}
- Catégorie: {base_item.get('category', 'N/A')}

DONNÉES SOURCE:
{row_text}

Retourne un JSON avec:
- conditions: liste des conditions (a), (b), (c) extraites
- applicable_msn: plages MSN si mentionnées
- operation_scope: types d'opération (CAT, SPO, etc.)
- etops_restriction: restriction ETOPS si applicable
- altitude_restriction: restriction altitude si applicable

RETOURNE UNIQUEMENT LE JSON.'''

        try:
            response, _ = self.llm_parser._call_llm(prompt, temperature=0.0, max_tokens=1000)
            enrichment = json.loads(self.llm_parser._clean_json_response(response))

            # Fusionner avec l'item de base
            enriched = {**base_item, **enrichment}
            enriched["extraction_method"] = "regex+llm"

            return enriched

        except Exception as e:
            logger.warning(f"Enrichissement LLM échoué: {e}")
            return None


# === TESTS ===
if __name__ == "__main__":
    # Test avec un bloc exemple (sans clé API réelle)
    test_block = '''
| Item | Description | Cat | Installed | Required | Remarks |
|------|-------------|-----|-----------|----------|---------|
| 21-30-01D | Ice Detection System (MSN 545 and up) | C | 2 | 1 | (O)(M) May be inoperative provided: (a) icing conditions not expected, (b) crew briefed, (c) alternate procedures used. CAT operations only. |
| 21-30-01E | Ice Detection System (MSN 1001 and up) | C | 2 | 1 | (O) May be inoperative for day VFR only. SPO/NCO operations. ETOPS prohibited. |
'''

    print("Test du parser sémantique")
    print("=" * 60)
    print("Note: Ce test nécessite une clé API Mistral valide")
    print()

    # Simuler une extraction regex basique
    parser = HybridParser(api_key="")

    # Test pattern ATA
    test_item = "21-30-01D"
    match = parser.ata_pattern.search(test_item)
    if match:
        print(f"ATA parsed: {match.groups()}")

    # Test extraction conditions (simulation)
    remarks = "(O)(M) May be inoperative provided: (a) icing conditions not expected, (b) crew briefed."
    conditions = extract_conditions_from_remarks(remarks) if MELItemV3 else []
    print(f"Conditions extraites: {[c.id if hasattr(c, 'id') else c for c in conditions]}")
