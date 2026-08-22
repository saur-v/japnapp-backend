# app/ingestion/structured_extract.py
import os, json, time
from typing import Optional, List, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from app.ingestion.extract import extract_pages_text_from_pdf

load_dotenv()

class JapaneseLearningItem(BaseModel):
    item_type: Literal["vocabulary", "kanji", "sentence", "grammar"] = Field(
        description="Type of learning item: vocabulary, kanji, sentence, or grammar"
    )
    text_ja: str = Field(description="The Japanese word, kanji, or sentence in natural script")
    reading: Optional[str] = Field(None, description="Hiragana or Katakana furigana reading")
    romaji: Optional[str] = Field(None, description="Romaji transliteration")
    meaning_en: str = Field(description="English meaning or translation")
    part_of_speech: Optional[str] = Field(None, description="noun, verb, adjective, particle, expression, etc.")
    example_sentence_ja: Optional[str] = Field(None, description="Example sentence in Japanese using this item")
    example_sentence_en: Optional[str] = Field(None, description="English translation of the example sentence")
    jlpt_level: Optional[Literal["N5", "N4", "N3", "N2", "N1"]] = Field(
        None, description="Estimated or detected JLPT level: N5, N4, N3, N2, N1, or null"
    )

class DocumentExtractionResult(BaseModel):
    items: List[JapaneseLearningItem] = Field(
        description="All extracted Japanese vocabulary, kanji, grammar points, and expressions from the document"
    )
    detected_jlpt_levels: List[str] = Field(
        default_factory=list, description="Unique JLPT levels identified across the document (e.g. N5, N4)"
    )

EXTRACTION_SYSTEM_PROMPT = """You are an expert Japanese linguist and curriculum builder.
Your task is to extract ALL learnable Japanese material (vocabulary, kanji, grammar points, expressions, sentences) from the provided document text.

Guidelines:
1. Strict Grounding: ONLY extract items that are explicitly present in the document. Do not invent items outside the source text.
2. Completeness: Extract EVERY single numbered vocabulary word, expression, and kanji found in the text.
3. Accurate Furigana: Provide the exact Kana reading and clean Romaji.
4. Natural Translations: Provide clear English meanings.
5. Examples: Include the Japanese example sentence and English translation if present in the text, or generate a simple natural one grounded in the item.
6. JLPT Level: Assign the detected JLPT level (N5, N4, N3, N2, N1) based on standard JLPT specifications.
"""

def extract_items_from_text(client: genai.Client, text_segment: str) -> DocumentExtractionResult:
    prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\nDOCUMENT CONTENT:\n---\n{text_segment}\n---\n\nExtract all Japanese learning items from this text and return JSON matching DocumentExtractionResult."
    models_to_try = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]
    last_error = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DocumentExtractionResult,
                    temperature=0.1,
                ),
            )
            result_json = json.loads(response.text)
            return DocumentExtractionResult(**result_json)
        except Exception as e:
            print(f"[Model {m} extraction error]: {e}")
            last_error = e

    if last_error:
        raise last_error
    return DocumentExtractionResult(items=[], detected_jlpt_levels=[])

def extract_document_in_one_pass(pdf_path: str) -> DocumentExtractionResult:
    """
    Extracts all Japanese learning items from the entire PDF.
    - Filters out empty/blank trailing pages automatically.
    - Processes valid vocabulary pages in optimal 3-page batches to extract all 800+ items without token truncation!
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set on the server!")

    client = genai.Client(api_key=api_key)
    raw_pages = extract_pages_text_from_pdf(pdf_path)
    
    # Filter out blank / trailing pages
    valid_pages = [p for p in raw_pages if len(p.strip()) > 50]
    total_valid = len(valid_pages)

    if total_valid == 0:
        return DocumentExtractionResult(items=[], detected_jlpt_levels=[])

    if total_valid <= 3:
        full_text = "\n\n".join(valid_pages)
        return extract_items_from_text(client, full_text)

    # Multi-page vocabulary list (e.g. 25 pages, 802 words)
    print(f"[Extracting Japanese Material]: {total_valid} content pages detected. Processing in optimal 3-page batches...")
    batch_size = 3
    all_items = []
    all_levels = set()

    for i in range(0, total_valid, batch_size):
        batch_pages = valid_pages[i : i + batch_size]
        batch_text = "\n\n".join(batch_pages)
        try:
            res = extract_items_from_text(client, batch_text)
            all_items.extend(res.items)
            for lvl in res.detected_jlpt_levels:
                all_levels.add(lvl)
            print(f"Batch {i // batch_size + 1}/{(total_valid + batch_size - 1) // batch_size} extracted {len(res.items)} words (Total so far: {len(all_items)})")
            time.sleep(0.5)
        except Exception as e:
            print(f"[Batch {i // batch_size + 1} Error]: {e}")

    return DocumentExtractionResult(items=all_items, detected_jlpt_levels=list(all_levels))
