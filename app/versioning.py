# app/versioning.py
from sqlalchemy import text
from app.ingestion.pipeline import run_ingestion

def replace_document(db, document_id: str, user_id: str, new_pdf_path: str):
    """Re-ingest a new version of an existing document. Diffs old vs new item set:
    - items no longer present -> removed (same rule as delete, Section 6.2)
    - new items -> added
    - unchanged items -> KEEP existing memory_records (don't reset review history)
    """
    # snapshot item ids linked to this doc BEFORE re-ingesting
    old_item_ids = {r[0] for r in db.execute(text("""
        SELECT item_id FROM item_sources WHERE document_id=:did
    """), {"did": document_id}).fetchall()}

    # unlink all old sources for this doc (items with other sources survive; orphans get cleaned after)
    db.execute(text("DELETE FROM item_sources WHERE document_id=:did"), {"did": document_id})
    db.commit()

    # re-run ingestion — this re-creates item_sources rows for whatever's newly extracted,
    # reusing existing item rows where text matches (de-dup logic in pipeline.py handles this)
    run_ingestion(db, document_id, user_id, new_pdf_path)

    # find items that were linked to this doc before, but have NO source at all now -> orphaned, delete
    still_orphaned = db.execute(text("""
        SELECT id FROM items i
        WHERE i.id = ANY(:old_ids)
        AND NOT EXISTS (SELECT 1 FROM item_sources s WHERE s.item_id = i.id)
    """), {"old_ids": list(old_item_ids)}).fetchall()

    orphan_ids = [r[0] for r in still_orphaned]
    if orphan_ids:
        # memory history archived, not hard-deleted (Section 6.2 rule)
        db.execute(text("""
            INSERT INTO memory_records_archive
            SELECT * FROM memory_records WHERE item_id = ANY(:ids)
        """), {"ids": orphan_ids})
        db.execute(text("DELETE FROM items WHERE id = ANY(:ids)"), {"ids": orphan_ids})

    db.commit()