import uuid
from datetime import date
from sqlalchemy import text

def normalize_user_id(uid_str: str) -> str:
    try:
        return str(uuid.UUID(str(uid_str)))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(uid_str)))

def ensure_user_exists(db, user_id: str) -> str:
    norm_uid = normalize_user_id(user_id)
    db.execute(text("""
        INSERT INTO users (id, email, display_name)
        VALUES (:uid, :email, 'Learner')
        ON CONFLICT (id) DO NOTHING
    """), {"uid": norm_uid, "email": f"{norm_uid}@example.com"})
    db.commit()
    return norm_uid

def generate_daily_plan(db, user_id: str, new_word_target: int = 10, force: bool = False):
    today = date.today()
    uid = ensure_user_exists(db, user_id)

    if force:
        db.execute(text("DELETE FROM daily_plans WHERE user_id=:uid AND plan_date=:d"), {"uid": uid, "d": today})
        db.commit()
    else:
        existing = db.execute(text("""
            SELECT id FROM daily_plans WHERE user_id=:uid AND plan_date=:d
        """), {"uid": uid, "d": today}).fetchone()
        if existing:
            return existing[0]  # idempotent: don't regenerate unless user forces it

    # 1. Due-for-review items (active documents only)
    due = db.execute(text("""
        SELECT DISTINCT i.id FROM items i
        JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        WHERE i.user_id=:uid AND d.is_active = true AND m.next_due_date <= :today
    """), {"uid": uid, "today": today}).fetchall()
    due_ids = [r[0] for r in due]

    # 2. New items (never studied), active documents only, capped at target
    new = db.execute(text("""
        SELECT id
        FROM (
            SELECT DISTINCT
                i.id,
                i.jlpt_level,
                i.created_at
            FROM items i
            JOIN item_sources s ON s.item_id = i.id
            JOIN documents d ON d.id = s.document_id
            LEFT JOIN memory_records m
                ON m.item_id = i.id
                AND m.user_id = i.user_id
            WHERE i.user_id = :uid
            AND d.is_active = true
            AND m.id IS NULL
        ) x
        ORDER BY jlpt_level, created_at DESC
        LIMIT :limit
    """), {"uid": uid, "limit": new_word_target}).fetchall()
    new_ids = [r[0] for r in new]

    study_set = due_ids + new_ids
    word_of_day = new_ids[0] if new_ids else (due_ids[0] if due_ids else None)

    # 3. Quiz set: sample from study set (simple version: first 5)
    quiz_ids = study_set[:5]

    # initialize memory records for brand-new items
    for iid in new_ids:
        db.execute(text("""
            INSERT INTO memory_records (user_id, item_id, next_due_date, mastery_state)
            VALUES (:uid,:iid,:today,'new')
            ON CONFLICT (user_id, item_id) DO NOTHING
        """), {"uid": uid, "iid": iid, "today": today})

    plan = db.execute(text("""
        INSERT INTO daily_plans (user_id, plan_date, word_of_day_item_id, study_set_item_ids, quiz_item_ids)
        VALUES (:uid,:d,:wod,:study,:quiz) RETURNING id
    """), {"uid": uid, "d": today, "wod": word_of_day, "study": study_set, "quiz": quiz_ids})
    db.commit()
    return plan.fetchone()[0]