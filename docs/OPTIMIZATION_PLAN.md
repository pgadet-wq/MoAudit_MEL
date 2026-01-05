# Plan d'Optimisation du Parsing MEL/MMEL

## Diagnostic : Mapping Défaillances → Code Actuel

### 1. Rupture de Continuité Multi-Pages

**Problème identifié :** Les tableaux se poursuivant sur plusieurs pages sont fragmentés.

**Code actuel concerné :** `mel_parser_docling.py:153-164`
```python
for i, table in enumerate(tables):
    # Chaque tableau est traité ISOLÉMENT
    df = table.export_to_dataframe()
    items = extract_mel_items_from_table(df, table_idx=i)
```

**Cause racine :** Docling retourne des `tables` séparées par page. Aucune logique de fusion n'existe.

---

### 2. Troncature du Texte (Remarks)

**Problème identifié :** Les cellules "Remarks" longues sont tronquées ou mal capturées.

**Code actuel concerné :** `mel_parser_docling.py:108`
```python
remarks = values[5] if len(values) > 5 else ""
# Pas de validation de complétude
```

**Cause racine :**
- Aucune validation de fin de phrase
- Pas de détection des conditions (a), (b), (c) incomplètes
- Docling peut tronquer les cellules multi-lignes

---

### 3. Cécité Contextuelle (MSN/Operation Types)

**Problème identifié :** Les qualificateurs MSN et types d'exploitation sont ignorés ou mal associés.

**Code actuel :** `mel_parser_v2.py` tente d'extraire ces infos mais :
```python
def extract_msn_range(text: str) -> str:
    msn_pattern = r'MSN\s*([\d\s,\-]+|ALL)'  # Pattern trop simple
```

**Causes racines :**
- Le MSN peut être dans la colonne "Item" (ex: `21-30-01D (MSN 545 and up)`)
- Les variantes A/B/C/D ne sont pas liées à leur contexte d'applicabilité
- La comparaison ne filtre pas par MSN/Operation (`mel_comparator.py`)

---

### 4. Logique de Comparaison Linéaire

**Problème identifié :** Comparaison 1:1 sans gestion des variantes multiples.

**Code actuel :** `mel_indexer.py:267-290`
```python
def find_exact_match(self, mel_item: Dict[str, Any]) -> Tuple[Optional[str], float]:
    # Match sur item_number seul, sans considérer:
    # - Les variantes (A, B, C, D)
    # - Le contexte MSN/Operation
```

**Cause racine :** L'algorithme ne peut pas dire "Pour MSN 1280 en CAT, quelle variante MMEL appliquer?"

---

## Architecture Cible V2

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PHASE 1: INGESTION                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  PDF → Docling → Markdown Structuré → Page Objects avec métadonnées         │
│                                                                              │
│  Nouveau: PageContinuityResolver                                             │
│  - Détecte "continued" et headers répétés                                    │
│  - Fusionne les blocs logiques cross-page                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 2: PARSING SÉMANTIQUE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Markdown Block → LLM (Mistral Large) → MELItemV3 (Pydantic)                │
│                                                                              │
│  Extraction structurée:                                                      │
│  - item_base: "21-30-01"                                                    │
│  - variant: "D"                                                             │
│  - applicable_msn: ["545-999", "1001+"]                                     │
│  - operation_scope: ["CAT", "SPO"]                                          │
│  - conditions: [{"id": "a", "text": "..."}, {"id": "b", "text": "..."}]     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 3: VALIDATION & SELF-HEALING                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  IntegrityChecker:                                                           │
│  - Phrases terminées par ponctuation valide                                  │
│  - Conditions (a), (b), (c) complètes et séquentielles                       │
│  - Si échec → Ré-extraction avec fenêtre spatiale élargie                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 4: INDEXATION CONTEXTUELLE                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  MMELVariantTree:                                                            │
│  - Structure: item_base → [variantes avec contextes]                         │
│  - Index par MSN range                                                       │
│  - Index par operation type                                                  │
│                                                                              │
│  Query: "21-30-01 pour MSN 1280 en CAT" → Variante D spécifique             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 5: COMPARAISON TREE-SEARCH                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  AircraftContext:                                                            │
│  - MSN: 1280                                                                │
│  - Operation: CAT                                                           │
│  - Installed Equipment: [...]                                               │
│                                                                              │
│  Algorithme:                                                                 │
│  1. Filtrer MMEL par contexte avion                                         │
│  2. Matcher MEL item → Variante MMEL applicable                             │
│  3. Comparer sémantiquement (catégorie, conditions, etc.)                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Implémentation Détaillée

### Module 1: `page_continuity_resolver.py`

