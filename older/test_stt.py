import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

# Load Whisper (downloads ~150MB the first time, then cached)
stt = WhisperModel("base", device="cpu", compute_type="int8")

def listen(duration=5, samplerate=16000):
    print(f"🎤 Speak now ({duration} seconds)...")
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype="float32")
    sd.wait()
    print("Processing...")
    segments, _ = stt.transcribe(audio.flatten(), language="en")
    text = " ".join(seg.text for seg in segments).strip()
    return text

result = listen(duration=5)
print(f"\nYou said: {result}")
