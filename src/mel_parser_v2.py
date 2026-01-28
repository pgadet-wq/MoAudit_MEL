#!/usr/bin/env python3
"""
MoA_MEL Parser V2 - Extraction enrichie avec qualificateurs
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ParserV2")


@dataclass
class MELItemV2:
    """Item MEL/MMEL enrichi avec qualificateurs"""
    # Identifiants
    ata_chapter: str = ""
    ata_section: str = ""
    item_base: str = ""          # Sans suffixe: 21-30-01
    item_number: str = ""        # Avec suffixe: 21-30-01D
    variant_suffix: str = ""     # D
    
    # Données standard
    item_description: str = ""
    category: str = ""           # A, B, C, D
    number_installed: str = ""   # "1", "-", "As installed"
    number_required: str = ""    # "0", "1", "-"
    remarks: str = ""
    
    # Qualificateurs
    operation_types: List[str] = field(default_factory=list)  # CAT, SPO, NCO
    applicable_msn: str = "ALL"
    rectification_interval: str = ""
    
    # Métadonnées
    source_table: int = 0
    source_page: int = 0
    
    # Flags HITL
    needs_hitl: bool = False
    hitl_reasons: List[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self):
        return asdict(self)


def parse_ata_number(raw: str) -> dict:
    """Parse un numéro ATA avec extraction du suffixe"""
    cleaned = re.sub(r'\s+', '', str(raw).strip())
    
    # Pattern: XX-YY-ZZ ou XX-YY-ZZA
    pattern = r'^(\d{2})-(\d{2})-?(\d{2,3})([A-Z])?$'
    match = re.match(pattern, cleaned)
    
    if match:
        chapter, section, item, suffix = match.groups()
        item_base = f"{chapter}-{section}-{item.zfill(2)}"
        item_full = item_base + (suffix or "")
        return {
            'valid': True,
            'chapter': chapter,
            'section': section,
            'item_base': item_base,
            'item_number': item_full,
            'suffix': suffix or ''
        }
    return {'valid': False, 'raw': raw}


def extract_operation_types(text: str) -> List[str]:
    """
    Extrait les types d'exploitation du texte.

    Patterns reconnus:
    - Avec parenthèses: (CAT), (SPO), (NCO), (NCC)
    - Sans parenthèses: CAT operations, SPO/NCO, etc.
    - Mots-clés: COMMERCIAL, PRIVATE, CARGO
    """
    patterns = {
        # Avec parenthèses
        r'\(CAT\)': "CAT",
        r'\(SPO\)': "SPO",
        r'\(NCO\)': "NCO",
        r'\(NCC\)': "NCC",
        r'\(ALL\)': "ALL",
        # Sans parenthèses (mots complets)
        r'\bCAT\b': "CAT",
        r'\bSPO\b': "SPO",
        r'\bNCO\b': "NCO",
        r'\bNCC\b': "NCC",
        # Mots-clés additionnels
        r'\bCOMMERCIAL\b': "CAT",
        r'\bPRIVATE\b': "NCC",
        r'\bCARGO\b': "CAT",
    }
    found = []
    for pattern, op_type in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            if op_type not in found:
                found.append(op_type)
    return found


def extract_msn_range(text: str) -> str:
    """Extrait les MSN applicables"""
    # Patterns: MSN 101-544, MSN 101, 102, 103, MSN ALL
    msn_pattern = r'MSN\s*([\d\s,\-]+|ALL)'
    match = re.search(msn_pattern, text, re.IGNORECASE)
    if match:
        return f"MSN {match.group(1).strip()}"
    return "ALL"


def parse_installed_required(installed_str: str, required_str: str) -> Tuple[str, str, List[str]]:
    """
    Parse Number Installed et Number Required avec détection des cas spéciaux
    Retourne: (installed, required, hitl_reasons)
    """
    hitl = []
    
    # Nettoyer
    inst = str(installed_str).strip() if installed_str else "-"
    req = str(required_str).strip() if required_str else "-"
    
    # Cas spéciaux pour installed
    if inst in ['-', '', 'nan', 'None', 'As installed', 'AR']:
        inst = "-"
    
    # Cas spéciaux pour required
    if req in ['-', '', 'nan', 'None']:
        req = "-"
    
    return inst, req, hitl


def extract_mel_items_v2(df, table_idx: int = 0) -> List[MELItemV2]:
    """Extraction enrichie des items MEL"""
    items = []
    cols = list(df.columns)
    n_cols = len(cols)
    
    if n_cols < 6:
        return items
    
    current_description = ""
    current_ops = []
    current_msn = "ALL"
    
    for idx, row in df.iterrows():
        values = [str(row.iloc[i]).strip() if i < len(row) else "" for i in range(n_cols)]
        
        col0 = values[0]  # Item number
        ata_info = parse_ata_number(col0)
        
        if ata_info['valid']:
            # Colonnes standard
            desc = values[1] if len(values) > 1 else ""
            category = values[2] if len(values) > 2 else ""
            installed = values[3] if len(values) > 3 else ""
            required = values[4] if len(values) > 4 else ""
            remarks = values[5] if len(values) > 5 else ""
            
            # Mise à jour description
            if desc and not desc.isspace() and not desc.startswith('('):
                current_description = desc
            
            # Extraire qualificateurs de la description/remarks
            full_text = f"{desc} {remarks}"
            ops = extract_operation_types(full_text)
            msn = extract_msn_range(full_text)
            
            if ops:
                current_ops = ops
            if msn != "ALL":
                current_msn = msn
            
            # Parser installed/required
            inst_clean, req_clean, inst_hitl = parse_installed_required(installed, required)
            
            # Construire l'item
            if category in ['A', 'B', 'C', 'D']:
                hitl_reasons = list(inst_hitl)
                needs_hitl = False
                
                # Règles HITL
                if current_ops:
                    hitl_reasons.append(f"Confirmer type exploitation: {', '.join(current_ops)}")
                    needs_hitl = True
                if current_msn != "ALL":
                    hitl_reasons.append(f"Confirmer applicabilité: {current_msn}")
                    needs_hitl = True
                if inst_clean == "-":
                    hitl_reasons.append("Number Installed non spécifié - vérifier configuration")
                    needs_hitl = True
                
                item = MELItemV2(
                    ata_chapter=ata_info['chapter'],
                    ata_section=ata_info['section'],
                    item_base=ata_info['item_base'],
                    item_number=ata_info['item_number'],
                    variant_suffix=ata_info['suffix'],
                    item_description=current_description,
                    category=category,
                    number_installed=inst_clean,
                    number_required=req_clean,
                    remarks=remarks,
                    operation_types=current_ops.copy() if current_ops else [],
                    applicable_msn=current_msn,
                    source_table=table_idx,
                    needs_hitl=needs_hitl,
                    hitl_reasons=hitl_reasons,
                    confidence=0.9 if needs_hitl else 0.95
                )
                items.append(item)
    
    return items


def parse_document_v2(pdf_path: str, doc_type: str = "MEL") -> dict:
    """Parse un document avec le parser V2 enrichi"""
    from docling.document_converter import DocumentConverter
    
    logger.info(f"Parsing V2 {doc_type}: {pdf_path}")
    
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    tables = list(result.document.tables)
    logger.info(f"Tableaux détectés: {len(tables)}")
    
    all_items = []
    
    for i, table in enumerate(tables):
        try:
            df = table.export_to_dataframe()
            if len(df.columns) >= 6:
                items = extract_mel_items_v2(df, table_idx=i)
                if items:
                    logger.info(f"  Tableau {i}: {len(items)} items")
                    all_items.extend(items)
        except Exception as e:
            logger.warning(f"  Tableau {i}: Erreur - {e}")
    
    # Dédoublonner
    unique = {}
    for item in all_items:
        key = item.item_number
        if key not in unique:
            unique[key] = item
        else:
            # Fusionner les infos si même item
            existing = unique[key]
            if item.operation_types:
                existing.operation_types = list(set(existing.operation_types + item.operation_types))
    
    items_list = list(unique.values())
    logger.info(f"Total items uniques: {len(items_list)}")
    
    # Stats
    by_chapter = {}
    needs_hitl_count = 0
    for item in items_list:
        by_chapter[item.ata_chapter] = by_chapter.get(item.ata_chapter, 0) + 1
        if item.needs_hitl:
            needs_hitl_count += 1
    
    return {
        "document_name": Path(pdf_path).name,
        "document_type": doc_type,
        "parsing_timestamp": datetime.now().isoformat(),
        "parser": "docling_v2",
        "statistics": {
            "total_tables": len(tables),
            "total_items": len(items_list),
            "needs_hitl": needs_hitl_count,
            "by_chapter": by_chapter
        },
        "items": [item.to_dict() for item in items_list]
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mel_parser_v2.py <pdf_path> [MEL|MMEL] [output.json]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "MEL"
    output_path = sys.argv[3] if len(sys.argv) > 3 else f"parsed_{doc_type.lower()}_v2.json"
    
    result = parse_document_v2(pdf_path, doc_type)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"PARSING V2 {doc_type} TERMINÉ")
    print(f"{'='*60}")
    print(f"Items extraits: {result['statistics']['total_items']}")
    print(f"Items nécessitant HITL: {result['statistics']['needs_hitl']}")
    print(f"Sauvegardé: {output_path}")
