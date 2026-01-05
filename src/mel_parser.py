"""
MoA_MEL_Parser - Extraction de tableaux MEL/MMEL depuis PDF
============================================================
Utilise Pixtral 12B (VLM Mistral) pour extraire les données structurées
des documents MEL, MMEL et CS-MMEL au format tabulaire.
"""

import json
import base64
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_Parser")

@dataclass
class MELItem:
    """Structure d'un item MEL/MMEL"""
    # Identifiants
    ata_chapter: str
    item_number: str
    sequence_number: Optional[str] = None
    
    # Description
    item_description: str = ""
    system_description: str = ""
    
    # Catégorie et dispatch
    category: str = ""  # A, B, C, D ou "-"
    repair_interval: str = ""
    
    # Quantités
    number_installed: str = ""
    number_required: str = ""
    
    # Conditions
    remarks: str = ""
    exceptions: str = ""
    provisos: str = ""
    
    # Métadonnées
    source_document: str = ""
    source_page: int = 0
    extraction_confidence: float = 0.0
    content_hash: str = ""
    
    # Flags
    requires_hitl_review: bool = False
    hitl_reason: str = ""
    
    def __post_init__(self):
        """Calcul du hash de contenu"""
        content = f"{self.ata_chapter}|{self.item_number}|{self.item_description}|{self.category}"
        self.content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class ParsingResult:
    """Résultat du parsing d'un document"""
    document_name: str
    document_type: str  # MEL, MMEL, CS-MMEL
    total_pages: int
    items: List[MELItem]
    parsing_timestamp: str
    
    # Statistiques
    total_items: int = 0
    high_confidence_items: int = 0
    low_confidence_items: int = 0
    hitl_required_items: int = 0
    
    # Erreurs
    errors: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        self.errors = self.errors or []
        self.total_items = len(self.items)
        self.high_confidence_items = sum(1 for i in self.items if i.extraction_confidence >= 0.85)
        self.low_confidence_items = sum(1 for i in self.items if i.extraction_confidence < 0.85)
        self.hitl_required_items = sum(1 for i in self.items if i.requires_hitl_review)


