# app/main.py
import shutil, uuid, os
from typing import Optional, List
from fastapi import FastAPI, UploadFile, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db
from app.ingestion.pipeline import run_ingestion
from app.daily_agent import generate_daily_plan, ensure_user_exists
from app.srs import update_memory_record
from app.quiz import build_quiz_for_items, grade_typed_answer
from app.ai.generate_content import generate_example_sentence
from app.tts import synthesize_japanese
from app.progress import get_jlpt_progress
from app.stats import get_streak, get_accuracy_trend, get_review_heatmap
from app.versioning import replace_document
from app.speaking import transcribe_japanese_audio, score_pronunciation

app = FastAPI(title="Japanese Learning Agent API")

# Enable CORS for React Native / Expo Web / mobile app clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "app": "Japanese Learning Agent API", "version": "1.0.0"}

# ----------------- Document Endpoints -----------------

@app.post("/documents")
def upload_document(user_id: str, file: UploadFile, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    doc_id = str(uuid.uuid4())
    upload_dir = "/data/uploads"
    if not os.path.exists(upload_dir):
        # Fallback to local uploads if /data is not mounted
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    path = os.path.join(upload_dir, f"{doc_id}_{file.filename}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    db.execute(text("""
        INSERT INTO documents (id, user_id, title, original_filename, storage_path, status)
        VALUES (:id,:uid,:title,:fname,:path,'processing')
    """), {"id": doc_id, "uid": uid, "title": file.filename,
            "fname": file.filename, "path": path})
    db.commit()

    run_ingestion(db, doc_id, uid, path)
    return {"document_id": doc_id, "status": "ready"}

@app.get("/documents")
def list_documents(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    rows = db.execute(text("""
        SELECT id, title, status, is_active, item_count, detected_jlpt_levels, uploaded_at 
        FROM documents 
        WHERE user_id=:uid 
        ORDER BY uploaded_at DESC
    """), {"uid": uid}).mappings().all()
    return [dict(r) for r in rows]

@app.patch("/documents/{doc_id}")
def toggle_document(doc_id: str, is_active: bool, db: Session = Depends(get_db)):
    db.execute(text("UPDATE documents SET is_active=:a WHERE id=:id"), {"a": is_active, "id": doc_id})
    db.commit()
    return {"ok": True, "is_active": is_active}

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    # Items whose ONLY source is this doc get deleted; items with multiple sources survive
    db.execute(text("""
        DELETE FROM items WHERE id IN (
            SELECT item_id FROM item_sources GROUP BY item_id HAVING COUNT(*) = 1
        ) AND id IN (SELECT item_id FROM item_sources WHERE document_id=:id)
    """), {"id": doc_id})
    db.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
    db.commit()
    return {"ok": True}

@app.put("/documents/{doc_id}/replace")
def replace_document_endpoint(doc_id: str, user_id: str, file: UploadFile, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    upload_dir = "/data/uploads"
    if not os.path.exists(upload_dir):
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    path = os.path.join(upload_dir, f"{doc_id}_{file.filename}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    replace_document(db, doc_id, uid, path)
    return {"ok": True}

# ----------------- Daily Plan Endpoints -----------------

@app.get("/plans/today")
def get_today_plan(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    plan_id = generate_daily_plan(db, uid, force=False)
    plan = db.execute(text("SELECT * FROM daily_plans WHERE id=:id"), {"id": plan_id}).mappings().first()
    return dict(plan) if plan else {}

@app.post("/plans/today/regenerate")
def regenerate_today_plan(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    plan_id = generate_daily_plan(db, uid, force=True)
    plan = db.execute(text("SELECT * FROM daily_plans WHERE id=:id"), {"id": plan_id}).mappings().first()
    return dict(plan) if plan else {}

# ----------------- Items & Flashcards -----------------

@app.get("/items/batch")
def get_items_batch(item_ids: str, db: Session = Depends(get_db)):
    ids = [i.strip() for i in item_ids.split(",") if i.strip()]
    if not ids:
        return []
    rows = db.execute(text("""
        SELECT i.id, i.text_ja, i.reading, i.romaji, i.meaning_en, i.part_of_speech,
               i.example_sentence_ja, i.example_sentence_en, i.jlpt_level,
               COALESCE(m.mastery_state, 'new') AS mastery_state,
               COALESCE(m.ease_factor, 2.5) AS ease_factor,
               COALESCE(m.interval_days, 0) AS interval_days,
               COALESCE(m.repetitions, 0) AS repetitions,
               COALESCE(m.total_reviews, 0) AS total_reviews,
               COALESCE(m.total_correct, 0) AS total_correct
        FROM items i
        LEFT JOIN memory_records m ON m.item_id = i.id
        WHERE i.id = ANY((:ids)::uuid[])
    """), {"ids": ids}).mappings().all()
    return [dict(r) for r in rows]

@app.get("/items")
def list_items(
    user_id: str,
    document_id: Optional[str] = None,
    jlpt_level: Optional[str] = None,
    mastery_state: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    uid = ensure_user_exists(db, user_id)
    query = """
        SELECT DISTINCT i.id, i.text_ja, i.reading, i.romaji, i.meaning_en, i.part_of_speech,
               i.example_sentence_ja, i.example_sentence_en, i.jlpt_level, i.created_at,
               COALESCE(m.mastery_state, 'new') AS mastery_state,
               COALESCE(m.repetitions, 0) AS repetitions
        FROM items i
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        LEFT JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        WHERE i.user_id = :uid AND d.is_active = true
    """
    params = {"uid": uid, "limit": limit, "offset": offset}

    if document_id:
        query += " AND s.document_id = :did"
        params["did"] = document_id
    if jlpt_level:
        query += " AND i.jlpt_level = :lvl"
        params["lvl"] = jlpt_level
    if mastery_state:
        query += " AND COALESCE(m.mastery_state, 'new') = :mstate"
        params["mstate"] = mastery_state
    if search:
        query += " AND (i.text_ja ILIKE :search OR i.reading ILIKE :search OR i.meaning_en ILIKE :search OR i.romaji ILIKE :search)"
        params["search"] = f"%{search}%"

    query += " ORDER BY i.created_at DESC LIMIT :limit OFFSET :offset"
    rows = db.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]

@app.get("/items/{item_id}")
def get_item_detail(item_id: str, user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    item = db.execute(text("""
        SELECT i.*, 
               COALESCE(m.mastery_state, 'new') AS mastery_state,
               COALESCE(m.ease_factor, 2.5) AS ease_factor,
               COALESCE(m.interval_days, 0) AS interval_days,
               COALESCE(m.repetitions, 0) AS repetitions,
               m.next_due_date,
               m.last_result,
               COALESCE(m.total_reviews, 0) AS total_reviews,
               COALESCE(m.total_correct, 0) AS total_correct,
               m.last_reviewed_at
        FROM items i
        LEFT JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        WHERE i.id = :id AND i.user_id = :uid
    """), {"id": item_id, "uid": uid}).mappings().first()

    if not item:
        return {}

    sources = db.execute(text("""
        SELECT d.id, d.title, d.original_filename, d.is_active
        FROM documents d
        JOIN item_sources s ON s.document_id = d.id
        WHERE s.item_id = :id
    """), {"id": item_id}).mappings().all()

    result = dict(item)
    result["sources"] = [dict(s) for s in sources]
    return result

# ----------------- Reviews & SRS -----------------

@app.post("/reviews")
def submit_review(
    user_id: str,
    item_id: str,
    result: str,
    event_type: str = "flashcard",
    db: Session = Depends(get_db)
):
    uid = ensure_user_exists(db, user_id)
    record = db.execute(text("""
        SELECT ease_factor, interval_days, repetitions FROM memory_records
        WHERE user_id=:uid AND item_id=:iid
    """), {"uid": uid, "iid": item_id}).mappings().first()

    if not record:
        record = {"ease_factor": 2.5, "interval_days": 0, "repetitions": 0}

    updated = update_memory_record(dict(record), result)

    db.execute(text("""
        INSERT INTO memory_records (user_id, item_id, ease_factor, interval_days, repetitions,
                                    next_due_date, last_result, mastery_state, total_reviews,
                                    total_correct, last_reviewed_at)
        VALUES (:uid, :iid, :ease, :interval, :reps, :due, :result, :mastery, 1, 
                CASE WHEN :result != 'again' THEN 1 ELSE 0 END, now())
        ON CONFLICT (user_id, item_id) DO UPDATE SET
            ease_factor = :ease,
            interval_days = :interval,
            repetitions = :reps,
            next_due_date = :due,
            last_result = :result,
            mastery_state = :mastery,
            total_reviews = memory_records.total_reviews + 1,
            total_correct = memory_records.total_correct + (CASE WHEN :result != 'again' THEN 1 ELSE 0 END),
            last_reviewed_at = now()
    """), {
        "ease": updated.get("ease_factor", 2.5),
        "interval": updated.get("interval_days", 1),
        "reps": updated.get("repetitions", 1),
        "due": updated.get("next_due_date"),
        "mastery": updated.get("mastery_state", "learning"),
        "result": result,
        "uid": uid,
        "iid": item_id
    })

    db.execute(text("""
        INSERT INTO review_events (user_id, item_id, event_type, result)
        VALUES (:uid,:iid,:etype,:result)
    """), {"uid": uid, "iid": item_id, "etype": event_type, "result": result})

    db.commit()
    return {"ok": True, "updated": updated}

# ----------------- Quiz Endpoints -----------------

@app.get("/quiz/today")
def get_today_quiz(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    plan = db.execute(text("""
        SELECT quiz_item_ids FROM daily_plans WHERE user_id=:uid AND plan_date = CURRENT_DATE
    """), {"uid": uid}).mappings().first()

    if not plan or not plan["quiz_item_ids"]:
        plan_id = generate_daily_plan(db, uid, force=False)
        plan = db.execute(text("SELECT quiz_item_ids FROM daily_plans WHERE id=:id"), {"id": plan_id}).mappings().first()

    if not plan or not plan.get("quiz_item_ids"):
        return {"questions": []}

    questions = build_quiz_for_items(db, uid, plan["quiz_item_ids"])
    return {"questions": questions}

@app.post("/quiz/answer")
def submit_quiz_answer(user_id: str, item_id: str, correct: bool, db: Session = Depends(get_db)):
    result = "good" if correct else "again"
    return submit_review(user_id=user_id, item_id=item_id, result=result, event_type="quiz", db=db)

@app.post("/quiz/answer/typed")
def submit_typed_answer(user_id: str, item_id: str, user_input: str, db: Session = Depends(get_db)):
    item = db.execute(text("""
        SELECT reading, romaji, meaning_en FROM items WHERE id=:id
    """), {"id": item_id}).mappings().first()

    if not item:
        return {"ok": False, "correct": False}

    alternates = [a for a in [item["romaji"], item["meaning_en"]] if a]
    correct = grade_typed_answer(user_input, item["reading"] or item["meaning_en"], alternates)
    result = "good" if correct else "again"
    submit_review(user_id=user_id, item_id=item_id, result=result, event_type="quiz", db=db)
    return {"ok": True, "correct": correct, "target": item["reading"] or item["meaning_en"]}

# ----------------- Progress & Stats -----------------

@app.get("/progress")
def get_progress(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    rows = db.execute(text("""
        SELECT COALESCE(m.mastery_state, 'new') AS state, COUNT(DISTINCT i.id) AS count
        FROM items i
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        LEFT JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        WHERE i.user_id=:uid AND d.is_active = true
        GROUP BY COALESCE(m.mastery_state, 'new')
    """), {"uid": uid}).fetchall()
    
    data = {"new": 0, "learning": 0, "review": 0, "mastered": 0}
    for state, count in rows:
        data[state] = count
    return data

@app.get("/progress/jlpt")
def jlpt_progress_endpoint(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    return get_jlpt_progress(db, uid)

@app.get("/progress/streak")
def streak_endpoint(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    return {"streak_days": get_streak(db, uid)}

@app.get("/progress/accuracy-trend")
def accuracy_trend_endpoint(user_id: str, days: int = 30, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    return {"trend": get_accuracy_trend(db, uid, days)}

@app.get("/progress/heatmap")
def heatmap_endpoint(user_id: str, days: int = 365, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    return {"heatmap": get_review_heatmap(db, uid, days)}

# ----------------- TTS & Speaking -----------------

@app.get("/tts")
def tts_endpoint(text_ja: str):
    try:
        audio_bytes = synthesize_japanese(text_ja)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        return Response(content=b"", media_type="audio/mpeg", status_code=500)

@app.post("/speaking/attempt")
async def submit_speaking_attempt(user_id: str, item_id: str, audio: UploadFile,
                                    db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    item = db.execute(text("SELECT text_ja FROM items WHERE id=:id"), {"id": item_id}).mappings().first()
    if not item:
        return {"score": 0, "text_similarity": 0, "stt_confidence": 0, "transcript": "", "target": ""}

    audio_bytes = await audio.read()
    stt_result = transcribe_japanese_audio(audio_bytes)
    scoring = score_pronunciation(item["text_ja"], stt_result["transcript"], stt_result["confidence"])

    db.execute(text("""
        INSERT INTO speaking_attempts (user_id, item_id, transcript, score, text_similarity, stt_confidence)
        VALUES (:uid,:iid,:transcript,:score,:sim,:conf)
    """), {"uid": uid, "iid": item_id, "transcript": scoring["transcript"],
            "score": scoring["score"], "sim": scoring["text_similarity"],
            "conf": scoring["stt_confidence"]})
    db.commit()

    result = "good" if scoring["score"] >= 70 else "again"
    submit_review(user_id=user_id, item_id=item_id, result=result, event_type="speaking", db=db)
    return scoring

# ----------------- Settings Endpoints -----------------

@app.get("/settings")
def get_user_settings(user_id: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    user = db.execute(text("""
        SELECT id, email, display_name, timezone, jlpt_focus_level, notification_time,
               daily_new_word_target, quiet_hours_start, quiet_hours_end, reminder_times
        FROM users WHERE id=:uid
    """), {"uid": uid}).mappings().first()
    return dict(user) if user else {}

@app.patch("/settings")
def update_settings(
    user_id: str,
    display_name: Optional[str] = None,
    jlpt_focus_level: Optional[str] = None,
    daily_new_word_target: Optional[int] = None,
    notification_time: Optional[str] = None,
    reminder_times: Optional[List[str]] = None,
    quiet_hours_start: Optional[str] = None,
    quiet_hours_end: Optional[str] = None,
    db: Session = Depends(get_db)
):
    uid = ensure_user_exists(db, user_id)
    updates = []
    params = {"uid": uid}

    if display_name is not None:
        updates.append("display_name = :dname")
        params["dname"] = display_name
    if jlpt_focus_level is not None:
        updates.append("jlpt_focus_level = :jlpt")
        params["jlpt"] = jlpt_focus_level
    if daily_new_word_target is not None:
        updates.append("daily_new_word_target = :target")
        params["target"] = daily_new_word_target
    if notification_time is not None:
        updates.append("notification_time = :ntime::time")
        params["ntime"] = notification_time
    if reminder_times is not None:
        updates.append("reminder_times = :rtimes::time[]")
        params["rtimes"] = reminder_times
    if quiet_hours_start is not None:
        updates.append("quiet_hours_start = :qstart::time")
        params["qstart"] = quiet_hours_start
    if quiet_hours_end is not None:
        updates.append("quiet_hours_end = :qend::time")
        params["qend"] = quiet_hours_end

    if updates:
        sql = f"UPDATE users SET {', '.join(updates)} WHERE id = :uid"
        db.execute(text(sql), params)
        db.commit()

    return {"ok": True}

@app.patch("/settings/notifications")
def update_notification_settings(user_id: str, reminder_times: list[str],
                                   quiet_start: str, quiet_end: str, db: Session = Depends(get_db)):
    uid = ensure_user_exists(db, user_id)
    db.execute(text("""
        UPDATE users SET reminder_times=:times, quiet_hours_start=:qs::time, quiet_hours_end=:qe::time
        WHERE id=:uid
    """), {"times": reminder_times, "qs": quiet_start, "qe": quiet_end, "uid": uid})
    db.commit()
    return {"ok": True}
