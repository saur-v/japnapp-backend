# extract_all_words.py
import os, json, time, sys
from dotenv import load_dotenv
load_dotenv()

from app.ingestion.structured_extract import extract_document_in_one_pass

pdf_path = r"c:\japnapp\Vocabulary_of_JLPT_N5.pdf"
print(f"Starting full extraction on: {pdf_path}...")
start_time = time.time()

result = extract_document_in_one_pass(pdf_path)
elapsed = time.time() - start_time

print(f"\n==========================================")
print(f"EXTRACTION COMPLETE in {elapsed:.2f} seconds!")
print(f"TOTAL EXTRACTED WORDS: {len(result.items)}")
print(f"DETECTED JLPT LEVELS: {result.detected_jlpt_levels}")
print(f"==========================================")

# Save to a json file to inspect
with open("extracted_802_words.json", "w", encoding="utf-8") as f:
    json.dump([item.model_dump() for item in result.items], f, ensure_ascii=False, indent=2)

print("Saved all extracted words to extracted_802_words.json")

# Print first 5 and last 5 words
print("\n--- FIRST 5 WORDS ---")
for i, it in enumerate(result.items[:5]):
    print(f"{i+1}. {it.text_ja} [{it.reading}] - {it.meaning_en} ({it.item_type})")

print("\n--- LAST 5 WORDS ---")
for i, it in enumerate(result.items[-5:]):
    idx = len(result.items) - 5 + i + 1
    print(f"{idx}. {it.text_ja} [{it.reading}] - {it.meaning_en} ({it.item_type})")
