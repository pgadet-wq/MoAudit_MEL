#!/usr/bin/env python3
"""
MoA_MEL - Parser MEL/MMEL basé sur Docling
Extraction fiable des tableaux avec validation ATA
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DoclingParser")


@dataclass
class MELItem:
    """Item MEL/MMEL extrait"""
    ata_chapter: str           # Ex: "21"
    ata_section: str           # Ex: "10"
    item_number: str           # Ex: "21-10-01A"
    item_description: str
    category: str              # A, B, C, D
    number_installed: str
    number_required: str
    remarks: str
    source_page: int = 0
    source_table: int = 0
    confidence: float = 1.0
    
    def to_dict(self):
        return asdict(self)
    
    @property
    def full_ata(self) -> str:
        """Format complet ATA: XX-YY-ZZ"""
        return self.item_number


def parse_ata_number(raw: str) -> dict:
    """
    Parse un numéro ATA et extrait les composants.
    Formats supportés: 21-10-01, 21-10-01A, 21-10- 01A, etc.
    """
    # Nettoyer
    cleaned = re.sub(r'\s+', '', str(raw).strip())
    
    # Pattern ATA: XX-YY-ZZ[A-Z]?
    pattern = r'^(\d{2})-(\d{2})-?(\d{2,3})([A-Z])?$'
    match = re.match(pattern, cleaned)
    
    if match:
        chapter, section, item, suffix = match.groups()
        item_num = f"{chapter}-{section}-{item.zfill(2)}"
        if suffix:
            item_num += suffix
        return {
            'valid': True,
            'chapter': chapter,
            'section': section,
            'item_number': item_num,
            'suffix': suffix or ''
        }
    
    return {'valid': False, 'raw': raw}


def extract_mel_items_from_table(df, table_idx: int = 0) -> List[MELItem]:
    """Extrait les items MEL d'un DataFrame Docling"""
    items = []
    
    # Identifier les colonnes
    cols = list(df.columns)
    n_cols = len(cols)
    
    if n_cols < 6:
        return items
    
    current_description = ""
    
    for idx, row in df.iterrows():
        values = [str(row.iloc[i]).strip() if i < len(row) else "" for i in range(n_cols)]
        
        # Colonne 0: System/Sequence number
        col0 = values[0]
        
        # Vérifier si c'est un numéro ATA
        ata_info = parse_ata_number(col0)
        
        if ata_info['valid']:
            # C'est une ligne avec un item ATA
            item_num = ata_info['item_number']
            chapter = ata_info['chapter']
            section = ata_info['section']
            
            # Colonne 1: Description (peut être vide si c'est une sous-ligne)
            desc = values[1] if len(values) > 1 else ""
            if desc and not desc.isspace():
                current_description = desc
            
            # Colonnes 2-5: Category, Installed, Required, Remarks
            category = values[2] if len(values) > 2 else ""
            installed = values[3] if len(values) > 3 else ""
            required = values[4] if len(values) > 4 else ""
            remarks = values[5] if len(values) > 5 else ""
            
            # Ne garder que si on a une catégorie (A, B, C, D)
            if category in ['A', 'B', 'C', 'D']:
                item = MELItem(
                    ata_chapter=chapter,
                    ata_section=section,
                    item_number=item_num,
                    item_description=current_description,
                    category=category,
                    number_installed=installed,
                    number_required=required,
                    remarks=remarks,
                    source_table=table_idx,
                    confidence=0.95
                )
                items.append(item)
                logger.debug(f"  Extrait: {item_num} - {current_description[:40]}... Cat={category}")
        
        elif col0 and not any(c.isdigit() for c in col0[:3]):
            # Ligne de description sans numéro ATA - possible titre de section
            pass
    
    return items


def parse_document(pdf_path: str, doc_type: str = "MEL") -> dict:
    """
    Parse un document MEL ou MMEL avec Docling.
    Retourne un dict avec les items extraits.
    """
    from docling.document_converter import DocumentConverter
    
    logger.info(f"Parsing {doc_type}: {pdf_path}")
    
    # Conversion avec Docling
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    
    # Extraire les tableaux
    tables = list(result.document.tables)
    logger.info(f"Tableaux détectés: {len(tables)}")
    
    all_items = []
    
    for i, table in enumerate(tables):
        try:
            df = table.export_to_dataframe()
            
            # Ne traiter que les tableaux avec au moins 6 colonnes (structure MEL)
            if len(df.columns) >= 6:
                items = extract_mel_items_from_table(df, table_idx=i)
                if items:
                    logger.info(f"  Tableau {i}: {len(items)} items extraits")
                    all_items.extend(items)
        except Exception as e:
            logger.warning(f"  Tableau {i}: Erreur - {e}")
    
    # Dédoublonner par item_number
    unique_items = {}
    for item in all_items:
        key = item.item_number
        if key not in unique_items:
            unique_items[key] = item
    
    items_list = list(unique_items.values())
    
    logger.info(f"Total items uniques: {len(items_list)}")
    
    # Construire le résultat
    result = {
        "document_name": Path(pdf_path).name,
        "document_type": doc_type,
        "parsing_timestamp": datetime.now().isoformat(),
        "parser": "docling",
        "statistics": {
            "total_tables": len(tables),
            "total_items": len(items_list),
            "by_chapter": {}
        },
        "items": [item.to_dict() for item in items_list]
    }
    
    # Stats par chapitre ATA
    for item in items_list:
        ch = item.ata_chapter
        result["statistics"]["by_chapter"][ch] = result["statistics"]["by_chapter"].get(ch, 0) + 1
    
    return result


def save_result(result: dict, output_path: str):
    """Sauvegarde le résultat en JSON"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info(f"Résultat sauvegardé: {output_path}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mel_parser_docling.py <pdf_path> [MEL|MMEL] [output.json]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "MEL"
    output_path = sys.argv[3] if len(sys.argv) > 3 else f"parsed_{doc_type.lower()}.json"
    
    result = parse_document(pdf_path, doc_type)
    save_result(result, output_path)
    
    print(f"\n{'='*60}")
    print(f"PARSING {doc_type} TERMINÉ")
    print(f"{'='*60}")
    print(f"Items extraits: {result['statistics']['total_items']}")
    print(f"Par chapitre ATA:")
    for ch, count in sorted(result['statistics']['by_chapter'].items()):
        print(f"  ATA {ch}: {count} items")