```python
@dataclass
class PageBlock:
    page_number: int
    content: str
    is_table_continuation: bool
    table_id: Optional[str]
    header_row: Optional[str]  # Pour détecter répétition

class PageContinuityResolver:
    """Fusionne les blocs multi-pages"""

    CONTINUATION_MARKERS = [
        r'\bcontinued\b',
        r'\(cont\.?\)',
        r'\(suite\)',
    ]

    def detect_continuation(self, current_block: PageBlock,
                           previous_block: PageBlock) -> bool:
        """Détecte si current_block continue previous_block"""
        # 1. Marqueur explicite
        if self._has_continuation_marker(current_block.content):
            return True

        # 2. Header répété (même colonnes)
        if self._headers_match(current_block.header_row,
                               previous_block.header_row):
            return True

        # 3. Item number incomplet (ligne commence par lettre seule)
        if re.match(r'^[A-Z]\s', current_block.content.strip()):
            return True

        return False

    def merge_blocks(self, blocks: List[PageBlock]) -> List[MergedBlock]:
        """Fusionne les blocs consécutifs appartenant au même item"""
        # Algorithme de fusion
```

### Module 2: `mel_item_v3.py` (Pydantic Models)

```python
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal

class ApplicabilityCondition(BaseModel):
    """Condition d'applicabilité (a), (b), (c)..."""
    id: str = Field(..., pattern=r'^[a-z]$')
    text: str
    is_complete: bool = True

class MSNRange(BaseModel):
    """Plage de MSN applicable"""
    start: Optional[int] = None
    end: Optional[int] = None
    explicit_list: List[int] = Field(default_factory=list)

    def matches(self, msn: int) -> bool:
        if self.explicit_list and msn in self.explicit_list:
            return True
        if self.start and self.end:
            return self.start <= msn <= self.end
        if self.start and not self.end:
            return msn >= self.start
        return True  # ALL

class MELItemV3(BaseModel):
    """Item MEL/MMEL avec contexte complet"""

    # Identification
    ata_chapter: str = Field(..., pattern=r'^\d{2}$')
    ata_section: str = Field(..., pattern=r'^\d{2}$')
    item_base: str = Field(..., pattern=r'^\d{2}-\d{2}-\d{2,3}$')
    variant_suffix: Optional[str] = Field(None, pattern=r'^[A-Z]$')

    @property
    def item_number(self) -> str:
        return f"{self.item_base}{self.variant_suffix or ''}"

    # Description
    item_description: str

    # Catégorie et dispatch
    category: Literal["A", "B", "C", "D"]
    number_installed: str
    number_required: str
    rectification_interval: Optional[str] = None

    # Remarques structurées
    remarks_raw: str = ""
    conditions: List[ApplicabilityCondition] = Field(default_factory=list)
    has_operational_procedure: bool = False  # (O)
    has_maintenance_procedure: bool = False  # (M)

    # Contexte d'applicabilité
    applicable_msn: List[MSNRange] = Field(default_factory=list)
    operation_scope: List[Literal["CAT", "NCC", "NCO", "SPO"]] = Field(
        default_factory=list
    )

    # Restrictions
    etops_restriction: Optional[str] = None
    altitude_restriction: Optional[str] = None

    # Métadonnées
    source_page: int = 0
    source_table: int = 0
    extraction_confidence: float = 1.0
    integrity_validated: bool = False

    @field_validator('conditions')
    @classmethod
    def validate_conditions_sequence(cls, v):
        """Vérifie que les conditions sont séquentielles"""
        if not v:
            return v
        expected = 'a'
        for cond in v:
            if cond.id != expected:
                raise ValueError(f"Condition sequence broken: expected {expected}, got {cond.id}")
            expected = chr(ord(expected) + 1)
        return v
```

### Module 3: `semantic_parser.py` (LLM-Driven)

```python
class SemanticMELParser:
    """Parser utilisant LLM pour extraction structurée"""

    EXTRACTION_PROMPT = '''
Analyse le bloc MEL/MMEL suivant et extrais les informations en JSON strict.

BLOC:
{block_content}

SCHÉMA ATTENDU:
{json_schema}

INSTRUCTIONS:
1. Sépare l'ID (21-30-01) du suffixe de variante (D)
2. Extrait les MSN dans applicable_msn si présents (ex: "MSN 545 and up")
3. Extrait les types d'opération dans operation_scope (CAT, SPO, NCO, NCC)
4. Décompose les conditions (a), (b), (c) dans le champ conditions
5. Identifie (O) = operational, (M) = maintenance
6. Si ETOPS mentionné, extrait la restriction

RETOURNE UNIQUEMENT LE JSON, sans markdown.
'''

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "mistral-large-latest"

    def parse_block(self, block_content: str) -> MELItemV3:
        """Parse un bloc avec LLM et valide avec Pydantic"""
        schema = MELItemV3.model_json_schema()

        prompt = self.EXTRACTION_PROMPT.format(
            block_content=block_content,
            json_schema=json.dumps(schema, indent=2)
        )

        response = self._call_llm(prompt)

        # Validation Pydantic
        try:
            item = MELItemV3.model_validate_json(response)
            item.integrity_validated = self._validate_integrity(item, block_content)
            return item
        except ValidationError as e:
            # Retry avec prompt corrigé
            return self._retry_with_error_context(block_content, e)
```

