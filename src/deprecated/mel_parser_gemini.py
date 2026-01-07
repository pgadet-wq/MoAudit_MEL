import os
import json
import time
import re
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

if "GOOGLE_API_KEY" not in os.environ:
    print("❌ Erreur : Variable GOOGLE_API_KEY manquante.")
    exit(1)

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

def repair_truncated_json(json_str):
    """Tente de réparer un JSON coupé brutalement à la fin"""
    print("   🔧 Tentative de réparation du JSON tronqué...")
    json_str = json_str.strip()
    
    # Trouver la dernière fermeture d'objet valide
    last_item_end = json_str.rfind('}')
    if last_item_end == -1: return {"items": []}
    
    # Garder la partie valide
    valid_part = json_str[:last_item_end+1]
    
    # Refermer proprement
    repaired = valid_part
    if not repaired.endswith(']'): repaired += ']'
    if not repaired.endswith('}'): repaired += '}'
    
    try:
        return json.loads(repaired)
    except:
        # Essai brutal
        try:
            return json.loads(valid_part + "]}")
        except:
            print("   ❌ Réparation échouée.")
            return None

def generate_with_retry(model, content, retries=3):
    """Gère les appels API avec retry automatique pour les erreurs 429"""
    for attempt in range(retries):
        try:
            return model.generate_content(
                content,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }
            )
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait_time = 30 * (attempt + 1) # Attente progressive : 30s, 60s, 90s
                print(f"   ⚠️ Quota atteint (429). Pause de {wait_time}s avant retry...")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("Abandon après 3 tentatives (Quota ou Erreur API)")

def parse_pdf_in_batches(pdf_path, doc_type="MEL"):
    # On reste sur gemini-2.5-flash (ou passez à gemini-1.5-flash si le quota persiste)
    MODEL_NAME = "gemini-2.5-flash"
    
    print(f"🚀 Démarrage de l'analyse par lots ({doc_type}) avec {MODEL_NAME}...")

    print("   Upload du fichier...")
    sample_file = genai.upload_file(path=pdf_path, display_name=f"{doc_type} Document")
    
    while sample_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(2)
        sample_file = genai.get_file(sample_file.name)
    print(f"\n   Fichier prêt : {sample_file.uri}")

    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.0,
        }
    )

    # Découpage optimisé pour réduire la taille des réponses (éviter Unterminated string)
    ata_batches = [
        ("00", "22"), # General, Air Cond, Auto Flight
        ("23", "25"), # Comms, Elec, Equip
        ("26", "29"), # Fire, Controls, Fuel, Hydro
        ("30", "32"), # Ice, Instruments, Gear
        ("33", "34"), # Lights, Navigation (Critique & Gros volume)
        ("35", "99")  # Oxygen et reste
    ]

    all_items = []
    
    for start_ata, end_ata in ata_batches:
        print(f"\n📦 Extraction du lot ATA {start_ata} à {end_ata}...")
        
        # PROMPT V6 - LOGIQUE DE RUPTURE STRICTE
        prompt = f"""
        RÔLE : Tu es un parser de données aéronautiques ultra-rigoureux.
        DOCUMENT : Extrais les items MMEL/MEL des chapitres ATA {start_ata} à {end_ata}.

        ⚡ RÈGLE D'OR : L'IDENTIFIANT ("ITEM") EST ROI ⚡
        
        ANALYSE SÉQUENTIELLE OBLIGATOIRE :
        1. Lis le document ligne par ligne.
        2. À chaque ligne, regarde la première colonne ("ITEM" ou "System & Sequence numbers").
        
        CAS 1 : NOUVEL IDENTIFIANT DÉTECTÉ (ex: passage de 34-40-01A à 34-40-01B)
           -> C'est une RUPTURE TOTALE.
           -> Tu dois CRÉER un nouvel objet JSON.
           -> INTERDICTION ABSOLUE de mélanger les données (Catégorie, Remarks) de l'item précédent avec celui-ci.
           -> Même si la page précédente disait "(continued)", un nouvel ID annule la continuité.
        
        CAS 2 : MÊME IDENTIFIANT ou IDENTIFIANT VIDE
           -> C'est une CONTINUITÉ.
           -> Tu ajoutes le texte à l'item en cours de lecture.
           -> C'est ici (et seulement ici) que tu gères les tableaux sur plusieurs pages.

        ATTENTION AU PIÈGE "34-40-01" :
        - 34-40-01A et 34-40-01B sont DEUX items distincts.
        - Si 34-40-01A est en bas de page 1 et 34-40-01B en haut de page 2 : NE LES FUSIONNE PAS.
        
        EXTRACTION DES REMARKS :
        - Capture le texte EXACT. 
        - Ne tronque pas les conditions (a), (b)...

        SCHEMA JSON DE SORTIE :
        {{
            "items": [
                {{
                    "item_number": "XX-YY-ZZA", 
                    "ata_chapter": "XX",
                    "item_description": "string",
                    "category": "A/B/C/D", 
                    "number_installed": "string",
                    "number_required": "string",
                    "remarks": "string", 
                    "operation_types": ["string"],
                    "applicable_msn": "string"
                }}
            ]
        }}
        """

        try:
            # Appel API avec gestion du retry 429
            response = generate_with_retry(model, [sample_file, prompt])
            
            # Parsing et Réparation
            try:
                batch_data = json.loads(response.text)
            except json.JSONDecodeError:
                batch_data = repair_truncated_json(response.text)
            
            if batch_data and "items" in batch_data:
                items = batch_data.get("items", [])
                print(f"   ✅ {len(items)} items trouvés.")
                all_items.extend(items)
            else:
                print("   ⚠️ Aucun item trouvé ou erreur JSON fatale sur ce lot.")

            # Pause préventive pour ménager le quota
            time.sleep(5)

        except Exception as e:
            print(f"   ❌ Erreur critique sur le lot {start_ata}-{end_ata} : {e}")

    print(f"\n📊 TOTAL : {len(all_items)} items extraits.")
    
    final_output = {
        "document_name": os.path.basename(pdf_path),
        "document_type": doc_type,
        "parser": f"{MODEL_NAME}-strict-v7",
        "statistics": {
            "total_items": len(all_items)
        },
        "items": all_items
    }
    
    return final_output

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python src/mel_parser_gemini.py <pdf> <type> <output>")
        sys.exit(1)

    pdf = sys.argv[1]
    dtype = sys.argv[2]
    out = sys.argv[3]
    
    result = parse_pdf_in_batches(pdf, dtype)
    if result:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ Sauvegarde terminée : {out}")
