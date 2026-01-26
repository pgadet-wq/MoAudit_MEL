#!/usr/bin/env python3
"""
Crée un PDF de test simple pour le diagnostic.
"""

import fitz  # PyMuPDF
from pathlib import Path


def create_simple_test_pdf(output_path: str = "test_simple.pdf"):
    """Crée un PDF d'une page avec du texte simple."""

    doc = fitz.open()

    # Page 1: Texte simple
    page = doc.new_page(width=595, height=842)  # A4

    # Titre
    page.insert_text(
        (50, 50),
        "TEST MEL DOCUMENT",
        fontsize=24,
        fontname="helv"
    )

    # Sous-titre
    page.insert_text(
        (50, 80),
        "ATA Chapter 21 - Air Conditioning",
        fontsize=14,
        fontname="helv"
    )

    # Tableau simple (simulé avec du texte)
    table_content = """
ITEM NUMBER    DESCRIPTION                     CAT  INST  REQ   REMARKS
-------------- ------------------------------- ---- ----- ----- ------------------
21-10-01       Air Conditioning Pack           C    2     1     May be inoperative
21-10-01A      Air Conditioning Pack Control   D    1     0     For ground ops only
21-20-01       Cabin Temperature Controller    B    1     0     Provided autopilot
21-30-01       Pressurization Controller       A    2     2     Required for flight
"""

    page.insert_text(
        (50, 120),
        table_content,
        fontsize=10,
        fontname="cour"  # Courier pour alignement
    )

    # Footer
    page.insert_text(
        (50, 800),
        "Page 1 of 1 - Test Document for Docling VLM",
        fontsize=8,
        fontname="helv"
    )

    doc.save(output_path)
    doc.close()

    print(f"PDF créé: {output_path}")
    return output_path


def create_mel_style_pdf(output_path: str = "test_mel_table.pdf"):
    """Crée un PDF avec un tableau MEL réaliste."""

    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 paysage

    # En-tête
    page.insert_text((50, 40), "MINIMUM EQUIPMENT LIST", fontsize=18, fontname="helv")
    page.insert_text((50, 60), "Aircraft Type: PC-12", fontsize=12, fontname="helv")

    # Lignes du tableau
    y = 100
    headers = ["System &", "Item", "Repair", "Number", "Number", ""]
    headers2 = ["Sequence No.", "Description", "Category", "Installed", "Required", "Remarks or Exceptions"]

    # Dessiner le tableau
    col_widths = [80, 200, 60, 60, 60, 280]
    x = 50

    # En-têtes
    for i, (h1, h2) in enumerate(zip(headers, headers2)):
        rect = fitz.Rect(x, y, x + col_widths[i], y + 30)
        page.draw_rect(rect, color=(0, 0, 0), width=0.5)
        page.insert_text((x + 5, y + 12), h1, fontsize=8, fontname="helv")
        page.insert_text((x + 5, y + 22), h2, fontsize=8, fontname="helv")
        x += col_widths[i]

    # Données
    data = [
        ["21-10-01", "Air Conditioning Pack", "C", "2", "1", "(M) May be inoperative provided:"],
        ["", "", "", "", "", "(a) Ambient temp is above 5°C"],
        ["", "", "", "", "", "(b) APU is operative"],
        ["21-10-01A", "Pack Control Panel", "D", "1", "0", "For ground operations only"],
        ["21-20-01", "Cabin Temp Controller", "B", "1", "0", "(O) May be inoperative provided"],
        ["", "", "", "", "", "manual temperature control is used"],
        ["21-30-01", "Press. Controller", "A", "2", "2", "Required"],
    ]

    y += 30
    for row in data:
        x = 50
        for i, cell in enumerate(row):
            rect = fitz.Rect(x, y, x + col_widths[i], y + 20)
            page.draw_rect(rect, color=(0, 0, 0), width=0.5)
            page.insert_text((x + 3, y + 14), cell, fontsize=8, fontname="helv")
            x += col_widths[i]
        y += 20

    # Footer
    page.insert_text((50, 550), "TEST DOCUMENT - NOT FOR OPERATIONAL USE", fontsize=10, fontname="helv")

    doc.save(output_path)
    doc.close()

    print(f"PDF créé: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

    create_simple_test_pdf(str(output_dir / "test_simple.pdf"))
    create_mel_style_pdf(str(output_dir / "test_mel_table.pdf"))

    print("\nPDFs de test créés. Utilisation:")
    print("  curl -X POST http://localhost:8080/test/pdf-page -F 'file=@test_simple.pdf'")
    print("  curl -X POST http://localhost:8080/convert -F 'file=@test_mel_table.pdf'")