### Module 4: `integrity_checker.py`

```python
class IntegrityChecker:
    """Validation d'intégrité post-extraction"""

    INCOMPLETE_ENDINGS = [
        r'\band\s*$',
        r'\bwith\s*$',
        r'\bthe\s*$',
        r'\bor\s*$',
        r'\bto\s*$',
        r'\bfor\s*$',
        r'\bprovided\s*$',
        r',\s*$',
    ]

    def check_sentence_completeness(self, text: str) -> Tuple[bool, str]:
        """Vérifie qu'une phrase est complète"""
        text = text.strip()

        # Vérifier terminaison valide
        if not text:
            return True, ""

        if not re.search(r'[.!?)]$', text):
            for pattern in self.INCOMPLETE_ENDINGS:
                if re.search(pattern, text, re.IGNORECASE):
                    return False, f"Phrase incomplète: se termine par '{pattern}'"

        return True, ""

    def check_conditions_complete(self, conditions: List[ApplicabilityCondition]) -> Tuple[bool, str]:
        """Vérifie que toutes les conditions sont complètes"""
        for cond in conditions:
            is_complete, reason = self.check_sentence_completeness(cond.text)
            if not is_complete:
                return False, f"Condition ({cond.id}) incomplète: {reason}"
        return True, ""

    def validate_item(self, item: MELItemV3,
                     source_pdf: str,
                     source_page: int) -> Tuple[bool, List[str]]:
        """Valide un item et retourne les problèmes détectés"""
        issues = []

        # Check 1: Remarks complets
        is_complete, reason = self.check_sentence_completeness(item.remarks_raw)
        if not is_complete:
            issues.append(f"Remarks: {reason}")

        # Check 2: Conditions complètes
        is_complete, reason = self.check_conditions_complete(item.conditions)
        if not is_complete:
            issues.append(reason)

        # Check 3: Cohérence catégorie/required
        if item.category == "A" and item.number_required != item.number_installed:
            issues.append("Cat A doit avoir required = installed")

        if issues:
            # Déclencher ré-extraction
            return False, issues

        return True, []
```

### Module 5: `mmel_variant_tree.py`

```python
class MMELVariantTree:
    """Index structuré des variantes MMEL avec contexte"""

    def __init__(self):
        # Structure: item_base -> {variant_suffix -> [items avec contextes]}
        self.tree: Dict[str, Dict[str, List[MELItemV3]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # Index secondaires
        self.by_msn: Dict[int, Set[str]] = defaultdict(set)
        self.by_operation: Dict[str, Set[str]] = defaultdict(set)

    def add_item(self, item: MELItemV3):
        """Ajoute un item à l'arbre"""
        self.tree[item.item_base][item.variant_suffix or ""].append(item)

        # Indexer par MSN
        for msn_range in item.applicable_msn:
            # Simplification: on indexe les bornes
            if msn_range.start:
                self.by_msn[msn_range.start].add(item.item_number)

        # Indexer par operation
        for op in item.operation_scope:
            self.by_operation[op].add(item.item_number)

    def find_applicable_variant(self,
                                item_base: str,
                                msn: int,
                                operation: str) -> Optional[MELItemV3]:
        """Trouve la variante applicable au contexte"""
        if item_base not in self.tree:
            return None

        candidates = []

        for suffix, items in self.tree[item_base].items():
            for item in items:
                # Vérifier MSN
                msn_match = any(r.matches(msn) for r in item.applicable_msn) \
                           or not item.applicable_msn

                # Vérifier operation
                op_match = operation in item.operation_scope \
                          or not item.operation_scope

                if msn_match and op_match:
                    candidates.append((item, suffix))

        if not candidates:
            return None

        # Priorité: variante la plus spécifique
        # (plus de conditions = plus spécifique)
        candidates.sort(key=lambda x: (
            len(x[0].applicable_msn),
            len(x[0].operation_scope)
        ), reverse=True)

        return candidates[0][0]
```

### Module 6: `tree_search_comparator.py`

