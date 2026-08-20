# app/quiz.py
import random
from sqlalchemy import text
from app.ai.generate_content import generate_quiz_distractors

QUESTION_TYPES = ["word_to_meaning", "meaning_to_word", "reading", "fill_in_blank", "listening"]

def _pick_question_type(mastery_state: str) -> str:
    """Weaker items get easier MCQ formats; stronger items get harder formats."""
    if mastery_state in ("new", "learning"):
        return random.choice(["word_to_meaning", "meaning_to_word", "reading"])
    elif mastery_state == "review":
        return random.choice(["fill_in_blank", "listening", "word_to_meaning"])
    else:  # mastered
        return random.choice(["fill_in_blank", "listening", "typing"])

def build_quiz_for_items(db, user_id: str, item_ids: list[str]) -> list[dict]:
    if not item_ids:
        return []

    items = db.execute(text("""
        SELECT i.id, i.text_ja, i.reading, i.meaning_en, i.part_of_speech,
               i.example_sentence_ja, i.jlpt_level, m.mastery_state
        FROM items i
        JOIN memory_records m ON m.item_id = i.id AND m.user_id = i.user_id
        WHERE i.id = ANY(:ids) AND i.user_id = :uid
    """), {"ids": item_ids, "uid": user_id}).mappings().all()
    items = [dict(r) for r in items]

    # candidate pool for distractors = all active-document items, excluding the target
    pool = db.execute(text("""
        SELECT DISTINCT i.id, i.text_ja, i.meaning_en, i.part_of_speech, i.jlpt_level
        FROM items i
        JOIN item_sources s ON s.item_id = i.id
        JOIN documents d ON d.id = s.document_id
        WHERE i.user_id = :uid AND d.is_active = true
    """), {"uid": user_id}).mappings().all()
    pool = [dict(r) for r in pool]

    quiz_questions = []
    for item in items:
        q_type = _pick_question_type(item["mastery_state"])
        candidates = [c for c in pool if c["id"] != item["id"]
                      and c.get("part_of_speech") == item.get("part_of_speech")]
        if len(candidates) < 3:
            candidates = [c for c in pool if c["id"] != item["id"]]  # relax filter if too few

        question = {"item_id": item["id"], "question_type": q_type}

        if q_type == "word_to_meaning":
            distractors = generate_quiz_distractors(item, candidates, n=3)
            options = distractors + [item["meaning_en"]]
            random.shuffle(options)
            question.update({"prompt_ja": item["text_ja"], "options": options,
                              "correct_answer": item["meaning_en"]})

        elif q_type == "meaning_to_word":
            distractor_words = random.sample([c["text_ja"] for c in candidates],
                                              min(3, len(candidates)))
            options = distractor_words + [item["text_ja"]]
            random.shuffle(options)
            question.update({"prompt_en": item["meaning_en"], "options": options,
                              "correct_answer": item["text_ja"]})

        elif q_type == "reading":
            # distractors: readings from other candidate items
            distractor_readings = random.sample(
                [c.get("text_ja") for c in candidates if c.get("text_ja")],
                min(3, len(candidates))
            )
            options = distractor_readings + [item["reading"]]
            random.shuffle(options)
            question.update({"prompt_ja": item["text_ja"], "options": options,
                              "correct_answer": item["reading"]})

        elif q_type == "fill_in_blank":
            sentence = item.get("example_sentence_ja") or f"{item['text_ja']}を使います。"
            blanked = sentence.replace(item["text_ja"], "＿＿＿", 1)
            question.update({"prompt_ja": blanked, "correct_answer": item["text_ja"]})

        elif q_type == "listening":
            question.update({"audio_text": item["text_ja"], "options": None,
                              "correct_answer": item["meaning_en"]})

        elif q_type == "typing":
            question.update({"prompt_ja": item["text_ja"],
                              "correct_answer": item["reading"] or item["meaning_en"]})

        quiz_questions.append(question)

    return quiz_questions


# app/quiz.py  (add this function)
import unicodedata

def normalize_answer(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.strip().lower().replace(" ", "")

def grade_typed_answer(user_input: str, correct_answer: str, acceptable_alternates: list[str] = None) -> bool:
    """Used for the 'typing' question type — high-mastery items only (Section 10.1)."""
    norm_input = normalize_answer(user_input)
    candidates = [correct_answer] + (acceptable_alternates or [])
    return any(norm_input == normalize_answer(c) for c in candidates)