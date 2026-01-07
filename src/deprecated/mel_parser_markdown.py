#!/usr/bin/env python3
"""
MoA_MEL Parser V3 - Extraction depuis Markdown
Parse le flux Markdown pour garantir 100% du texte
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MarkdownParser")


@dataclass
class MELItemV3:
    ata_chapter: str = ""
    ata_section: str = ""
    item_base: str = ""
    item_number: str = ""
    variant_suffix: str = ""
    item_description: str = ""
    category: str = ""
    number_installed: str = ""
    number_required: str = ""
    remarks: str = ""
    operation_types: List[str] = field(default_factory=list)
    applicable_msn: str = "ALL"
    source_page: int = 0
    raw_line: str = ""
    
    def to_dict(self):
        return asdict(self)


def parse_ata_number(raw: str) -> Optional[Dict]:
    cleaned = re.sub(r'\s+', '', str(raw).strip())
    cleaned = re.sub(r'-+', '-', cleaned)
    
    patterns = [
        r'^(\d{2})-(\d{2})-(\d{2,3})([A-Z])?$',
        r'^(\d{2})-(\d{2})-(\d{2})-(\d)([A-Z])?$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            groups = match.groups()
            chapter = groups[0]
            section = groups[1]
            
            if len(groups) == 4:
                item_base = f"{chapter}-{section}-{groups[2]}"
                suffix = groups[3] or ""
            else:
                item_base = f"{chapter}-{section}-{groups[2]}-{groups[3]}"
                suffix = groups[4] or ""
            
            item_number = item_base + suffix
            
            return {
                'valid': True,
                'chapter': chapter,
                'section': section,
                'item_base': item_base,
                'item_number': item_number,
                'suffix': suffix
            }
    return None


def extract_operation_types(text: str) -> List[str]:
    patterns = [r'\(CAT\)', r'\(SPO\)', r'\(NCO\)', r'\(NCC\)', r'\(ALL\)']
    found = []
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            op = re.search(p, text, re.IGNORECASE).group().strip('()').upper()
            if op not in found:
                found.append(op)
    return found


def extract_msn(text: str) -> str:
    msn_pattern = r'MSN\s*([\d\s,\-and]+|ALL)'
    match = re.search(msn_pattern, text, re.IGNORECASE)
    if match:
        return f"MSN {match.group(1).strip()}"
    return "ALL"


def normalize_remarks(text: str) -> str:
    text = re.sub(r'\b([a-z])\.\s', r'(\1) ', text)
    text = re.sub(r'\b([a-z])\)\s', r'(\1) ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_markdown_table_row(row: str) -> List[str]:
    if not row.strip().startswith('|'):
        return []
    row = row.strip()
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|'):
        row = row[:-1]
    cells = [c.strip() for c in row.split('|')]
    return cells


def parse_markdown_document(md_content: str, doc_type: str = "MEL") -> Dict:
    logger.info(f"Parsing Markdown {doc_type}...")
    
    items = []
    current_description = ""
    current_page = 0
    
    lines = md_content.split('\n')
    
    for i, line in enumerate(lines):
        page_match = re.search(r'Page:\s*(\d+)\s*/\s*\d+', line)
        if page_match:
            current_page = int(page_match.group(1))
            continue
        
        if not line.strip().startswith('|'):
            continue
        
        if re.match(r'^\|[\s\-:]+\|', line):
            continue
        
        cells = parse_markdown_table_row(line)
        if len(cells) < 6:
            continue
        
        first_cell = cells[0].strip()
        
        # Ignorer les en-tetes et lignes continued
        if not first_cell or 'System & Sequence' in first_cell or 'cont' in first_cell.lower():
            continue
        
        # Verifier si c'est un en-tete de chapitre
        chapter_match = re.match(r'^(\d{2})\s+([A-Z\s]+)$', first_cell)
        if chapter_match:
            continue
        
        ata_info = parse_ata_number(first_cell)
        
        if ata_info:
            category_cell = cells[2].strip() if len(cells) > 2 else ""
            
            if category_cell in ['A', 'B', 'C', 'D']:
                item = MELItemV3(
                    ata_chapter=ata_info['chapter'],
                    ata_section=ata_info['section'],
                    item_base=ata_info['item_base'],
                    item_number=ata_info['item_number'],
                    variant_suffix=ata_info['suffix'],
                    item_description=current_description,
                    category=category_cell,
                    number_installed=cells[3].strip() if len(cells) > 3 else "",
                    number_required=cells[4].strip() if len(cells) > 4 else "",
                    remarks=normalize_remarks(cells[5]) if len(cells) > 5 else "",
                    source_page=current_page,
                    raw_line=line
                )
                
                full_text = f"{item.item_description} {item.remarks}"
                item.operation_types = extract_operation_types(full_text)
                item.applicable_msn = extract_msn(full_text)
                
                items.append(item)
                logger.debug(f"  Extrait: {item.item_number} Cat={item.category}")
            else:
                desc_cell = cells[1].strip() if len(cells) > 1 else ""
                if desc_cell:
                    current_description = desc_cell
        else:
            desc_match = re.match(r'(\d{2}-\d{2}-\d{2})\s+(.+)', first_cell)
            if desc_match:
                current_description = desc_match.group(2).strip()
    
    # Dedoublonner
    unique_items = {}
    for item in items:
        key = item.item_number
        if key not in unique_items:
            unique_items[key] = item
        else:
            existing = unique_items[key]
            if len(item.remarks) > len(existing.remarks):
                unique_items[key] = item
    
    items_list = list(unique_items.values())
    logger.info(f"Total items uniques: {len(items_list)}")
    
    by_chapter = {}
    for item in items_list:
        ch = item.ata_chapter
        by_chapter[ch] = by_chapter.get(ch, 0) + 1
    
    return {
        "document_type": doc_type,
        "parsing_timestamp": datetime.now().isoformat(),
        "parser": "markdown_v3",
        "statistics": {
            "total_items": len(items_list),
            "by_chapter": by_chapter
        },
        "items": [item.to_dict() for item in items_list]
    }


def convert_and_parse(pdf_path: str, doc_type: str = "MEL") -> Dict:
    from docling.document_converter import DocumentConverter
    
    logger.info(f"Conversion PDF -> Markdown: {pdf_path}")
    
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    md_content = result.document.export_to_markdown()
    
    logger.info(f"Markdown genere: {len(md_content)} caracteres")
    
    md_path = f"outputs/{doc_type.lower()}_full.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    logger.info(f"Markdown sauvegarde: {md_path}")
    
    result = parse_markdown_document(md_content, doc_type)
    result["source_pdf"] = Path(pdf_path).name
    result["markdown_file"] = md_path
    
    return result


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mel_parser_markdown.py <pdf_path> [MEL|MMEL] [output.json]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "MEL"
    output_path = sys.argv[3] if len(sys.argv) > 3 else f"outputs/parsed_{doc_type.lower()}_v3.json"
    
    result = convert_and_parse(pdf_path, doc_type)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"PARSING MARKDOWN {doc_type} TERMINE")
    print(f"{'='*60}")
    print(f"Items extraits: {result['statistics']['total_items']}")
    print(f"Par chapitre ATA:")
    for ch, count in sorted(result['statistics']['by_chapter'].items()):
        print(f"  ATA {ch}: {count} items")
    print(f"\nSauvegarde: {output_path}")
