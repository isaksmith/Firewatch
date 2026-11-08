"""Render the deck PDFs to 1920-wide PNGs (build/slides/<name>-<page>.png) with PyMuPDF."""
import sys
from pathlib import Path
import pymupdf

HERE = Path(__file__).resolve().parent
DECK = HERE.parents[2] / "design/deck"
OUT = HERE / "build/slides"
OUT.mkdir(parents=True, exist_ok=True)
for pdf, tag in [("Firewatch-Solution.pdf", "sol"), ("Firewatch-Flowchart.pdf", "flow"), ("Firewatch-vs-Current-Build.pdf", "cmp")]:
    doc = pymupdf.open(DECK / pdf)
    for i, page in enumerate(doc, 1):
        z = 1920 / page.rect.width
        page.get_pixmap(matrix=pymupdf.Matrix(z, z)).save(OUT / f"{tag}-{i:02d}.png")
print(len(list(OUT.glob("*.png"))), "slides")
