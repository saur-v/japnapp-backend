# app/ingestion/extract.py  (updated)
import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_path

def _page_has_text(page) -> bool:
    return len(page.get_text("text").strip()) > 20  # heuristic threshold

def extract_text_from_pdf(path: str) -> str:
    """Extract text from a PDF. Falls back to OCR (jpn+eng) per-page
    if a page has no extractable text layer (i.e. it's a scanned image)."""
    doc = fitz.open(path)
    needs_ocr = any(not _page_has_text(page) for page in doc)
    doc.close()

    if not needs_ocr:
        return _extract_digital_text(path)
    return _extract_with_ocr(path)

def _extract_digital_text(path: str) -> str:
    doc = fitz.open(path)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return "\n\n".join(pages)

def _extract_with_ocr(path: str) -> str:
    """Mixed-mode: use digital text where available per page, OCR only the
    image-based pages. Handles textbooks with a mix of scanned + digital pages."""
    doc = fitz.open(path)
    images = convert_from_path(path, dpi=300)
    pages_text = []

    for i, page in enumerate(doc):
        if _page_has_text(page):
            pages_text.append(page.get_text("text"))
        else:
            ocr_text = pytesseract.image_to_string(images[i], lang="jpn+eng")
            pages_text.append(ocr_text)

    doc.close()
    return "\n\n".join(pages_text)

def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
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