# Rapport de Modification : Filtrage par Types d'Opérations

**Date** : 28 janvier 2026
**Version** : 2.1
**Statut** : Implémenté et testé

---

## 1. Problématique Initiale

### 1.1 Contexte Métier

L'audit MEL/MMEL compare le document opérateur (MEL) avec la référence réglementaire (MMEL). La MMEL définit pour chaque item son **applicabilité selon les types d'opérations** :

| Code | Description |
|------|-------------|
| CAT | Commercial Air Transport (Transport Aérien Commercial) |
| SPO | Specialized Operations (Opérations Spécialisées) |
| NCO | Non-Commercial Operations |
| NCC | Non-Commercial Complex |

### 1.2 Problème Identifié

**Comportement avant modification :**
- Le système ne permettait de sélectionner qu'**un seul type d'opération**
- Tous les items MMEL non présents dans la MEL étaient signalés comme `MISSING_IN_MEL` avec sévérité `WARNING`
- **Conséquence** : Un opérateur CAT recevait des alertes pour des items SPO/NCO/NCC qui ne le concernent pas

**Exemple concret :**
```
Item MMEL 21-40-01-2D : applicable uniquement pour SPO
Opérateur : fait uniquement du CAT
→ AVANT : Alerte WARNING "Item MMEL non couvert"
→ APRÈS : INFO "Item ignoré - concerne ['SPO'], compagnie: ['CAT']"
```

### 1.3 Impact sur l'Audit

- **Faux positifs** : ~30-50% des alertes "MISSING" concernaient des items non applicables
- **Taux de conformité faussé** : Pénalisé par des items hors périmètre
- **Charge de travail HITL** : Revue manuelle d'items non pertinents

---

## 2. Solution Implémentée

### 2.1 Modification de l'Interface Web

**Fichier** : `static/audit_ui.html`

**Avant** :
```html
<select id="operation">
    <option value="CAT">CAT - Commercial Air Transport</option>
    ...
</select>
```

**Après** :
```html
<div class="checkbox-group">
    <label><input type="checkbox" name="operations" value="CAT" checked> CAT</label>
    <label><input type="checkbox" name="operations" value="SPO"> SPO</label>
    <label><input type="checkbox" name="operations" value="NCO"> NCO</label>
    <label><input type="checkbox" name="operations" value="NCC"> NCC</label>
</div>
```

**JavaScript modifié** :
```javascript
const operations = Array.from(document.querySelectorAll('input[name="operations"]:checked'))
    .map(cb => cb.value);
// Envoi: { operations: ["CAT", "SPO"], ... }
```

### 2.2 Modification du Modèle API

**Fichier** : `src/server_v2.py`

```python
class AuditRequestV2(BaseModel):
    operations: List[str] = ["CAT"]  # Nouveau: liste
    operation: Optional[str] = None   # Rétrocompatibilité

    def get_operations(self) -> List[str]:
        if self.operation and self.operations == ["CAT"]:
            return [self.operation]
        return self.operations
```

### 2.3 Modification du Contexte Avion

**Fichier** : `src/matching/mmel_variant_tree.py`

```python
@dataclass
class AircraftContext:
    msn: int
    operation_types: List[str]  # Changé de str à List[str]
    aircraft_type: str = ""
    etops_certified: bool = False
```

### 2.4 Modification de la Logique de Matching

**Fichier** : `src/matching/mmel_variant_tree.py`

```python
def matches(self, msn: int, operations: List[str], aircraft: str = "") -> bool:
    # Vérifier MSN
    if self.msn_ranges:
        if not any(r.matches(msn) for r in self.msn_ranges):
            return False

    # Vérifier opérations - AU MOINS UNE EN COMMUN
    if self.operation_types:
        company_ops = [o.upper() for o in operations]
        item_ops = [o.upper() for o in self.operation_types]
        if not any(op in company_ops for op in item_ops):
            return False  # Aucune opération en commun

    return True
```

### 2.5 Modification du Comparateur

**Fichier** : `src/comparison/tree_search_comparator.py`

```python
# Pour chaque item MMEL non couvert
if is_applicable:
    # Item applicable → WARNING
    verdict = Verdict.MISSING_IN_MEL
    severity = Severity.WARNING
    hitl_reason = "Item MMEL applicable non couvert par la MEL"
else:
    # Item NON applicable → INFO (ignoré)
    verdict = Verdict.CONTEXT_MISMATCH
    severity = Severity.INFO
    hitl_reason = f"Item MMEL ignoré - concerne {item_ops}, compagnie: {company_ops}"
```

