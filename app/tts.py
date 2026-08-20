# app/tts.py
from google.cloud import texttospeech

tts_client = texttospeech.TextToSpeechClient()  # uses GOOGLE_APPLICATION_CREDENTIALS env var

def synthesize_japanese(text_ja: str) -> bytes:
    synthesis_input = texttospeech.SynthesisInput(text=text_ja)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ja-JP", name="ja-JP-Neural2-B"  # neural JP voice
    )
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = tts_client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content