class MistralVLMClient:
    """Client pour l'API Mistral Pixtral (VLM)"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"
        self.model = "pixtral-12b-2409"
        
    def _encode_image(self, image_path: str) -> str:
        """Encode une image en base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def _encode_pdf_page(self, pdf_path: str, page_num: int) -> str:
        """Extrait et encode une page PDF en image"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            page = doc[page_num]
            # Rendu haute résolution
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom pour meilleure qualité
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            doc.close()
            return base64.b64encode(img_bytes).decode("utf-8")
        except ImportError:
            logger.error("PyMuPDF non installé. Installer avec: pip install pymupdf")
            raise
    
    def extract_mel_table(self, image_base64: str, page_num: int) -> Dict[str, Any]:
        """Extrait les données MEL/MMEL d'une image de page"""
        import requests
        
        prompt = """Analyze this MEL/MMEL document page and extract ALL equipment items in a structured JSON format.

For each item found, extract:
- ata_chapter: The ATA chapter number (e.g., "21", "24-10", "32-40")
- item_number: The specific item number or code
- sequence_number: Sub-item sequence if present (e.g., "-1", "-2")
- item_description: Full description of the equipment
- category: Dispatch category (A, B, C, D, or "-" if not specified)
- repair_interval: Time limit for repair (e.g., "120 days", "A check")
- number_installed: Number of items installed on aircraft
- number_required: Minimum number required for dispatch
- remarks: Any operational remarks, conditions, or (O) (M) annotations
- exceptions: Any exceptions or special conditions
- provisos: Additional provisos or notes

Return a JSON array with this exact structure:
{
  "items": [
    {
      "ata_chapter": "string",
      "item_number": "string", 
      "sequence_number": "string or null",
      "item_description": "string",
      "category": "string",
      "repair_interval": "string",
      "number_installed": "string",
      "number_required": "string",
      "remarks": "string",
      "exceptions": "string",
      "provisos": "string",
      "confidence": 0.95
    }
  ],
  "page_type": "mel_table|title_page|text_page|other",
  "extraction_notes": "string"
}

If no MEL items are found on this page (title page, text-only, etc.), return empty items array.
Be extremely precise with numbers and categories - aviation safety depends on accuracy."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.error(f"Erreur API Pixtral page {page_num}: {e}")
            return {"items": [], "page_type": "error", "extraction_notes": str(e)}


class MELParser:
    """Parser principal pour documents MEL/MMEL"""
    
    def __init__(self, api_key: str, confidence_threshold: float = 0.85, hitl_threshold: float = 0.70):
        self.vlm_client = MistralVLMClient(api_key)
        self.confidence_threshold = confidence_threshold
        self.hitl_threshold = hitl_threshold
        
    def detect_document_type(self, filename: str, first_page_text: str = "") -> str:
        """Détecte le type de document (MEL, MMEL, CS-MMEL)"""
        filename_lower = filename.lower()
        text_lower = first_page_text.lower()
        
        if "cs-mmel" in filename_lower or "cs-mmel" in text_lower:
            return "CS-MMEL"
        elif "mmel" in filename_lower or "master minimum equipment" in text_lower:
            return "MMEL"
        elif "mel" in filename_lower or "minimum equipment list" in text_lower:
            return "MEL"
        else:
            return "UNKNOWN"
    
    def parse_pdf(self, pdf_path: str, start_page: int = 0, end_page: int = None) -> ParsingResult:
        """Parse un document PDF MEL/MMEL complet"""
        import fitz
        
        pdf_path = Path(pdf_path)
        logger.info(f"Parsing document: {pdf_path.name}")
        
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        end_page = end_page or total_pages
        
        # Détection du type de document
        first_page_text = doc[0].get_text() if total_pages > 0 else ""
        doc_type = self.detect_document_type(pdf_path.name, first_page_text)
        logger.info(f"Document type detected: {doc_type}")
        
        all_items = []
        errors = []
        
        for page_num in range(start_page, min(end_page, total_pages)):
            logger.info(f"Processing page {page_num + 1}/{total_pages}")
            
            try:
                # Encoder la page en image
                image_b64 = self.vlm_client._encode_pdf_page(str(pdf_path), page_num)
                
                # Extraction via VLM
                result = self.vlm_client.extract_mel_table(image_b64, page_num)
                
                # Traitement des items extraits
                for item_data in result.get("items", []):
                    confidence = item_data.pop("confidence", 0.8)
                    
                    # Création de l'item MEL
                    mel_item = MELItem(
                        ata_chapter=str(item_data.get("ata_chapter", "")).strip(),
                        item_number=str(item_data.get("item_number", "")).strip(),
                        sequence_number=item_data.get("sequence_number"),
                        item_description=str(item_data.get("item_description", "")).strip(),
                        category=str(item_data.get("category", "")).strip().upper(),
                        repair_interval=str(item_data.get("repair_interval", "")).strip(),
                        number_installed=str(item_data.get("number_installed", "")).strip(),
                        number_required=str(item_data.get("number_required", "")).strip(),
                        remarks=str(item_data.get("remarks", "")).strip(),
                        exceptions=str(item_data.get("exceptions", "")).strip(),
                        provisos=str(item_data.get("provisos", "")).strip(),
                        source_document=pdf_path.name,
                        source_page=page_num + 1,
                        extraction_confidence=confidence
                    )
                    
                    # Vérification HITL
                    if confidence < self.hitl_threshold:
                        mel_item.requires_hitl_review = True
                        mel_item.hitl_reason = f"Low confidence: {confidence:.2f}"
                    elif confidence < self.confidence_threshold:
                        mel_item.requires_hitl_review = True
                        mel_item.hitl_reason = f"Medium confidence: {confidence:.2f}"
                    
                    # Validation basique
                    if mel_item.ata_chapter and mel_item.item_description:
                        all_items.append(mel_item)
                    else:
                        errors.append({
                            "page": page_num + 1,
                            "error": "Missing required fields",
                            "data": item_data
                        })
                        
            except Exception as e:
                logger.error(f"Error processing page {page_num + 1}: {e}")
                errors.append({
                    "page": page_num + 1,
                    "error": str(e)
                })
        
        doc.close()
        
        result = ParsingResult(
            document_name=pdf_path.name,
            document_type=doc_type,
            total_pages=total_pages,
            items=all_items,
            parsing_timestamp=datetime.now().isoformat(),
            errors=errors
        )
        
        logger.info(f"Parsing complete: {result.total_items} items, {result.hitl_required_items} require HITL review")
        return result
    
    def save_parsing_result(self, result: ParsingResult, output_path: str) -> str:
        """Sauvegarde le résultat du parsing en JSON"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "document_name": result.document_name,
            "document_type": result.document_type,
            "total_pages": result.total_pages,
            "parsing_timestamp": result.parsing_timestamp,
            "statistics": {
                "total_items": result.total_items,
                "high_confidence": result.high_confidence_items,
                "low_confidence": result.low_confidence_items,
                "hitl_required": result.hitl_required_items
            },
            "items": [item.to_dict() for item in result.items],
            "errors": result.errors
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Parsing result saved to: {output_path}")
        return str(output_path)
    
    def generate_hitl_log(self, result: ParsingResult, log_path: str) -> str:
        """Génère le fichier de log HITL pour review manuel"""
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        hitl_items = [item for item in result.items if item.requires_hitl_review]
        
        log_data = {
            "document": result.document_name,
            "generated_at": datetime.now().isoformat(),
            "total_items_for_review": len(hitl_items),
            "items": []
        }
        
        for item in hitl_items:
            log_data["items"].append({
                "id": f"{item.ata_chapter}-{item.item_number}",
                "page": item.source_page,
                "confidence": item.extraction_confidence,
                "reason": item.hitl_reason,
                "extracted_data": {
                    "ata_chapter": item.ata_chapter,
                    "item_number": item.item_number,
                    "description": item.item_description,
                    "category": item.category,
                    "remarks": item.remarks
                },
                "validation": {
                    "status": "PENDING",  # PENDING, APPROVED, CORRECTED, REJECTED
                    "corrected_data": None,
                    "validated_by": None,
                    "validated_at": None,
                    "comments": None
                }
            })
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"HITL log generated: {log_path} ({len(hitl_items)} items)")
        return str(log_path)


