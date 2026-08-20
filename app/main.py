# app/main.py
import shutil, uuid, os
from fastapi import FastAPI, UploadFile, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db
from app.ingestion.pipeline import run_ingestion
from app.daily_agent import generate_daily_plan
from app.srs import update_memory_record

app = FastAPI()

@app.post("/documents")
def upload_document(user_id: str, file: UploadFile, db: Session = Depends(get_db)):
    doc_id = str(uuid.uuid4())
    path = f"/data/uploads/{doc_id}.pdf"
    os.makedirs("/data/uploads", exist_ok=True)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    db.execute(text("""
        INSERT INTO documents (id, user_id, title, original_filename, storage_path, status)
        VALUES (:id,:uid,:title,:fname,:path,'processing')
    """), {"id": doc_id, "uid": user_id, "title": file.filename,
            "fname": file.filename, "path": path})
    db.commit()

    run_ingestion(db, doc_id, user_id, path)  # sync for MVP; move to a queue later
    return {"document_id": doc_id, "status": "ready"}

@app.get("/documents")
def list_documents(user_id: str, db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, title, status, is_active, item_count FROM documents WHERE user_id=:uid"),
                       {"uid": user_id}).mappings().all()
    return list(rows)

@app.patch("/documents/{doc_id}")
def toggle_document(doc_id: str, is_active: bool, db: Session = Depends(get_db)):
    db.execute(text("UPDATE documents SET is_active=:a WHERE id=:id"), {"a": is_active, "id": doc_id})
    db.commit()
    return {"ok": True}

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    # items whose ONLY source is this doc get cascade-deleted via item_sources FK + a cleanup query
    db.execute(text("""
        DELETE FROM items WHERE id IN (
            SELECT item_id FROM item_sources GROUP BY item_id HAVING COUNT(*) = 1
        ) AND id IN (SELECT item_id FROM item_sources WHERE document_id=:id)
    """), {"id": doc_id})
    db.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
    db.commit()
    return {"ok": True}

@app.get("/plans/today")
def get_today_plan(user_id: str, db: Session = Depends(get_db)):
    plan_id = generate_daily_plan(db, user_id)
    plan = db.execute(text("SELECT * FROM daily_plans WHERE id=:id"), {"id": plan_id}).mappings().first()
    return dict(plan)

@app.post("/reviews")
def submit_review(user_id: str, item_id: str, result: str, event_type: str = "flashcard",
                   db: Session = Depends(get_db)):
    record = db.execute(text("""
        SELECT ease_factor, interval_days, repetitions FROM memory_records
        WHERE user_id=:uid AND item_id=:iid
    """), {"uid": user_id, "iid": item_id}).mappings().first()

    updated = update_memory_record(dict(record), result)

    db.execute(text("""
        UPDATE memory_records SET ease_factor=:ease, interval_days=:interval, repetitions=:reps,
            next_due_date=:due, last_result=:result, mastery_state=:mastery,
            total_reviews = total_reviews + 1,
            total_correct = total_correct + (CASE WHEN :result != 'again' THEN 1 ELSE 0 END),
            last_reviewed_at = now()
        WHERE user_id=:uid AND item_id=:iid
    """), {**updated, "uid": user_id, "iid": item_id})

    db.execute(text("""
        INSERT INTO review_events (user_id, item_id, event_type, result)
        VALUES (:uid,:iid,:etype,:result)
    """), {"uid": user_id, "iid": item_id, "etype": event_type, "result": result})
    db.commit()
    return {"ok": True, "updated": updated}

