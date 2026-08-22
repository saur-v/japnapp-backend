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
    """
    Strict Idempotent Daily Plan Generator:
    - 1 fixed plan per calendar date.
    - Word of the Day is locked for the entire day.
    - Only 1 word of the day per day, invariant to refreshes.
    """
    today = date.today()
    uid = ensure_user_exists(db, user_id)

    # 0. Fetch user's custom daily target and JLPT level
    user_row = db.execute(text("SELECT daily_new_word_target, jlpt_focus_level FROM users WHERE id=:uid"), {"uid": uid}).fetchone()
    target = user_row[0] if (user_row and user_row[0]) else new_word_target

    existing_wod = None
    if force:
        prev_plan = db.execute(text("""
            SELECT word_of_day_item_id FROM daily_plans WHERE user_id=:uid AND plan_date=:d
        """), {"uid": uid, "d": today}).fetchone()
        if prev_plan and prev_plan[0]:
            existing_wod = prev_plan[0]
        db.execute(text("DELETE FROM daily_plans WHERE user_id=:uid AND plan_date=:d"), {"uid": uid, "d": today})
        db.commit()
    else:
        existing = db.execute(text("""
            SELECT id FROM daily_plans WHERE user_id=:uid AND plan_date=:d
        """), {"uid": uid, "d": today}).fetchone()
        if existing:
            return existing[0]  # STRICT: Idempotent - return today's existing plan without changing anything!

    # 1. Due-for-review items (active documents only, sorted deterministically)
    due = db.execute(text("""
        SELECT DISTINCT i.id, m.next_due_date, m.ease_factor FROM items i
        JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        WHERE i.user_id=:uid AND d.is_active = true AND m.next_due_date <= :today
        ORDER BY m.next_due_date ASC, m.ease_factor ASC, i.id ASC
    """), {"uid": uid, "today": today}).fetchall()
    due_ids = [r[0] for r in due]

    # 2. New items (never reviewed), active documents only, capped at target
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
            AND (m.id IS NULL OR (m.mastery_state = 'new' AND COALESCE(m.total_reviews, 0) = 0))
        ) x
        ORDER BY jlpt_level ASC NULLS LAST, created_at ASC, id ASC
        LIMIT :limit
    """), {"uid": uid, "limit": target}).fetchall()
    new_ids = [r[0] for r in new]

    study_set = due_ids + new_ids

    # 3. Deterministic Word of the Day (Strictly 1 for the day)
    # If a WOD was already assigned for today and is still active, KEEP IT LOCKED.
    if existing_wod and existing_wod in study_set:
        word_of_day = existing_wod
    elif study_set:
        # Pick deterministically so it never changes randomly
        word_of_day = study_set[0]
    else:
        word_of_day = None

    # 4. Quiz set: first items from study set
    quiz_ids = study_set[:5]

    # Initialize memory records for brand-new items
    for iid in new_ids:
        db.execute(text("""
            INSERT INTO memory_records (user_id, item_id, next_due_date, mastery_state, ease_factor, interval_days, repetitions, total_reviews)
            VALUES (:uid, :iid, :today, 'new', 2.5, 0, 0, 0)
            ON CONFLICT (user_id, item_id) DO NOTHING
        """), {"uid": uid, "iid": iid, "today": today})

    plan = db.execute(text("""
        INSERT INTO daily_plans (user_id, plan_date, word_of_day_item_id, study_set_item_ids, quiz_item_ids)
        VALUES (:uid, :d, :wod, :study, :quiz) RETURNING id
    """), {"uid": uid, "d": today, "wod": word_of_day, "study": study_set, "quiz": quiz_ids})
    db.commit()
    return plan.fetchone()[0]