```python
@dataclass
class AircraftContext:
    """Contexte de l'avion pour la comparaison"""
    msn: int
    operation_type: str  # CAT, SPO, NCO, NCC
    etops_certified: bool = False
    installed_equipment: Dict[str, int] = field(default_factory=dict)

class TreeSearchComparator:
    """Comparateur avec logique Tree-Search"""

    def __init__(self, mmel_tree: MMELVariantTree):
        self.mmel_tree = mmel_tree

    def compare_item(self,
                    mel_item: MELItemV3,
                    aircraft_context: AircraftContext) -> ComparisonResultV2:
        """Compare un item MEL avec la variante MMEL applicable"""

        # Étape 1: Trouver la variante MMEL applicable
        mmel_item = self.mmel_tree.find_applicable_variant(
            item_base=mel_item.item_base,
            msn=aircraft_context.msn,
            operation=aircraft_context.operation_type
        )

        if not mmel_item:
            return self._no_match_result(mel_item)

        # Étape 2: Comparer les attributs
        category_result = self._compare_categories(
            mel_item.category,
            mmel_item.category
        )

        quantity_result = self._compare_quantities(
            mel_item.number_required,
            mmel_item.number_required,
            aircraft_context.installed_equipment.get(mel_item.item_base, 0)
        )

        conditions_result = self._compare_conditions(
            mel_item.conditions,
            mmel_item.conditions
        )

        # Étape 3: Vérifier restrictions spéciales
        if aircraft_context.etops_certified and mmel_item.etops_restriction:
            # L'avion fait ETOPS mais la MMEL a une restriction
            # Vérifier que la MEL respecte
            pass

        # Verdict final
        return self._compute_verdict(
            category_result,
            quantity_result,
            conditions_result
        )

    def _compare_conditions(self,
                           mel_conditions: List[ApplicabilityCondition],
                           mmel_conditions: List[ApplicabilityCondition]) -> ConditionComparisonResult:
        """Compare les conditions sémantiquement"""

        mel_texts = {c.id: c.text for c in mel_conditions}
        mmel_texts = {c.id: c.text for c in mmel_conditions}

        # Conditions MMEL manquantes dans MEL = LESS_RESTRICTIVE
        missing_in_mel = set(mmel_texts.keys()) - set(mel_texts.keys())

        # Conditions MEL supplémentaires = MORE_RESTRICTIVE (ok)
        extra_in_mel = set(mel_texts.keys()) - set(mmel_texts.keys())

        # Conditions modifiées = à analyser
        modified = []
        for cid in set(mel_texts.keys()) & set(mmel_texts.keys()):
            if mel_texts[cid].lower() != mmel_texts[cid].lower():
                modified.append({
                    "id": cid,
                    "mel": mel_texts[cid],
                    "mmel": mmel_texts[cid]
                })

        return ConditionComparisonResult(
            missing_in_mel=list(missing_in_mel),
            extra_in_mel=list(extra_in_mel),
            modified=modified,
            is_less_restrictive=len(missing_in_mel) > 0
        )
```

---

## Plan d'Implémentation par Priorité

### Phase 1: Fondations (Critique)
1. **`mel_item_v3.py`** - Nouveaux modèles Pydantic
2. **`page_continuity_resolver.py`** - Fusion multi-pages
3. **Tests unitaires** pour ces modules

### Phase 2: Extraction (Haute priorité)
4. **`semantic_parser.py`** - Parser LLM
5. **`integrity_checker.py`** - Validation
6. Intégration avec Docling (mode Markdown)

### Phase 3: Comparaison (Moyenne priorité)
7. **`mmel_variant_tree.py`** - Index structuré
8. **`tree_search_comparator.py`** - Comparateur
9. **`aircraft_context.py`** - Gestion du contexte avion

### Phase 4: Pipeline (Finalisation)
10. Mise à jour de `pipeline.py`
11. Tests d'intégration avec vrais PDFs
12. Métriques de qualité (taux d'extraction, faux positifs)

---

## Métriques de Succès

| Métrique | Actuel (estimé) | Cible |
|----------|-----------------|-------|
| Continuité multi-pages | 0% | >95% |
| Complétude des Remarks | ~70% | >99% |
| Extraction MSN/Operation | ~30% | >95% |
| Faux positifs comparaison | ~15% | <2% |
| Couverture variantes MMEL | ~60% | >98% |

---

## Recommandations Immédiates

1. **Ne plus utiliser** `mel_parser_docling.py` en mode CSV/DataFrame direct
2. **Activer** le mode Markdown de Docling: `result.document.export_to_markdown()`
3. **Ajouter** une étape de pré-traitement pour fusionner les pages avant parsing
4. **Enrichir** le modèle de données avec les champs `applicable_msn` et `operation_scope`
5. **Implémenter** un cache d'embeddings pour accélérer le matching sémantique
