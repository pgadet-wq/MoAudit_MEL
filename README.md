# MoA_MEL - Audit MEL/MMEL Automatisé

## 🎯 Vue d'ensemble

**MoA_MEL** est un prototype d'audit automatisé comparant les documents MEL opérateur avec les MMEL réglementaires.

### Objectif
Détecter les écarts entre le MEL d'un opérateur et la MMEL de référence, en identifiant les cas critiques où le MEL serait **moins restrictif**.

## 🚀 Démarrage Rapide

### Installation

```bash
cd moa_mel_poc
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

```env
# .env
MISTRAL_API_KEY=your_api_key_here
PORT=8080
```

### Lancer le serveur

```bash
cd src
python server.py
```

### Test avec données exemple

```bash
python pipeline.py \
  --mel ../data/sample_mel.json \
  --mmel ../data/sample_mmel.json \
  --mel-json --mmel-json
```

## 📁 Structure

```
moa_mel_poc/
├── src/
│   ├── mel_parser.py     # Extraction PDF (Pixtral VLM)
│   ├── mel_indexer.py    # Matching exact + sémantique
│   ├── mel_comparator.py # Comparaison et verdicts
│   ├── pipeline.py       # Orchestration
│   ├── server.py         # API FastAPI
│   └── dashboard.jsx     # Interface React
├── workflows/
│   └── moa_mel_audit_pipeline.json  # Workflow n8n
├── data/                 # Données test
└── outputs/             # Résultats
```

## 🔄 Pipeline

1. **Parser** → Extraction tableaux PDF via Pixtral 12B
2. **Indexer** → Matching ATA + embeddings sémantiques
3. **Comparator** → Génération verdicts et écarts
4. **Dashboard** → Visualisation des résultats

## 📊 Verdicts

| Verdict | Sévérité | Description |
|---------|----------|-------------|
| COMPLIANT | Info | MEL = MMEL |
| MORE_RESTRICTIVE | Info | MEL plus strict |
| **LESS_RESTRICTIVE** | **Critical** | MEL moins strict (**ÉCART**) |
| MISSING_IN_MEL | Warning | Item MMEL absent |

## 🔗 API

```bash
# Démarrer un audit
POST /api/audit/start
{
  "mel_path": "path/to/mel.json",
  "mmel_path": "path/to/mmel.json"
}

# Statut
GET /api/audit/status/{job_id}

# Résultat
GET /api/audit/result/{job_id}
```

## 🖥️ Dashboard

Accès : `http://localhost:8080/dashboard`

---

**MoA_MEL PoC** - Mistral AI 🇫🇷 | Scaleway 🇪🇺
