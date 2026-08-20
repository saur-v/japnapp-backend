# app/notifications.py
from datetime import datetime, time

def is_within_quiet_hours(check_time: time, quiet_start: time, quiet_end: time) -> bool:
    """Handles overnight ranges (e.g. 22:00 -> 07:00)."""
    if quiet_start <= quiet_end:
        return quiet_start <= check_time <= quiet_end
    return check_time >= quiet_start or check_time <= quiet_end

def get_notification_schedule(db, user_id: str) -> list[time]:
    from sqlalchemy import text
    row = db.execute(text("""
        SELECT reminder_times, quiet_hours_start, quiet_hours_end FROM users WHERE id=:uid
    """), {"uid": user_id}).mappings().first()

    # filter out any configured reminder that falls inside quiet hours
    return [
        t for t in row["reminder_times"]
        if not is_within_quiet_hours(t, row["quiet_hours_start"], row["quiet_hours_end"])
    ]