# app/ingestion/extract.py
import fitz  # PyMuPDF
from typing import List

def _page_has_text(page) -> bool:
    return len(page.get_text("text").strip()) > 10

def extract_pages_text_from_pdf(path: str) -> List[str]:
    """
    Extracts text page-by-page from a PDF document.
    """
    doc = fitz.open(path)
    pages = []
    for page in doc:
        txt = page.get_text("text")
        pages.append(txt)
    doc.close()
    return pages

def extract_text_from_pdf(path: str) -> str:
    """Extract full text from a PDF."""
    pages = extract_pages_text_from_pdf(path)
    return "\n\n".join(pages)

def chunk_text(text: str, max_chars: int = 4000) -> List[str]:
    """Chunk by blank-line paragraphs, packed up to max_chars."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) > max_chars and current:
            chunks.append(current)
            current = ""
        current += p + "\n\n"
    if current:
        chunks.append(current)
    return chunks