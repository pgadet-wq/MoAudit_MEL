# Guide d'Utilisation - Pipeline V2 MoA_MEL

## Prérequis

### Installation des dépendances

```bash
pip install pydantic docling requests numpy
```

### Configuration de l'API Mistral (optionnel mais recommandé)

```bash
export MISTRAL_API_KEY="votre-clé-api"
```

---

## Utilisation Rapide

### Avec des fichiers JSON pré-parsés

```bash
cd /home/user/MoAudit_MEL

python src/pipeline_v2.py \
    --mel data/sample_mel.json \
    --mmel data/sample_mmel.json \
    --mel-json --mmel-json \
    --msn 1280 \
    --operation CAT
```

### Avec des PDF (nécessite Docling)

```bash
python src/pipeline_v2.py \
    --mel documents/MEL_A320.pdf \
    --mmel documents/MMEL_A320_EASA.pdf \
    --msn 1280 \
    --operation CAT \
    --api-key $MISTRAL_API_KEY
```

---

## Options de la Ligne de Commande

| Option | Description | Exemple |
|--------|-------------|---------|
| `--mel` | Chemin vers le fichier MEL (PDF ou JSON) | `--mel MEL.pdf` |
| `--mmel` | Chemin vers le fichier MMEL (PDF ou JSON) | `--mmel MMEL.pdf` |
| `--mel-json` | Indique que le fichier MEL est en JSON | `--mel-json` |
| `--mmel-json` | Indique que le fichier MMEL est en JSON | `--mmel-json` |
| `--msn` | MSN de l'avion (obligatoire pour le contexte) | `--msn 1280` |
| `--operation` | Type d'opération: CAT, SPO, NCO, NCC | `--operation CAT` |
| `--aircraft-type` | Type d'avion (ex: A320-214) | `--aircraft-type A320-214` |
| `--etops` | Avion certifié ETOPS | `--etops` |
| `--api-key` | Clé API Mistral pour parsing LLM | `--api-key xxx` |
| `--output-dir` | Répertoire de sortie | `--output-dir outputs` |
| `--no-llm` | Désactiver le parsing LLM | `--no-llm` |
| `--no-self-healing` | Désactiver la validation auto | `--no-self-healing` |

---

## Exemples d'Utilisation

### Cas 1: Audit standard pour opérations commerciales (CAT)

```bash
python src/pipeline_v2.py \
    --mel data/sample_mel.json --mel-json \
    --mmel data/sample_mmel.json --mmel-json \
    --msn 1280 \
    --operation CAT \
    --aircraft-type A320-214
```

### Cas 2: Audit pour opérations spéciales (SPO)

```bash
python src/pipeline_v2.py \
    --mel MEL.json --mel-json \
    --mmel MMEL.json --mmel-json \
    --msn 545 \
    --operation SPO
```

### Cas 3: Audit avec ETOPS

```bash
python src/pipeline_v2.py \
    --mel MEL.pdf \
    --mmel MMEL.pdf \
    --msn 1500 \
    --operation CAT \
    --etops \
    --api-key $MISTRAL_API_KEY
```

---

## Utilisation Programmatique (Python)

### Pipeline complet

```python
import sys
sys.path.insert(0, "src")

from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

# Configuration
config = PipelineConfigV2(
    aircraft_msn=1280,
    operation_type="CAT",
    aircraft_type="A320-214",
    output_dir="outputs",
    api_key="your-api-key",  # Optionnel
    use_llm_parser=True,
    enable_self_healing=True
)

# Créer et exécuter le pipeline
pipeline = MoAMELPipelineV2(config)

result = pipeline.run_full_pipeline(
    mel_source="data/sample_mel.json",
    mmel_source="data/sample_mmel.json",
    mel_is_json=True,
    mmel_is_json=True
)

# Analyser les résultats
print(f"Conformité: {result['summary']['compliance_rate']}%")
print(f"Critiques: {result['summary']['less_restrictive_critical']}")
```

### Utilisation des composants individuels

