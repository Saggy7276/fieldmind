import sounddevice as sd
from faster_whisper import WhisperModel
import ollama

stt = WhisperModel("base", device="cpu", compute_type="int8")

SYSTEM_PROMPT = (
    "You are a helpful field operations voice assistant. "
    "Answer clearly and concisely. "
    "If you are uncertain or the query is out of scope, respond with exactly: ESCALATE"
)

def listen(duration=5, samplerate=16000):
    print(f"🎤 Speak now ({duration} seconds)...")
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype="float32")
    sd.wait()
    print("Processing...")
    segments, _ = stt.transcribe(audio.flatten(), language="en")
    return " ".join(seg.text for seg in segments).strip()

def ask_model(question):
    response = ollama.chat(
        model="fieldmind",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": question},
        ],
    )
    return response["message"]["content"]

# Run one full turn: speak → transcribe → model answers
question = listen(duration=5)
print(f"\n🧑 You said: {question}")

answer = ask_model(question)
print(f"\n🤖 FieldMind: {answer}")