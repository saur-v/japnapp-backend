# app/ingestion/structured_extract.py
import os, json
from google import genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

model = genai.GenerativeModel(
    "gemini-2.5-flash",  # fast + cheap for high-volume chunk extraction; swap to gemini-2.5-pro for higher accuracy
    generation_config={"response_mime_type": "application/json"},
)

EXTRACTION_PROMPT = """You are extracting Japanese learning material from a document chunk.

Return ONLY a JSON array (no prose, no markdown fences) of learning items found in the chunk below.
Each item must be one of these types: "vocabulary", "kanji", "sentence", "grammar".

Each item object must have these fields (use null if unknown, never guess):
- item_type
- text_ja
- reading
- romaji
- meaning_en
- part_of_speech
- example_sentence_ja
- example_sentence_en
- jlpt_level  (one of "N5","N4","N3","N2","N1", or null)

Skip anything that is not learnable Japanese material (page numbers, headers, unrelated notes).

CHUNK:
---
{chunk}
---
"""

def extract_items_from_chunk(chunk: str) -> list[dict]:
    resp = model.generate_content(EXTRACTION_PROMPT.format(chunk=chunk))
    raw = resp.text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []  # skip malformed chunk rather than crash the whole ingestion