```python
# 1. MMEL Variant Tree pour matching contextuel
from matching.mmel_variant_tree import MMELVariantTree, AircraftContext

tree = MMELVariantTree()
tree.build_from_items(mmel_items)

# Trouver la variante applicable
context = AircraftContext(msn=1280, operation_type="CAT")
match = tree.match_mel_item(
    {"item_number": "21-30-01", "item_base": "21-30-01"},
    msn=context.msn,
    operation=context.operation_type
)
print(f"Variante applicable: {match.matched_variant.item_number}")

# 2. Integrity Checker pour validation
from validation.integrity_checker import IntegrityChecker

checker = IntegrityChecker()
report = checker.validate_item(item)
if not report.is_valid:
    print(f"Problèmes détectés: {[i.message for i in report.issues]}")

# 3. Tree-Search Comparator
from comparison.tree_search_comparator import TreeSearchComparator

comparator = TreeSearchComparator(tree)
result = comparator.compare_item(mel_item, context)
print(f"Verdict: {result.verdict.value}")
```

---

## Interprétation des Résultats

### Verdicts

| Verdict | Signification | Action |
|---------|--------------|--------|
| `COMPLIANT` | MEL = MMEL | Aucune action |
| `MORE_RESTRICTIVE` | MEL plus restrictive que MMEL | OK (plus sûr) |
| `LESS_RESTRICTIVE` | MEL moins restrictive que MMEL | **CRITIQUE - Action immédiate** |
| `MISSING_IN_MEL` | Item MMEL absent de la MEL | Vérifier si équipement installé |
| `MISSING_IN_MMEL` | Item MEL absent de la MMEL | OK (spécifique opérateur) |
| `VARIANT_MISMATCH` | Variante mal matchée | Revue manuelle |

### Sévérités

| Sévérité | SLA | Description |
|----------|-----|-------------|
| `critical` | 48h | MEL moins restrictive - violation |
| `high` | 48h | Écart majeur |
| `medium` | 72h | Écart modéré |
| `warning` | 1 sem | À vérifier |
| `info` | - | Informatif |

---

## Fichiers Générés

Après chaque exécution, les fichiers suivants sont créés dans `outputs/`:

| Fichier | Description |
|---------|-------------|
| `audit_result_v2_XXXXXX.json` | Résultat complet de l'audit |
| `hitl_log_XXXXXX.json` | Items nécessitant revue humaine |
| `final_report_XXXXXX.json` | Rapport final avec recommandations |
| `parsed_mel_XXXXXX.json` | Résultat du parsing MEL |
| `parsed_mmel_XXXXXX.json` | Résultat du parsing MMEL |
| `pipeline_state_XXXXXX.json` | État du pipeline |

---

## Résolution des Problèmes

### "Modules V2 non disponibles"

```bash
pip install pydantic
```

### "No module named 'docling'"

```bash
pip install docling
```

### Parsing échoue sur les PDF complexes

1. Utilisez l'option `--api-key` pour activer le parsing LLM
2. Convertissez manuellement le PDF en JSON au format attendu

### Format JSON attendu pour les items

```json
{
  "items": [
    {
      "item_number": "21-51-01",
      "ata_chapter": "21",
      "item_description": "Air Conditioning Pack",
      "category": "C",
      "number_installed": "2",
      "number_required": "1",
      "remarks": "(O) May be inoperative provided...",
      "applicable_msn": ["MSN 545 and up"],
      "operation_scope": ["CAT", "SPO"]
    }
  ]
}
```

---

## Tests

Pour valider l'installation:

```bash
python test_pipeline_v2.py
```

Résultat attendu:
```
🎉 Tous les tests ont réussi!
```

---

## Architecture des Nouveaux Modules

```
src/
├── models/
│   └── mel_item_v3.py       # Modèles Pydantic enrichis
├── parsers/
│   ├── page_continuity_resolver.py  # Fusion multi-pages
│   └── semantic_parser.py           # Extraction LLM
├── validation/
│   └── integrity_checker.py         # Self-healing
├── matching/
│   └── mmel_variant_tree.py         # Index par contexte
├── comparison/
│   └── tree_search_comparator.py    # Comparaison Tree-Search
└── pipeline_v2.py                   # Orchestrateur V2
```

---

## Support

Pour toute question ou problème:
- Consultez le plan d'optimisation: `docs/OPTIMIZATION_PLAN.md`
- Examinez les tests: `test_pipeline_v2.py`