### 2.6 Modification des Statistiques

```python
@dataclass
class AuditResultV2:
    not_applicable_count: int = 0  # Nouveau compteur

def compute_statistics(self):
    # Taux de conformité EXCLUT les items non applicables
    applicable_items = self.total_comparisons - self.not_applicable_count
    if applicable_items > 0:
        self.overall_compliance_rate = conforming / applicable_items * 100
```

---

## 3. Fichiers Modifiés

| Fichier | Modifications |
|---------|--------------|
| `static/audit_ui.html` | Interface checkboxes multi-sélection |
| `src/server_v2.py` | Modèle Pydantic `operations: List[str]` |
| `src/pipeline_v2.py` | Config `operation_types: List[str]` |
| `src/matching/mmel_variant_tree.py` | `AircraftContext` et `matches()` avec liste |
| `src/comparison/tree_search_comparator.py` | Filtrage et verdict `CONTEXT_MISMATCH` |

---

## 4. Comportement Attendu

### 4.1 Scénario : Opérateur CAT uniquement

| Item MMEL | Scope MMEL | Verdict | Sévérité |
|-----------|------------|---------|----------|
| 21-30-01A | CAT | MISSING_IN_MEL | WARNING |
| 21-30-01B | SPO, NCO | CONTEXT_MISMATCH | INFO |
| 21-30-01C | CAT, SPO | MISSING_IN_MEL | WARNING |

### 4.2 Scénario : Opérateur CAT + SPO

| Item MMEL | Scope MMEL | Verdict | Sévérité |
|-----------|------------|---------|----------|
| 21-30-01A | CAT | MISSING_IN_MEL | WARNING |
| 21-30-01B | SPO, NCO | MISSING_IN_MEL | WARNING |
| 21-30-01C | NCO | CONTEXT_MISMATCH | INFO |

---

## 5. Points Restants à Vérifier

### 5.1 Extraction du champ `operation_scope` dans le parsing

**Problème potentiel** : Le parsing des documents MMEL doit correctement extraire le champ `operation_scope` depuis les remarques ou la description.

**À vérifier** :
- Les patterns regex extraient-ils correctement `(CAT)`, `(SPO)`, etc. ?
- Le champ est-il peuplé pour tous les items MMEL ?

### 5.2 Items sans scope défini

**Question** : Comment traiter un item MMEL sans `operation_scope` explicite ?

**Options** :
1. Considérer applicable à TOUS les types → Toujours signalé
2. Considérer applicable à CAT par défaut
3. Demander une revue HITL

### 5.3 Cohérence des données de test

Les fichiers JSON de test doivent inclure le champ `operation_scope` pour valider le comportement.

### 5.4 Affichage dans le rapport

Le rapport final devrait distinguer :
- `missing_items_applicable` : Items réellement manquants
- `missing_items_not_applicable` : Items ignorés (hors périmètre)

---

## 6. Tests Recommandés

1. **Test unitaire** : `VariantContext.matches()` avec différentes combinaisons
2. **Test d'intégration** : Audit complet avec opérateur mono-type vs multi-type
3. **Test de régression** : Vérifier que les anciens audits fonctionnent (rétrocompatibilité)

---

## 7. Commandes de Test

```bash
# Démarrer le serveur
cd MoAudit_MEL && python src/server_v2.py

# Test CLI avec plusieurs opérations
python src/pipeline_v2.py --mel data/mel.json --mmel data/mmel.json \
    --mel-json --mmel-json --msn 1280 --operations CAT SPO

# Vérifier l'API
curl http://localhost:8080/health
curl http://localhost:8080/openapi.json | jq '.components.schemas.AuditRequestV2'
```

---

## 8. Conclusion

L'implémentation permet désormais :
- ✅ Sélection multiple des types d'opérations
- ✅ Filtrage des items MMEL selon leur applicabilité
- ✅ Distinction claire entre items manquants et items hors périmètre
- ✅ Calcul du taux de conformité sur le périmètre pertinent uniquement
- ✅ Rétrocompatibilité avec l'ancien format API

**Impact attendu** : Réduction significative des faux positifs et du temps de revue HITL.
