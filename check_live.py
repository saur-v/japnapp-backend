# check_live.py
import requests

user_id = "2dff88fb-9ce6-4ef9-95fd-e3e6a04e0c4a"
base_url = "https://web-production-1bf99.up.railway.app"

# 1. Documents
docs = requests.get(f"{base_url}/documents?user_id={user_id}").json()
print("=== UPLOADED DOCUMENTS ===")
for d in docs:
    print(f"File: {d.get('title')} | Status: {d.get('status')} | Items Extracted: {d.get('item_count')} | JLPT: {d.get('detected_jlpt_levels')}")

# 2. Items
items = requests.get(f"{base_url}/items?user_id={user_id}&limit=100").json()
print(f"\n=== EXTRACTED WORDS ({len(items)} items) ===")
for i, it in enumerate(items):
    ja = it.get('text_ja', '')
    reading = it.get('reading', '')
    meaning = it.get('meaning_en', '')
    level = it.get('jlpt_level', '')
    pos = it.get('part_of_speech', '')
    print(f"{i+1}. {ja} [{reading}] ({pos}) - {meaning} [JLPT {level}]")
