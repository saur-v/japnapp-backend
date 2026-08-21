# app/stats.py
from datetime import date, timedelta
from sqlalchemy import text

def get_streak(db, user_id: str) -> int:
    """Consecutive days (ending today or yesterday) with at least one review_event."""
    rows = db.execute(text("""
        SELECT DISTINCT created_at::date AS d FROM review_events
        WHERE user_id=:uid ORDER BY d DESC
    """), {"uid": user_id}).fetchall()
    active_days = {r[0] for r in rows}

    streak = 0
    cursor = date.today()
    # allow the streak to still count if today has no review yet but yesterday does
    if cursor not in active_days:
        cursor -= timedelta(days=1)
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak

def get_accuracy_trend(db, user_id: str, days: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = db.execute(text("""
        SELECT created_at::date AS d,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE result != 'again') AS correct
        FROM review_events
        WHERE user_id=:uid AND created_at >= :cutoff
        GROUP BY d ORDER BY d
    """), {"uid": user_id, "cutoff": cutoff}).mappings().all()

    return [
        {"date": str(r["d"]), "accuracy": round(r["correct"] / r["total"], 3) if r["total"] else 0}
        for r in rows
    ]

def get_review_heatmap(db, user_id: str, days: int = 365) -> list[dict]:
    """Calendar-heatmap data: review count per day, like GitHub contributions graph."""
    cutoff = date.today() - timedelta(days=days)
    rows = db.execute(text("""
        SELECT created_at::date AS d, COUNT(*) AS count
        FROM review_events
        WHERE user_id=:uid AND created_at >= :cutoff
        GROUP BY d ORDER BY d
    """), {"uid": user_id, "cutoff": cutoff}).mappings().all()
    return [{"date": str(r["d"]), "count": r["count"]} for r in rows]