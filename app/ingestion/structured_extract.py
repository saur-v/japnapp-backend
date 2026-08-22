# app/ingestion/structured_extract.py
import os, json
from typing import Optional, List, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from app.ingestion.extract import extract_text_from_pdf

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
Your task is to extract ALL learnable Japanese material (vocabulary, kanji, grammar points, expressions, sentences) from the provided document in ONE comprehensive pass.

Guidelines:
1. Strict Grounding: ONLY extract items that are explicitly present in the document. Do not invent items outside the source text.
2. Completeness: Extract every meaningful vocabulary word, kanji, and grammar structure found in the document.
3. Accurate Furigana: Provide the exact Kana reading and clean Romaji.
4. Natural Translations: Provide clear English meanings.
5. Examples: Include the Japanese example sentence and English translation if present in the text, or generate a simple natural one grounded in the item.
6. JLPT Level: Assign the detected JLPT level (N5, N4, N3, N2, N1) based on standard JLPT specifications.
"""

def extract_document_in_one_pass(pdf_path: str) -> DocumentExtractionResult:
    """
    Extracts all Japanese learning items from the entire PDF in 1 single Gemini call
    using native structured output (response_schema).
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    raw_text = extract_text_from_pdf(pdf_path)
    prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\nDOCUMENT CONTENT:\n---\n{raw_text}\n---\n\nExtract all Japanese learning items and return JSON matching the schema."

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
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
            print(f"[Model {m} extraction fallback]: {e}")
            last_error = e

    if last_error:
        raise last_error
    return DocumentExtractionResult(items=[], detected_jlpt_levels=[])
