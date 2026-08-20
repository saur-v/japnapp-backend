# app/ingestion/pipeline.py
from sqlalchemy import text
from app.ingestion.extract import extract_text_from_pdf, chunk_text
from app.ingestion.structured_extract import extract_items_from_chunk

# app/ingestion/pipeline.py  (small addition — replace the normalize() usage)
import unicodedata

def normalize_ja(text: str) -> str:
    """Normalize Japanese text for de-dup matching: full-width/half-width
    variants collapsed, whitespace stripped, case-folded."""
    text = unicodedata.normalize("NFKC", text)  # collapses ｱ vs ア, Ａ vs A, etc.
    return text.strip().lower()

def run_ingestion(db, document_id: str, user_id: str, pdf_path: str):
    db.execute(text("UPDATE documents SET status='processing' WHERE id=:id"), {"id": document_id})
    db.commit()

    raw_text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(raw_text)

    detected_levels = set()
    item_count = 0

    for chunk in chunks:
        extracted = extract_items_from_chunk(chunk)
        for it in extracted:
            if not it.get("text_ja"):
                continue

            # de-dup: same user + same normalized text_ja + same item_type
            # app/ingestion/pipeline.py  (update the existing-item lookup query)
            existing = db.execute(text("""
            SELECT id FROM items
            WHERE user_id=:uid AND item_type=:t AND lower(text_ja) = :norm_txt
        """), {"uid": user_id, "t": it["item_type"], "norm_txt": normalize_ja(it["text_ja"])}).fetchone()

            if existing:
                item_id = existing[0]
            else:
                row = db.execute(text("""
                    INSERT INTO items (user_id, item_type, text_ja, reading, romaji,
                        meaning_en, part_of_speech, example_sentence_ja, example_sentence_en, jlpt_level)
                    VALUES (:uid,:t,:ja,:reading,:romaji,:meaning,:pos,:exja,:exen,:level)
                    RETURNING id
                """), {
                    "uid": user_id, "t": it["item_type"], "ja": it["text_ja"],
                    "reading": it.get("reading"), "romaji": it.get("romaji"),
                    "meaning": it.get("meaning_en"), "pos": it.get("part_of_speech"),
                    "exja": it.get("example_sentence_ja"), "exen": it.get("example_sentence_en"),
                    "level": it.get("jlpt_level"),
                })
                item_id = row.fetchone()[0]
                item_count += 1

            # link source (idempotent)
            db.execute(text("""
                INSERT INTO item_sources (item_id, document_id) VALUES (:iid,:did)
                ON CONFLICT DO NOTHING
            """), {"iid": item_id, "did": document_id})

            if it.get("jlpt_level"):
                detected_levels.add(it["jlpt_level"])

    db.execute(text("""
        UPDATE documents SET status='ready', item_count=:c, detected_jlpt_levels=:levels
        WHERE id=:id
    """), {"c": item_count, "levels": list(detected_levels), "id": document_id})
    db.commit()