@app.get("/progress")
def get_progress(user_id: str, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT mastery_state, COUNT(*) FROM memory_records WHERE user_id=:uid GROUP BY mastery_state
    """), {"uid": user_id}).fetchall()
    return {state: count for state, count in rows}

# app/main.py  (add these endpoints — appended to existing file)
from app.quiz import build_quiz_for_items
from app.ai.generate_content import generate_example_sentence

@app.get("/quiz/today")
def get_today_quiz(user_id: str, db: Session = Depends(get_db)):
    plan = db.execute(text("""
        SELECT quiz_item_ids FROM daily_plans WHERE user_id=:uid AND plan_date = CURRENT_DATE
    """), {"uid": user_id}).mappings().first()
    if not plan:
        return {"questions": []}
    questions = build_quiz_for_items(db, user_id, plan["quiz_item_ids"])
    return {"questions": questions}

@app.post("/quiz/answer")
def submit_quiz_answer(user_id: str, item_id: str, correct: bool, db: Session = Depends(get_db)):
    result = "good" if correct else "again"
    # reuse the same SRS update path as flashcards (Section 10.3: shared memory system)
    return submit_review(user_id=user_id, item_id=item_id, result=result, event_type="quiz", db=db)


# app/main.py (add)
from fastapi.responses import Response
from app.tts import synthesize_japanese

@app.get("/tts")
def tts_endpoint(text_ja: str):
    audio_bytes = synthesize_japanese(text_ja)
    return Response(content=audio_bytes, media_type="audio/mpeg")


# app/main.py (add)
from app.progress import get_jlpt_progress

@app.get("/progress/jlpt")
def jlpt_progress_endpoint(user_id: str, db: Session = Depends(get_db)):
    return get_jlpt_progress(db, user_id)
    # e.g. {"N5": {"seen": 800, "mastered": 480}, "N4": {"seen": 210, "mastered": 40}, ...}



# app/main.py  (add endpoint — separate from MCQ /quiz/answer since typing needs text input, not a bool)
from app.quiz import grade_typed_answer

@app.post("/quiz/answer/typed")
def submit_typed_answer(user_id: str, item_id: str, user_input: str, db: Session = Depends(get_db)):
    item = db.execute(text("""
        SELECT reading, romaji, meaning_en FROM items WHERE id=:id
    """), {"id": item_id}).mappings().first()

    alternates = [a for a in [item["romaji"], item["meaning_en"]] if a]
    correct = grade_typed_answer(user_input, item["reading"] or item["meaning_en"], alternates)

    result = "good" if correct else "again"
    return submit_review(user_id=user_id, item_id=item_id, result=result, event_type="quiz", db=db)


# app/main.py (add)
from app.stats import get_streak, get_accuracy_trend, get_review_heatmap

@app.get("/progress/streak")
def streak_endpoint(user_id: str, db: Session = Depends(get_db)):
    return {"streak_days": get_streak(db, user_id)}

@app.get("/progress/accuracy-trend")
def accuracy_trend_endpoint(user_id: str, days: int = 30, db: Session = Depends(get_db)):
    return {"trend": get_accuracy_trend(db, user_id, days)}

@app.get("/progress/heatmap")
def heatmap_endpoint(user_id: str, days: int = 365, db: Session = Depends(get_db)):
    return {"heatmap": get_review_heatmap(db, user_id, days)}


# app/main.py (add)
import shutil
from app.versioning import replace_document

@app.put("/documents/{doc_id}/replace")
def replace_document_endpoint(doc_id: str, user_id: str, file: UploadFile, db: Session = Depends(get_db)):
    path = f"/data/uploads/{doc_id}.pdf"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    replace_document(db, doc_id, user_id, path)
    return {"ok": True}


# app/main.py (add — lets user configure this from Settings screen, Section 16)
@app.patch("/settings/notifications")
def update_notification_settings(user_id: str, reminder_times: list[str],
                                   quiet_start: str, quiet_end: str, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE users SET reminder_times=:times, quiet_hours_start=:qs, quiet_hours_end=:qe
        WHERE id=:uid
    """), {"times": reminder_times, "qs": quiet_start, "qe": quiet_end, "uid": user_id})
    db.commit()
    return {"ok": True}


# app/main.py (add)
from app.speaking import transcribe_japanese_audio, score_pronunciation

@app.post("/speaking/attempt")
async def submit_speaking_attempt(user_id: str, item_id: str, audio: UploadFile,
                                    db: Session = Depends(get_db)):
    item = db.execute(text("SELECT text_ja FROM items WHERE id=:id"), {"id": item_id}).mappings().first()

    audio_bytes = await audio.read()
    stt_result = transcribe_japanese_audio(audio_bytes)
    scoring = score_pronunciation(item["text_ja"], stt_result["transcript"], stt_result["confidence"])

    # log the attempt so Progress screen / review history can reference it later
    db.execute(text("""
        INSERT INTO speaking_attempts (user_id, item_id, transcript, score, text_similarity, stt_confidence)
        VALUES (:uid,:iid,:transcript,:score,:sim,:conf)
    """), {"uid": user_id, "iid": item_id, "transcript": scoring["transcript"],
            "score": scoring["score"], "sim": scoring["text_similarity"],
            "conf": scoring["stt_confidence"]})
    db.commit()

    # feed into SRS: treat score >= 70 as "good", else "again" (same shared memory system as Section 10.3)
    result = "good" if scoring["score"] >= 70 else "again"
    submit_review(user_id=user_id, item_id=item_id, result=result, event_type="speaking", db=db)

    return scoring




# app/main.py (add)
@app.get("/items/batch")
def get_items_batch(item_ids: str, db: Session = Depends(get_db)):
    """item_ids: comma-separated UUIDs, e.g. ?item_ids=uuid1,uuid2,uuid3"""
    ids = item_ids.split(",")
    rows = db.execute(text("""
        SELECT id, text_ja, reading, romaji, meaning_en, part_of_speech,
               example_sentence_ja, example_sentence_en, jlpt_level
        FROM items WHERE id = ANY(:ids)
    """), {"ids": ids}).mappings().all()
    return [dict(r) for r in rows]