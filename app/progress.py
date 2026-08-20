# app/progress.py
from sqlalchemy import text

def get_jlpt_progress(db, user_id: str) -> dict:
    rows = db.execute(text("""
        SELECT i.jlpt_level,
               COUNT(*) AS seen,
               COUNT(*) FILTER (WHERE m.mastery_state = 'mastered') AS mastered
        FROM items i
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        LEFT JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        WHERE i.user_id = :uid AND d.is_active = true AND i.jlpt_level IS NOT NULL
        GROUP BY i.jlpt_level
        ORDER BY i.jlpt_level
    """), {"uid": user_id}).mappings().all()

    return {
        row["jlpt_level"]: {"seen": row["seen"], "mastered": row["mastered"]}
        for row in rows
    }