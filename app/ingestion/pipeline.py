# app/ingestion/pipeline.py
import unicodedata
from sqlalchemy import text
from app.ingestion.structured_extract import extract_document_in_one_pass

def normalize_ja(text: str) -> str:
    """Normalize Japanese text for de-dup matching: full-width/half-width
    variants collapsed, whitespace stripped, case-folded."""
    text = unicodedata.normalize("NFKC", text)
    return text.strip().lower()

def run_ingestion(db, document_id: str, user_id: str, pdf_path: str):
    """
    Ingests a complete PDF in 1 single pass using LangChain structured outputs with Gemini.
    """
    db.execute(text("UPDATE documents SET status='processing' WHERE id=:id"), {"id": document_id})
    db.commit()

    # Extract all items and detected JLPT levels in 1 single Gemini call
    result = extract_document_in_one_pass(pdf_path)
    extracted_items = result.items
    detected_levels = set(result.detected_jlpt_levels or [])
    item_count = 0

    for item_model in extracted_items:
        it = item_model.model_dump() if hasattr(item_model, "model_dump") else dict(item_model)
        if not it.get("text_ja"):
            continue

        # De-dup: check if same user already has this word
        norm_txt = normalize_ja(it["text_ja"])
        existing = db.execute(text("""
            SELECT id FROM items
            WHERE user_id = :uid AND item_type = :t AND lower(text_ja) = :norm_txt
        """), {"uid": user_id, "t": it["item_type"], "norm_txt": norm_txt}).fetchone()

        if existing:
            item_id = existing[0]
        else:
            row = db.execute(text("""
                INSERT INTO items (
                    user_id, item_type, text_ja, reading, romaji,
                    meaning_en, part_of_speech, example_sentence_ja, example_sentence_en, jlpt_level
                )
                VALUES (:uid, :t, :ja, :reading, :romaji, :meaning, :pos, :exja, :exen, :level)
                RETURNING id
            """), {
                "uid": user_id,
                "t": it["item_type"],
                "ja": it["text_ja"],
                "reading": it.get("reading"),
                "romaji": it.get("romaji"),
                "meaning": it.get("meaning_en"),
                "pos": it.get("part_of_speech"),
                "exja": it.get("example_sentence_ja"),
                "exen": it.get("example_sentence_en"),
                "level": it.get("jlpt_level"),
            })
            item_id = row.fetchone()[0]
            item_count += 1

        # Link source document (idempotent)
        db.execute(text("""
            INSERT INTO item_sources (item_id, document_id) VALUES (:iid, :did)
            ON CONFLICT DO NOTHING
        """), {"iid": item_id, "did": document_id})

        if it.get("jlpt_level"):
            detected_levels.add(it["jlpt_level"])

    # Mark document ready with detected levels and total count
    db.execute(text("""
        UPDATE documents SET status='ready', item_count=:c, detected_jlpt_levels=:levels
        WHERE id=:id
    """), {"c": item_count, "levels": list(detected_levels), "id": document_id})
    db.commit()