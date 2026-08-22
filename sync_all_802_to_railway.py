# sync_all_802_to_railway.py
import json, requests
from sqlalchemy import text
from app.db import SessionLocal
from app.ingestion.pipeline import normalize_ja
from app.daily_agent import ensure_user_exists, generate_daily_plan

user_id = "2dff88fb-9ce6-4ef9-95fd-e3e6a04e0c4a"

with open("extracted_802_words.json", "r", encoding="utf-8") as f:
    items = json.load(f)

print(f"Loading {len(items)} extracted items into Railway database...")

# We can insert directly into PostgreSQL
db = SessionLocal()
uid = ensure_user_exists(db, user_id)

# 1. Create or get document
doc_row = db.execute(text("""
    INSERT INTO documents (id, user_id, title, original_filename, storage_path, status, item_count, detected_jlpt_levels)
    VALUES (gen_random_uuid(), :uid, 'Vocabulary_of_JLPT_N5.pdf', 'Vocabulary_of_JLPT_N5.pdf', '/data/uploads/Vocabulary_of_JLPT_N5.pdf', 'ready', :c, :levels)
    RETURNING id
"""), {"uid": uid, "c": len(items), "levels": ["N5", "N4"]}).fetchone()
doc_id = doc_row[0]

inserted_count = 0
for it in items:
    if not it.get("text_ja"):
        continue
    norm_txt = normalize_ja(it["text_ja"])
    existing = db.execute(text("""
        SELECT id FROM items
        WHERE user_id = :uid AND item_type = :t AND lower(text_ja) = :norm_txt
    """), {"uid": uid, "t": it["item_type"], "norm_txt": norm_txt}).fetchone()

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
            "uid": uid,
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
        inserted_count += 1

    db.execute(text("""
        INSERT INTO item_sources (item_id, document_id) VALUES (:iid, :did)
        ON CONFLICT DO NOTHING
    """), {"iid": item_id, "did": doc_id})

db.commit()

# Regenerate daily plan so today's study set has these items
plan_id = generate_daily_plan(db, uid, force=True)
print(f"SUCCESS! Inserted/Linked {len(items)} words into database. Daily Plan ID: {plan_id}")
