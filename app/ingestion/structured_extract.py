# app/ingestion/structured_extract.py
import os, base64
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from app.ingestion.extract import extract_text_from_pdf

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

def get_structured_llm():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=api_key,
        temperature=0.1,
    )
    return llm.with_structured_output(DocumentExtractionResult)

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
    using LangChain's structured_output (Pydantic schema).
    """
    structured_llm = get_structured_llm()

    # Read and encode PDF for direct native multimodal document understanding
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        message = HumanMessage(
            content=[
                {"type": "text", "text": EXTRACTION_SYSTEM_PROMPT},
                {
                    "type": "media",
                    "mime_type": "application/pdf",
                    "data": pdf_b64,
                },
                {"type": "text", "text": "Extract all Japanese learning items and return the complete DocumentExtractionResult."}
            ]
        )
        result: DocumentExtractionResult = structured_llm.invoke([message])
        return result
    except Exception as e:
        # Fallback to full digital/OCR text extraction if direct PDF media upload has issues
        print(f"[Fallback to Full Text Extraction]: {e}")
        raw_text = extract_text_from_pdf(pdf_path)
        message = HumanMessage(
            content=f"{EXTRACTION_SYSTEM_PROMPT}\n\nDOCUMENT CONTENT:\n---\n{raw_text}\n---"
        )
        result: DocumentExtractionResult = structured_llm.invoke([message])
        return result
