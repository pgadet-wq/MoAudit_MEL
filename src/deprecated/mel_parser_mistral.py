import os
import json
import time
from mistralai import Mistral
from docling.document_converter import DocumentConverter

# Configuration de la clé API
if "MISTRAL_API_KEY" not in os.environ:
    print("❌ Erreur : Variable MISTRAL_API_KEY manquante.")
    print("Exportez votre clé : export MISTRAL_API_KEY='votre_clé'")
    exit(1)

# Initialisation du client Mistral
client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

def convert_pdf_to_markdown(pdf_path):
    """Convertit le PDF en Markdown structuré via Docling"""
    print(f"📄 Conversion du PDF en Markdown avec Docling : {pdf_path}...")
    try:
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        # On exporte en markdown qui préserve bien les tableaux pour les LLM
        return result.document.export_to_markdown()
    except Exception as e:
        print(f"❌ Erreur critique Docling : {e}")
        return None

def repair_truncated_json(json_str):
    """Tente de réparer un JSON coupé (copié de la V7)"""
    print("   🔧 Tentative de réparation du JSON tronqué...")
    json_str = json_str.strip()
    
    # Nettoyage des balises markdown code si présentes
    if json_str.startswith("```json"):
        json_str = json_str[7:]
    if json_str.endswith("```"):
        json_str = json_str[:-3]
    
    last_item_end = json_str.rfind('}')
    if last_item_end == -1: return {"items": []}
    
    valid_part = json_str[:last_item_end+1]
    repaired = valid_part
    if not repaired.endswith(']'): repaired += ']'
    if not repaired.endswith('}'): repaired += '}'
    
    try:
        return json.loads(repaired)
    except:
        return {"items": []}

def generate_with_retry(content, retries=3):
    """Appel API Mistral avec Retry"""
    model = "mistral-large-latest" # Le meilleur modèle pour le raisonnement complexe
    
    for attempt in range(retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[
                    {"role": "user", "content": content}
                ],
                response_format={"type": "json_object"}, # Force le JSON strict
                temperature=0.0
            )
            return response.choices[0].message.content
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                wait_time = 10 * (attempt + 1)
                print(f"   ⚠️ Rate Limit Mistral. Pause {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"   ❌ Erreur API : {e}")
                raise e
    raise Exception("Abandon après retries")

def parse_with_mistral(pdf_path, doc_type="MEL"):
    print(f"🚀 Démarrage Parser Mistral Large ({doc_type})...")

    # 1. Conversion préalable (Local - Rapide et Gratuit)
    markdown_content = convert_pdf_to_markdown(pdf_path)
    if not markdown_content:
        return None

    # 2. Découpage par lots ATA (Méthodologie V7 conservée)
    ata_batches = [
        ("00", "22"), 
        ("23", "25"), 
        ("26", "29"), 
        ("30", "32"), 
        ("33", "34"), # Le lot critique
        ("35", "99")
    ]

    all_items = []
    
    for start_ata, end_ata in ata_batches:
        print(f"\n📦 Extraction Lot ATA {start_ata}-{end_ata}...")
        
        # PROMPT V7 ADAPTÉ POUR MISTRAL (Même logique stricte)
        prompt = f"""
        Tu es un expert en audit aéronautique. Analyse le document technique ci-dessous (format Markdown).
        
        TACHE : Extrais UNIQUEMENT les items des chapitres ATA {start_ata} à {end_ata}.
        
        DOCUMENT (Extrait Markdown) :
        {markdown_content[:100000]} 
        (Note: Le contexte est tronqué pour l'input si trop long, mais Mistral Large gère 128k tokens)

        ⚡ RÈGLE D'OR : L'IDENTIFIANT ("ITEM") DÉFINIT L'OBJET ⚡
        1. NOUVEL ID (ex: 34-40-01A -> 34-40-01B) = NOUVEL OBJET JSON. Ne fusionne jamais deux IDs différents.
        2. MEME ID = CONTINUITÉ. Fusionne le texte si le tableau continue sur la page suivante avec le même ID.
        3. REMARKS : Capture tout le texte, conditions (a), (b) incluses.

        Format de sortie JSON attendu :
        {{
            "items": [
                {{
                    "item_number": "XX-YY-ZZA", 
                    "ata_chapter": "XX",
                    "category": "A/B/C/D", 
                    "number_installed": "string",
                    "number_required": "string",
                    "remarks": "string", 
                    "item_description": "string"
                }}
            ]
        }}
        """
        # Note: Pour optimiser, on pourrait filtrer le markdown_content pour n'envoyer que les pages concernées, 
        # mais Mistral Large a un grand contexte, on tente l'envoi global ou on tronque si besoin.
        # Ici on envoie tout car le Markdown est moins lourd que le PDF binaire.

        try:
            json_response = generate_with_retry(prompt)
            
            # Traitement réponse
            try:
                batch_data = json.loads(json_response)
            except:
                batch_data = repair_truncated_json(json_response)
            
            items = batch_data.get("items", [])
            print(f"   ✅ {len(items)} items extraits.")
            all_items.extend(items)
            
        except Exception as e:
            print(f"   ⚠️ Erreur lot {start_ata}-{end_ata}: {e}")

    # 3. Sauvegarde
    final_output = {
        "document_name": os.path.basename(pdf_path),
        "parser": "mistral-large-docling-v1",
        "statistics": {"total_items": len(all_items)},
        "items": all_items
    }
    
    return final_output

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python src/mel_parser_mistral.py <pdf> <type> <output>")
        sys.exit(1)
        
    pdf = sys.argv[1]
    dtype = sys.argv[2]
    out = sys.argv[3]
    
    result = parse_with_mistral(pdf, dtype)
    if result:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ Terminé : {out}")
