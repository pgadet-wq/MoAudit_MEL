# Diagnostic Docling + Granite-Docling VLM

Ce dossier contient les outils de diagnostic pour debugger le problème de markdown vide.

## Problème Identifié

Le service Docling détecte les pages du PDF (ex: 130 pages) mais retourne un markdown vide.
Le modèle Granite-Docling (vLLM) répond correctement quand testé directement.

**Hypothèse principale**: Les images des pages PDF ne sont pas transmises de Docling vers vLLM.

## Fichiers

| Fichier | Description |
|---------|-------------|
| `docling_vlm_diagnostic.py` | Script de diagnostic complet avec interception HTTP |
| `docling_service_v2.py` | Server.py amélioré avec logging détaillé |
| `create_test_pdf.py` | Générateur de PDF de test simples |

---

## Étapes de Diagnostic

### 1. Déployer la nouvelle version du service

```bash
# Depuis Windows (local)
scp tools/docling_service_v2.py root@51.159.146.199:/opt/docling-service/server.py

# Sur le serveur
ssh root@51.159.146.199 << 'EOF'
pkill -f "python3 server.py"
cd /opt/docling-service
nohup python3 server.py > /var/log/docling-service.log 2>&1 &
sleep 2
curl http://localhost:8080/health
EOF
```

### 2. Tester la chaîne vLLM directement

```bash
# Test 1: vLLM health
curl http://51.159.146.199:8000/health

# Test 2: vLLM texte seul
curl -X POST http://51.159.146.199:8080/test/vllm-text

# Test 3: vLLM avec image (uploader une image PNG/JPG)
curl -X POST http://51.159.146.199:8080/test/vllm-image \
  -F 'file=@test_image.png'
```

### 3. Tester avec un PDF simple

```bash
# Générer les PDFs de test localement
python tools/create_test_pdf.py

# Uploader et tester une page directement (bypass Docling)
curl -X POST http://51.159.146.199:8080/test/pdf-page \
  -F 'file=@test_simple.pdf' \
  -F 'page=0'

# Tester la conversion directe (sans Docling)
curl -X POST http://51.159.146.199:8080/convert-direct \
  -F 'file=@test_simple.pdf'
```

### 4. Tester la conversion Docling complète

```bash
# Conversion avec Docling (la chaîne complète)
curl -X POST http://51.159.146.199:8080/convert \
  -F 'file=@test_simple.pdf'
```

### 5. Analyser les logs

```bash
ssh root@51.159.146.199 "tail -100 /var/log/docling-service.log"

# Chercher spécifiquement les interceptions
ssh root@51.159.146.199 "grep -i 'IMAGE' /var/log/docling-service.log"
ssh root@51.159.146.199 "grep -i 'INTERCEPT' /var/log/docling-service.log"
```

---

## Interprétation des Résultats

### Cas 1: `/test/pdf-page` fonctionne mais `/convert` non

**Diagnostic**: Docling n'envoie pas les images au bon format.

**Solution possible**: Le problème est dans la configuration `ApiVlmOptions`. Vérifier:
- La version de Docling installée
- Le format attendu par `ApiVlmOptions`

```bash
ssh root@51.159.146.199 "pip show docling"
curl http://51.159.146.199:8080/debug/docling-info
```

### Cas 2: `/test/vllm-image` échoue

**Diagnostic**: vLLM ne supporte pas les images multimodales correctement.

**Solution**: Vérifier le modèle chargé et la configuration vLLM.

```bash
docker logs granite-docling 2>&1 | tail -50
curl http://51.159.146.199:8000/v1/models
```

### Cas 3: Les logs montrent des requêtes SANS images

**Diagnostic**: Docling envoie des requêtes texte-only.

**Cause probable**:
- `ApiVlmOptions` ne supporte pas `image_url` format
- Docling utilise un autre mécanisme pour les images

**Solution**: Investiguer la source Docling pour comprendre comment les images sont transmises.

---

## Version de Docling Requise

D'après la documentation Docling, le support VLM API nécessite:
- `docling >= 2.0.0`
- `enable_remote_services=True` dans `VlmPipelineOptions`

Vérifier sur le serveur:
```bash
ssh root@51.159.146.199 "pip show docling docling-core docling-ibm-models"
```

---

## Alternative: Conversion Directe (Sans Docling)

Si Docling ne fonctionne pas, utiliser l'endpoint `/convert-direct` qui:
1. Extrait les pages PDF en images avec PyMuPDF
2. Encode en base64
3. Envoie directement à vLLM
4. Retourne les DocTags bruts

```bash
curl -X POST http://51.159.146.199:8080/convert-direct \
  -F 'file=@MEL_PC-12.pdf' \
  -F 'page=-1'  # -1 = toutes les pages
```

Cela permet de valider que la chaîne PDF→vLLM fonctionne indépendamment de Docling.

---

## Scripts de Debug Sur le Serveur

### Installer le diagnostic sur le serveur

```bash
scp tools/docling_vlm_diagnostic.py root@51.159.146.199:/opt/docling-service/

ssh root@51.159.146.199 << 'EOF'
cd /opt/docling-service

# Test rapide sans PDF
python3 docling_vlm_diagnostic.py

# Test complet avec un PDF
python3 docling_vlm_diagnostic.py /path/to/test.pdf --verbose
EOF
```

### Vérifier la configuration vLLM

```bash
ssh root@51.159.146.199 "docker exec granite-docling env | grep -i model"
ssh root@51.159.146.199 "docker exec granite-docling cat /proc/1/cmdline | tr '\0' '\n'"
```

---

## Points de Vérification Finaux

| Check | Commande | Résultat Attendu |
|-------|----------|------------------|
| vLLM health | `curl :8000/health` | `{"status":"healthy"}` |
| Docling service | `curl :8080/health` | `{"status":"healthy","granite_docling":true}` |
| vLLM text | `POST :8080/test/vllm-text` | Réponse avec DocTags |
| Direct PDF→vLLM | `POST :8080/test/pdf-page` | `has_doctags: true` |
| Docling convert | `POST :8080/convert` | `markdown_length > 0` |

Si tous passent sauf le dernier, le problème est confirmé dans Docling.