# Pour les tests sans API (mock data)
def create_mock_parsing_result(doc_name: str, doc_type: str) -> ParsingResult:
    """Crée un résultat de parsing fictif pour les tests"""
    mock_items = [
        MELItem(
            ata_chapter="21",
            item_number="21-51-01",
            item_description="Air Conditioning Pack",
            category="C",
            repair_interval="10 days",
            number_installed="2",
            number_required="1",
            remarks="(O) May be inoperative provided remaining pack operates normally",
            source_document=doc_name,
            source_page=15,
            extraction_confidence=0.95
        ),
        MELItem(
            ata_chapter="24",
            item_number="24-10-01",
            item_description="Main Battery",
            category="A",
            repair_interval="",
            number_installed="1",
            number_required="1",
            remarks="",
            source_document=doc_name,
            source_page=22,
            extraction_confidence=0.92
        ),
        MELItem(
            ata_chapter="32",
            item_number="32-40-01",
            item_description="Nose Wheel Steering System",
            category="C",
            repair_interval="3 days",
            number_installed="1",
            number_required="0",
            remarks="(M) Maintenance actions required. May be inoperative provided aircraft is not operated on contaminated runway",
            source_document=doc_name,
            source_page=45,
            extraction_confidence=0.78,
            requires_hitl_review=True,
            hitl_reason="Medium confidence: 0.78"
        )
    ]
    
    return ParsingResult(
        document_name=doc_name,
        document_type=doc_type,
        total_pages=120,
        items=mock_items,
        parsing_timestamp=datetime.now().isoformat()
    )


if __name__ == "__main__":
    import sys
    
    # Test avec données mock si pas d'API key
    api_key = sys.argv[1] if len(sys.argv) > 1 else ""
    
    if not api_key:
        print("Mode test avec données mock")
        result = create_mock_parsing_result("test_mel.pdf", "MEL")
        print(f"Items parsés: {result.total_items}")
        print(f"HITL requis: {result.hitl_required_items}")
        for item in result.items:
            print(f"  - {item.ata_chapter} | {item.item_number} | {item.category} | {item.extraction_confidence:.2f}")
    else:
        print("Mode production avec API Mistral")
        parser = MELParser(api_key)
        # parser.parse_pdf("path/to/mel.pdf")
