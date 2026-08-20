# app/speaking.py
import io
from google.cloud import speech
import Levenshtein
import unicodedata

speech_client = speech.SpeechClient()  # uses GOOGLE_APPLICATION_CREDENTIALS, same as tts.py

def transcribe_japanese_audio(audio_bytes: bytes, sample_rate: int = 16000) -> dict:
    """Transcribes recorded speech. Returns transcript + STT confidence."""
    audio = speech.RecognitionAudio(content=audio_bytes)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,
        language_code="ja-JP",
        enable_automatic_punctuation=False,
    )
    response = speech_client.recognize(config=config, audio=audio)

    if not response.results:
        return {"transcript": "", "confidence": 0.0}

    best = response.results[0].alternatives[0]
    return {"transcript": best.transcript, "confidence": best.confidence}

def normalize_ja(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.strip().replace(" ", "").replace("　", "")

def score_pronunciation(target_text: str, transcript: str, stt_confidence: float) -> dict:
    """Approximate pronunciation score:
    - text_similarity: how close the transcribed text is to the target (character-level)
    - combined with STT's own confidence in what it heard
    NOTE: this measures 'did you say the right sounds/words', not native-like accent —
    a true acoustic pronunciation-assessment API (e.g. Azure) would be needed for that.
    """
    t_norm = normalize_ja(target_text)
    s_norm = normalize_ja(transcript)

    if not t_norm:
        return {"score": 0, "text_similarity": 0, "transcript": transcript}

    distance = Levenshtein.distance(t_norm, s_norm)
    max_len = max(len(t_norm), len(s_norm), 1)
    text_similarity = 1 - (distance / max_len)

    # weighted blend: text match matters more than raw STT confidence
    combined_score = round((text_similarity * 0.7 + stt_confidence * 0.3) * 100)

    return {
        "score": max(0, combined_score),
        "text_similarity": round(text_similarity, 3),
        "stt_confidence": round(stt_confidence, 3),
        "transcript": transcript,
        "target": target_text,
    }