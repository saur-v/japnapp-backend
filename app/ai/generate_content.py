# app/ai/generate_content.py
import os, json
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

model = genai.GenerativeModel(
    "gemini-2.5-flash",
    generation_config={"response_mime_type": "application/json"},
)

GROUNDING_RULE = (
    "Only use content derived from the provided source items; "
    "do not introduce vocabulary, kanji, or facts not present in the provided context."
)

def generate_example_sentence(item: dict, known_vocab: list[str]) -> str:
    prompt = f"""{GROUNDING_RULE}

Write ONE natural Japanese example sentence using the word "{item['text_ja']}" ({item['meaning_en']}).
You may only use vocabulary from this list of words the user already knows: {known_vocab}.
Return ONLY JSON: {{"sentence_ja": "...", "sentence_en": "..."}}
"""
    resp = model.generate_content(prompt)
    return json.loads(resp.text.strip())

def generate_quiz_distractors(target_item: dict, candidate_pool: list[dict], n: int = 3) -> list[str]:
    prompt = f"""{GROUNDING_RULE}

Target answer: "{target_item['meaning_en']}" (word: {target_item['text_ja']}, JLPT {target_item.get('jlpt_level')}).
Pick {n} plausible WRONG answers only from this candidate pool: {[c['meaning_en'] for c in candidate_pool]}.
Prefer distractors close in JLPT level or part of speech.
Return ONLY JSON: {{"distractors": ["...", "...", "..."]}}
"""
    resp = model.generate_content(prompt)
    return json.loads(resp.text.strip())["distractors"]

def generate_notification_copy(word_of_day: dict, study_count: int) -> str:
    prompt = f"""{GROUNDING_RULE}

Word of the day: {word_of_day['text_ja']} ({word_of_day['reading']}) - "{word_of_day['meaning_en']}".
Write ONE short, friendly push notification (under 100 characters) announcing this word and
inviting the user to review today's {study_count} words. No emojis unless natural.
Return ONLY JSON: {{"notification_text": "..."}}
"""
    resp = model.generate_content(prompt)
    return json.loads(resp.text.strip())["notification_text"]