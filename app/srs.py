# app/srs.py
from datetime import date, timedelta

def grade_to_quality(result: str) -> int:
    return {"again": 0, "hard": 3, "good": 4, "easy": 5}[result]

def update_memory_record(record: dict, result: str) -> dict:
    """record has: ease_factor, interval_days, repetitions.
       Returns updated fields. Mirrors simplified SM-2."""
    q = grade_to_quality(result)
    ease = record["ease_factor"]
    reps = record["repetitions"]

    if q < 3:  # "again"
        reps = 0
        interval = 1
        ease = max(1.3, ease - 0.2)
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = round(record["interval_days"] * ease)

        if result == "easy":
            ease += 0.1
        elif result == "hard":
            ease = max(1.3, ease - 0.15)
        # "good" leaves ease unchanged

    mastery = "new"
    if reps == 0:
        mastery = "learning"
    elif reps < 3:
        mastery = "learning"
    elif reps < 8:
        mastery = "review"
    else:
        mastery = "mastered"

    return {
        "ease_factor": ease,
        "interval_days": interval,
        "repetitions": reps,
        "next_due_date": date.today() + timedelta(days=interval),
        "last_result": result,
        "mastery_state": mastery,
    }