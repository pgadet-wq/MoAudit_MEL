# Documentation Technique - MoA_MEL

## Audit Automatise MEL/MMEL

**Version**: 1.0.0-poc
**Date**: Janvier 2026
**Projet**: MoA_MEL - Mistral AI / Scaleway

---

## Table des matieres

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du systeme](#2-architecture-du-systeme)
3. [Flux de donnees](#3-flux-de-donnees)
4. [Composants principaux](#4-composants-principaux)
5. [Modeles de donnees](#5-modeles-de-donnees)
6. [Pipeline d'audit](#6-pipeline-daudit)
7. [Systeme de verdicts](#7-systeme-de-verdicts)
8. [Configuration](#8-configuration)
9. [API REST](#9-api-rest)
10. [Installation et deploiement](#10-installation-et-deploiement)

---

## 1. Vue d'ensemble

### 1.1 Objectif du systeme

**MoA_MEL** (Mixture of Agents - Minimum Equipment List) est un systeme d'audit automatise concu pour comparer les documents **MEL** (Minimum Equipment List) des operateurs aeriens avec les **MMEL** (Master Minimum Equipment List) reglementaires.

L'objectif principal est de detecter les ecarts critiques ou le MEL d'un operateur serait **moins restrictif** que la MMEL de reference - ce qui constituerait une non-conformite reglementaire.

### 1.2 Contexte aeronautique

| Document | Description | Emetteur |
|----------|-------------|----------|
| **MMEL** | Liste maitresse des equipements minimaux | Autorite (EASA, FAA) |
| **MEL** | Liste adaptee par l'operateur | Compagnie aerienne |

La regle fondamentale : **MEL >= MMEL** (le MEL doit etre au moins aussi restrictif que la MMEL)

### 1.3 Technologies utilisees

| Composant | Technologie | Role |
|-----------|-------------|------|
| Backend | Python 3.11+ | Logique metier |
| API | FastAPI + Uvicorn | Services REST |
| Modeles | Pydantic 2.5+ | Validation donnees |
| LLM | Mistral AI | Extraction semantique |
| VLM | Pixtral-12b / Granite-Docling | Extraction PDF |
| Embeddings | mistral-embed | Matching semantique |
| PDF | Docling / PyMuPDF | Parsing documents |
| Frontend | React + HTML5 | Dashboard |

---

## 2. Architecture du systeme

### 2.1 Schema d'architecture globale

```
+------------------------------------------------------------------+
|                         COUCHE D'ENTREE                           |
|   Documents PDF (MEL/MMEL) ou fichiers JSON pre-parses           |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                     COUCHE DE PARSING                             |
|                                                                   |
|  +----------------+    +------------------+    +----------------+ |
|  | DoclingParser  |--->| PageContinuity   |--->| SemanticParser | |
|  | (VLM)          |    | Resolver         |    | (LLM)          | |
|  +----------------+    +------------------+    +----------------+ |
|                                                                   |
|  Alternatives: MistralParser, GeminiParser, MarkdownParser       |
|  Sortie: ParsingResultV3 avec objets MELItemV3                   |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                 COUCHE DE VALIDATION                              |
|                                                                   |
|  +-------------------+    +----------------------+                |
|  | IntegrityChecker  |--->| SelfHealingExtractor |                |
|  | (Detection)       |    | (Correction auto)    |                |
|  +-------------------+    +----------------------+                |
|                                                                   |
|  - Detection troncature                                          |
|  - Validation sequences conditions (a, b, c...)                  |
|  - Coherence categorie/quantite                                  |
|  Sortie: IntegrityReport par item                                |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                COUCHE DE MATCHING/INDEXATION                      |
|                                                                   |
|  +----------------+              +-------------------+            |
|  | MELIndexer     |              | MMELVariantTree   |            |
|  | (Exact+Embed)  |              | (Contexte MSN/Op) |            |
|  +----------------+              +-------------------+            |
|                                                                   |
|  - Matching exact: ATA + numero item                             |
|  - Matching semantique: embeddings Mistral                       |
|  - Filtrage par MSN et type operation                            |
|  Sortie: IndexingResult avec MatchResult                         |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                   COUCHE DE COMPARAISON                           |
|                                                                   |
|  +---------------------+    +------------------+                  |
|  | TreeSearchComparator|--->| ConditionComparison |               |
|  | (V2 - Contextuel)   |    | (Analyse delta)     |               |
|  +---------------------+    +------------------+                  |
|                                                                   |
|  +---------------------+                                         |
|  | MELComparator (V1)  |  <- Fallback lineaire                   |
|  +---------------------+                                         |
|                                                                   |
|  Verdicts: COMPLIANT, MORE_RESTRICTIVE, LESS_RESTRICTIVE, etc.  |
|  Sortie: ComparisonResult[] + AuditResult                        |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                    COUCHE DE SORTIE                               |
|                                                                   |
|  +------------------+  +------------------+  +----------------+   |
|  | audit_result.json|  | hitl_log.json    |  | final_report   |   |
|  +------------------+  +------------------+  +----------------+   |
|                                                                   |
|  Dashboard Web: http://localhost:8080/dashboard                  |
+------------------------------------------------------------------+
```

### 2.2 Structure des repertoires

```
MoAudit_MEL/
|
+-- src/                           # Code source principal
|   +-- models/                    # Modeles de donnees Pydantic
|   |   +-- mel_item_v3.py         # Modele MELItemV3 enrichi
|   |
|   +-- parsers/                   # Modules de parsing
|   |   +-- semantic_parser.py     # Extraction LLM
|   |   +-- page_continuity_resolver.py  # Fusion multi-pages
|   |
|   +-- validation/                # Validation et correction
|   |   +-- integrity_checker.py   # Self-healing
|   |
|   +-- matching/                  # Algorithmes de matching
|   |   +-- mmel_variant_tree.py   # Indexation contextuelle
|   |
|   +-- comparison/                # Logique de comparaison
|   |   +-- tree_search_comparator.py  # Comparateur V2
|   |
|   +-- mel_parser.py              # Parser PDF base
|   +-- mel_parser_docling.py      # Integration Docling
|   +-- mel_parser_gemini.py       # Integration Google Gemini
|   +-- mel_parser_mistral.py      # Integration Mistral
|   +-- mel_indexer.py             # Indexation MEL/MMEL
|   +-- mel_comparator.py          # Comparateur V1
|   +-- mel_comparator_v2.py       # Comparateur V2
|   +-- mel_validator.py           # Validation semantique
|   +-- pipeline.py                # Orchestrateur V1
|   +-- pipeline_v2.py             # Orchestrateur V2 (recommande)
|   +-- server.py                  # Serveur FastAPI
|   +-- config.py                  # Configuration centralisee
|   +-- dashboard.jsx              # Interface React
|
+-- data/                          # Donnees de test
|   +-- sample_mel.json            # Exemple MEL
|   +-- sample_mmel.json           # Exemple MMEL
|
+-- docs/                          # Documentation
|   +-- USAGE_GUIDE.md             # Guide utilisateur
|   +-- OPTIMIZATION_PLAN.md       # Roadmap technique
|   +-- DOCUMENTATION_TECHNIQUE.md # Ce document
|
+-- tools/                         # Outils de diagnostic
|   +-- docling_service_v*.py      # Services conversion PDF
|   +-- docling_vlm_diagnostic.py  # Debug VLM
|   +-- docling_web_ui.html        # Interface web Docling
|
+-- workflows/                     # Automatisation n8n
|   +-- moa_mel_audit_pipeline.json
|
+-- static/                        # Assets web
|   +-- dashboard.html
|
+-- outputs/                       # Resultats d'audit
+-- logs/                          # Logs systeme
+-- requirements.txt               # Dependances Python
+-- README.md                      # Documentation racine
```

---

## 3. Flux de donnees

### 3.1 Workflow complet d'un audit

```
[1] ENTREE
    |
    +-- Documents PDF ou JSON
    |   - MEL operateur
    |   - MMEL reglementaire
    |
    +-- Contexte avion
        - MSN (ex: 1280)
        - Type operation (CAT, SPO, NCO, NCC)
        - Type avion (ex: A320-214)
        - Certification ETOPS (oui/non)
            |
            v
[2] PARSING
    |
    +-- Si PDF:
    |   DoclingParser --> Markdown --> PageContinuityResolver
    |   --> SemanticParser (LLM) --> MELItemV3[]
    |
    +-- Si JSON:
        Chargement direct --> Conversion MELItemV3[]
            |
            v
[3] VALIDATION
    |
    IntegrityChecker verifie chaque item:
    +-- Troncature detectee? --> SelfHealing tente correction
    +-- Conditions incompletes? --> Flag HITL
    +-- Incoherence quantites? --> Auto-fix si possible
            |
            v
[4] INDEXATION
    |
    MMELVariantTree construit l'index MMEL:
    +-- Items regroupes par item_base
    +-- Variantes filtrees par MSN applicable
    +-- Variantes filtrees par type operation
            |
            v
[5] MATCHING
    |
    Pour chaque item MEL:
    +-- Recherche exacte (ATA + numero)
    +-- Si non trouve: recherche semantique (embeddings)
    +-- Resultat: MatchResult avec confiance
            |
            v
[6] COMPARAISON
    |
    TreeSearchComparator analyse les paires:
    +-- Compare categories (A/B/C/D)
    +-- Compare quantites (installed/required)
    +-- Compare conditions/remarques
    +-- Determine verdict et severite
            |
            v
[7] SORTIE
    |
    +-- audit_result_v2_XXXXXX.json (resultats complets)
    +-- hitl_log_XXXXXX.json (items a reviser)
    +-- final_report_XXXXXX.json (synthese)
    +-- Dashboard web interactif
```

### 3.2 Exemple concret de traitement

**Entree**: Item MEL 21-30-01D

```json
{
  "item_number": "21-30-01D",
  "category": "C",
  "remarks": "(O)(M) May be inoperative provided icing conditions not expected"
}
```

**Apres parsing et enrichissement**:

```
MELItemV3:
  item_base: "21-30-01"
  variant_suffix: "D"
  category: "C"
  conditions: [
    {id: "a", text: "icing conditions not expected"},
    {id: "b", text: "crew briefed"}
  ]
  applicable_msn: [MSNRange(start=545, end=999)]
  operation_scope: ["CAT", "SPO"]
```

**Matching avec MMEL** (contexte: MSN 1280, operation CAT):

```
MMEL Reference trouvee:
  21-30-01D: category=B, conditions=[a, b, c]
  Applicable: MSN 545-999, CAT
```

**Comparaison**:

```
Categorie: C (MEL) vs B (MMEL) --> MEL PLUS restrictif (OK)
Conditions: 2 vs 3 --> Condition (c) manquante dans MEL
Verdict: LESS_RESTRICTIVE (condition manquante)
Severite: CRITICAL
```

---

## 4. Composants principaux

### 4.1 Parsers (`src/parsers/` et `src/mel_parser_*.py`)

#### 4.1.1 DoclingParser (`mel_parser_docling.py`)

- **Role**: Extraction de tableaux PDF via Docling + VLM
- **Entree**: Fichier PDF
- **Sortie**: Blocs Markdown structures
- **Modele**: Granite-Docling VLM

```python
from mel_parser_docling import parse_document

result = parse_document("MEL.pdf", output_format="markdown")
# Retourne: {"blocks": [...], "tables": [...]}
```

#### 4.1.2 PageContinuityResolver (`parsers/page_continuity_resolver.py`)

- **Role**: Fusionner les tableaux coupes sur plusieurs pages
- **Probleme resolu**: Tableaux MEL souvent fragmentes entre pages
- **Algorithme**:
  1. Detecte les en-tetes de tableau
  2. Identifie les lignes orphelines
  3. Fusionne avec le tableau precedent

#### 4.1.3 SemanticMELParser (`parsers/semantic_parser.py`)

- **Role**: Extraction structuree via LLM
- **Modele**: mistral-large-latest
- **Sortie**: Objets MELItemV3 valides

### 4.2 Validation (`src/validation/`)

#### 4.2.1 IntegrityChecker (`integrity_checker.py`)

Detecte les problemes d'extraction:

| Probleme | Detection | Auto-fix |
|----------|-----------|----------|
| Troncature remarques | Pattern "..." ou coupe abrupte | Re-extraction |
| Conditions incompletes | Sequence (a), (c) manque (b) | Flag HITL |
| Categorie invalide | Hors A/B/C/D | Correction si evident |
| Quantites incoherentes | required > installed | Inversion |

```python
from validation.integrity_checker import IntegrityChecker

checker = IntegrityChecker(auto_fix=True)
report = checker.validate_item(mel_item)

if not report.is_valid:
    for issue in report.issues:
        print(f"[{issue.severity}] {issue.message}")
```

#### 4.2.2 SelfHealingExtractor

- **Role**: Tenter de corriger automatiquement les items invalides
- **Methode**: Re-extraction ciblee avec contexte supplementaire

### 4.3 Matching (`src/matching/`)

#### 4.3.1 MMELVariantTree (`mmel_variant_tree.py`)

Index hierarchique des variantes MMEL:

```
MMEL Tree Structure:
|
+-- 21-30 (ATA Chapter-Section)
|   +-- 21-30-01 (Item Base)
|       +-- Variant A (MSN 001-544, ALL ops)
|       +-- Variant B (MSN 545-999, CAT/SPO)
|       +-- Variant C (MSN 1000+, ALL ops)
|       +-- Variant D (MSN 545-999, CAT/SPO, ETOPS)
```

**Filtrage contextuel**:

```python
from matching.mmel_variant_tree import MMELVariantTree, AircraftContext

tree = MMELVariantTree()
tree.build_from_items(mmel_items)

context = AircraftContext(msn=1280, operation_type="CAT")
match = tree.match_mel_item(mel_item, msn=1280, operation="CAT")

# match.confidence: EXACT, VARIANT, PARTIAL, INFERRED, NONE
# match.matched_variant: MELItemV3 de la MMEL
```

#### 4.3.2 MELIndexer (`mel_indexer.py`)

Matching hybride exact + semantique:

| Methode | Poids | Description |
|---------|-------|-------------|
| Exact | 60% | ATA chapter + item number |
| Semantique | 40% | Embeddings Mistral des descriptions |

```python
from mel_indexer import MELIndexer

indexer = MELIndexer(api_key="...")
result = indexer.index_mel_items(mel_items, mmel_items)

# Score combine: 0.6 * exact_score + 0.4 * semantic_score
```

### 4.4 Comparaison (`src/comparison/`)

#### 4.4.1 TreeSearchComparator (`tree_search_comparator.py`)

Comparateur V2 avec conscience du contexte:

```python
from comparison.tree_search_comparator import TreeSearchComparator

comparator = TreeSearchComparator(mmel_tree)
result = comparator.compare_item(mel_item, context)

# result.verdict: VerdictType
# result.severity: SeverityLevel
# result.issues: List[str]
# result.delta: ConditionDelta
```

**Logique de comparaison des categories**:

```
Hierarchie: A(1) > B(2) > C(3) > D(4)
Plus le numero est bas, plus c'est restrictif.

MEL cat C vs MMEL cat D --> MORE_RESTRICTIVE (OK)
MEL cat D vs MMEL cat C --> LESS_RESTRICTIVE (CRITIQUE!)
```

### 4.5 Pipeline (`src/pipeline_v2.py`)

Orchestrateur principal:

```python
from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

config = PipelineConfigV2(
    aircraft_msn=1280,
    operation_type="CAT",
    api_key="...",
    enable_self_healing=True
)

pipeline = MoAMELPipelineV2(config)
result = pipeline.run_full_pipeline(
    mel_source="MEL.pdf",
    mmel_source="MMEL.pdf"
)
```

---

## 5. Modeles de donnees

### 5.1 MELItemV3 (`models/mel_item_v3.py`)

Modele principal pour un item MEL/MMEL:

```python
class MELItemV3(BaseModel):
    # Identification
    ata_chapter: str              # "21"
    ata_section: str              # "30"
    item_base: str                # "21-30-01"
    variant_suffix: Optional[str] # "D"
    item_number: str              # "21-30-01D" (calcule)

    # Description
    item_description: str         # "Ice Detection System"

    # Categorie et dispatch
    category: Literal["A","B","C","D"]
    number_installed: str         # "2"
    number_required: str          # "1"
    rectification_interval: Optional[RectificationInterval]

    # Remarques et conditions
    remarks_raw: str              # Texte brut
    conditions: List[ApplicabilityCondition]  # (a), (b), (c)...
    has_operational_procedure: bool   # (O)
    has_maintenance_procedure: bool   # (M)

    # Contexte d'applicabilite
    applicable_msn: List[MSNRange]
    operation_scope: List[OperationType]  # CAT, SPO, NCO, NCC
    aircraft_variants: List[str]

    # Restrictions
    etops_restriction: Optional[str]
    altitude_restriction: Optional[str]
    rvsm_restriction: Optional[str]
    icing_restriction: Optional[str]

    # Metadonnees
    source_document: str
    source_page: int
    extraction_confidence: float  # 0.0 - 1.0
    needs_hitl: bool             # Necessite revision humaine
    integrity_validated: bool
```

### 5.2 MSNRange

Plage de numeros de serie avion:

```python
class MSNRange(BaseModel):
    start: Optional[int]       # 545
    end: Optional[int]         # 999 (None = ouvert)
    explicit_list: List[int]   # [101, 102, 103]
    raw_text: str              # "MSN 545-999"

    def matches(self, msn: int) -> bool:
        """Verifie si un MSN est dans cette plage"""
```

Exemples de parsing:

| Texte | start | end | Interpretation |
|-------|-------|-----|----------------|
| "MSN 545-999" | 545 | 999 | Plage fermee |
| "MSN 1001 and up" | 1001 | None | Plage ouverte |
| "MSN 101, 102, 103" | - | - | Liste explicite |
| "ALL" | None | None | Tous les MSN |

### 5.3 ApplicabilityCondition

Condition extraite des remarques:

```python
class ApplicabilityCondition(BaseModel):
    id: str           # "a", "b", "c"
    text: str         # "icing conditions not expected"
    is_complete: bool # True si texte complet
    condition_type: Optional[Literal[
        "operational",   # Procedure equipage
        "maintenance",   # Procedure maintenance
        "equipment",     # Equipement requis
        "restriction"    # Limitation operationnelle
    ]]
```

---

## 6. Pipeline d'audit

### 6.1 Etapes du pipeline V2

| Etape | Composant | Entree | Sortie |
|-------|-----------|--------|--------|
| 1 | Parser | PDF/JSON | MELItemV3[] |
| 2 | IntegrityChecker | MELItemV3[] | IntegrityReport[] |
| 3 | SelfHealer | Items invalides | Items corriges |
| 4 | MMELVariantTree | MMEL items | Index structure |
| 5 | Matcher | MEL + Index | MatchResult[] |
| 6 | Comparator | Paires matchees | ComparisonResult[] |
| 7 | Reporter | Resultats | JSON + Dashboard |

### 6.2 Execution en ligne de commande

```bash
# Audit standard (JSON pre-parse)
python src/pipeline_v2.py \
    --mel data/sample_mel.json --mel-json \
    --mmel data/sample_mmel.json --mmel-json \
    --msn 1280 \
    --operation CAT

# Audit PDF avec LLM
python src/pipeline_v2.py \
    --mel documents/MEL.pdf \
    --mmel documents/MMEL.pdf \
    --msn 1280 \
    --operation CAT \
    --api-key $MISTRAL_API_KEY

# Options avancees
python src/pipeline_v2.py \
    --mel MEL.pdf --mmel MMEL.pdf \
    --msn 1500 \
    --operation SPO \
    --aircraft-type A320-251N \
    --etops \
    --output-dir ./resultats \
    --no-self-healing
```

### 6.3 Execution programmatique

```python
import sys
sys.path.insert(0, "src")

from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

# Configuration
config = PipelineConfigV2(
    aircraft_msn=1280,
    operation_type="CAT",
    aircraft_type="A320-214",
    api_key="sk-...",
    use_llm_parser=True,
    enable_self_healing=True,
    output_dir="outputs"
)

# Execution
pipeline = MoAMELPipelineV2(config)
result = pipeline.run_full_pipeline(
    mel_source="data/sample_mel.json",
    mmel_source="data/sample_mmel.json",
    mel_is_json=True,
    mmel_is_json=True
)

# Analyse resultats
print(f"Taux de conformite: {result['summary']['compliance_rate']}%")
print(f"Critiques: {result['summary']['less_restrictive_critical']}")

for item in result['comparisons']:
    if item['verdict'] == 'LESS_RESTRICTIVE':
        print(f"ALERTE: {item['mel_item']} - {item['issues']}")
```

---

## 7. Systeme de verdicts

### 7.1 Types de verdicts

| Verdict | Code | Description |
|---------|------|-------------|
| `COMPLIANT` | OK | MEL identique a MMEL |
| `MORE_RESTRICTIVE` | MR | MEL plus strict (acceptable) |
| `LESS_RESTRICTIVE` | LR | MEL moins strict (VIOLATION) |
| `MISSING_IN_MEL` | MIM | Item MMEL absent de MEL |
| `MISSING_IN_MMEL` | MIR | Item specifique operateur |
| `CATEGORY_MISMATCH` | CM | Categories differentes |
| `REMARKS_DEVIATION` | RD | Ecart dans remarques |
| `VARIANT_MISMATCH` | VM | Variante incorrecte |

### 7.2 Niveaux de severite

| Severite | SLA | Action requise |
|----------|-----|----------------|
| `critical` | 48h | Action immediate - violation reglementaire |
| `high` | 48h | Revue prioritaire |
| `medium` | 72h | Revue standard |
| `warning` | 1 sem | Verification recommandee |
| `info` | - | Informatif uniquement |

### 7.3 Matrice verdict/severite

| Verdict | Severite par defaut |
|---------|---------------------|
| COMPLIANT | info |
| MORE_RESTRICTIVE | info |
| LESS_RESTRICTIVE | **critical** |
| MISSING_IN_MEL | warning |
| MISSING_IN_MMEL | info |
| CATEGORY_MISMATCH | high |
| REMARKS_DEVIATION | medium |

### 7.4 Logique de comparaison des categories

```
Hierarchie de restrictivite (plus restrictif en haut):
    A (1) - Rectification avant vol
    B (2) - Rectification sous 3 jours
    C (3) - Rectification sous 10 jours
    D (4) - Pas de limite

Comparaison:
    MEL.category_rank < MMEL.category_rank --> MORE_RESTRICTIVE
    MEL.category_rank > MMEL.category_rank --> LESS_RESTRICTIVE
    MEL.category_rank == MMEL.category_rank --> Comparer conditions
```

---

## 8. Configuration

### 8.1 Fichier de configuration (`src/config.py`)

```python
@dataclass
class AppConfig:
    mistral: MistralConfig      # API Mistral
    database: DatabaseConfig    # Base de donnees
    parsing: ParsingConfig      # Parametres extraction
    matching: MatchingConfig    # Parametres matching
    comparison: ComparisonConfig # Parametres comparaison
    hitl: HITLConfig           # Human-in-the-loop
    output: OutputConfig       # Formats sortie
```

### 8.2 Variables d'environnement

| Variable | Description | Defaut |
|----------|-------------|--------|
| `MISTRAL_API_KEY` | Cle API Mistral | (requis) |
| `PORT` | Port serveur web | 8080 |
| `PG_HOST` | Hote PostgreSQL | localhost |
| `PG_PORT` | Port PostgreSQL | 5432 |
| `PG_DATABASE` | Nom base | moa_mel |
| `PG_USER` | Utilisateur | postgres |
| `PG_PASSWORD` | Mot de passe | - |

### 8.3 Parametres de matching

```python
@dataclass
class MatchingConfig:
    exact_match_fields = ["ata_chapter", "item_number"]
    semantic_match_fields = ["item_description", "remarks"]
    semantic_threshold = 0.85   # Seuil similarite
    exact_weight = 0.6          # Poids matching exact
    semantic_weight = 0.4       # Poids matching semantique
```

### 8.4 Parametres de parsing

```python
@dataclass
class ParsingConfig:
    confidence_threshold = 0.85  # Validation auto
    hitl_threshold = 0.70       # Revue humaine si en-dessous
    output_format = "json"
```

---

## 9. API REST

### 9.1 Endpoints principaux

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/` | Verification serveur |
| `GET` | `/health` | Etat de sante |
| `POST` | `/api/upload/{doc_type}` | Upload document |
| `POST` | `/api/audit/start` | Demarrer audit |
| `GET` | `/api/audit/status/{job_id}` | Statut job |
| `GET` | `/api/audit/result/{job_id}` | Resultat audit |
| `GET` | `/dashboard` | Interface web |

### 9.2 Demarrer un audit

```bash
curl -X POST http://localhost:8080/api/audit/start \
  -H "Content-Type: application/json" \
  -d '{
    "mel_path": "data/sample_mel.json",
    "mmel_path": "data/sample_mmel.json",
    "mel_is_json": true,
    "mmel_is_json": true,
    "msn": 1280,
    "operation": "CAT"
  }'
```

Reponse:
```json
{
  "job_id": "audit_20260128_143022",
  "status": "started"
}
```

### 9.3 Consulter le resultat

```bash
curl http://localhost:8080/api/audit/result/audit_20260128_143022
```

Reponse:
```json
{
  "job_id": "audit_20260128_143022",
  "status": "completed",
  "summary": {
    "total_items": 10,
    "compliant": 6,
    "more_restrictive": 2,
    "less_restrictive_critical": 1,
    "missing": 1,
    "compliance_rate": 80.0
  },
  "comparisons": [...],
  "hitl_items": [...]
}
```

### 9.4 Lancer le serveur

```bash
cd src
python server.py
# ou
uvicorn server:app --host 0.0.0.0 --port 8080
```

---

## 10. Installation et deploiement

### 10.1 Prerequis

- Python 3.11+
- Compte Mistral AI (cle API)
- 4 Go RAM minimum
- GPU optionnel (pour VLM local)

### 10.2 Installation

```bash
# Cloner le projet
git clone https://github.com/pgadet-wq/MoAudit_MEL.git
cd MoAudit_MEL

# Environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Dependances
pip install -r requirements.txt

# Configuration
cp .env.example .env
# Editer .env avec votre cle API Mistral
```

### 10.3 Dependances principales

```
fastapi>=0.109.0
uvicorn>=0.27.0
pydantic>=2.5.0
mistralai>=0.4.0
docling>=0.1.0
pymupdf>=1.23.0
numpy>=1.26.0
pandas>=2.1.0
httpx>=0.26.0
aiofiles>=23.0.0
python-dotenv>=1.0.0
loguru>=0.7.0
```

### 10.4 Test de l'installation

```bash
# Test rapide
python run_test.py

# Test complet du pipeline V2
python test_pipeline_v2.py

# Resultat attendu
# Items compares: 10
# Conformite: 80%
# Critiques: 1
```

### 10.5 Deploiement production

```bash
# Avec Gunicorn
pip install gunicorn
gunicorn src.server:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080

# Avec Docker (a venir)
docker build -t moa-mel .
docker run -p 8080:8080 -e MISTRAL_API_KEY=... moa-mel
```

---

## Annexes

### A. Glossaire

| Terme | Definition |
|-------|------------|
| **ATA** | Air Transport Association - systeme de numerotation des chapitres |
| **CAT** | Commercial Air Transport |
| **ETOPS** | Extended-range Twin-engine Operational Performance Standards |
| **HITL** | Human-in-the-Loop - revision humaine requise |
| **MEL** | Minimum Equipment List - liste operateur |
| **MMEL** | Master MEL - liste reglementaire |
| **MSN** | Manufacturer Serial Number |
| **NCO** | Non-Commercial Operations |
| **NCC** | Non-Commercial Complex |
| **SPO** | Specialised Operations |
| **VLM** | Vision Language Model |

### B. References

- EASA Part-M - Continuing Airworthiness
- FAA Order 8900.1 - Flight Standards Information Management System
- MMEL Policy Board Handbook

### C. Historique des versions

| Version | Date | Changements |
|---------|------|-------------|
| 1.0.0-poc | 2025-11 | Version initiale PoC |
| 1.1.0 | 2025-11 | Integration Granite-Docling VLM |
| 1.2.0 | 2025-11 | Pipeline V2 avec contexte |

---

**Document genere pour MoA_MEL v1.0.0-poc**
**Mistral AI / Scaleway**
