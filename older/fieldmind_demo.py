import sounddevice as sd
from faster_whisper import WhisperModel
import ollama
import pyttsx3
import chromadb
from sentence_transformers import SentenceTransformer
import re

embedder = SentenceTransformer("all-MiniLM-L6-v2")
rag_client = chromadb.PersistentClient(path="./rag_db")
rag_collection = rag_client.get_collection("about")

def retrieve(query, top_k=2):
    q_emb = embedder.encode(query).tolist()
    results = rag_collection.query(query_embeddings=[q_emb], n_results=top_k)
    return "\n".join(results["documents"][0])

# ── Setup (loads once) ──
print("Loading FieldMind...")
stt = WhisperModel("base", device="cpu", compute_type="int8")


SYSTEM_PROMPT = (
    "You are a helpful field operations voice assistant. "
    "Answer clearly and concisely in 2-3 sentences. "
    "If you are uncertain or the query is out of scope, respond with exactly: ESCALATE"
)

# ── Pipeline functions ──
def listen(duration=5, samplerate=16000):
    print(f"\n🎤 Listening ({duration}s)...")
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype="float32")
    sd.wait()
    segments, _ = stt.transcribe(audio.flatten(), language="en")
    return " ".join(seg.text for seg in segments).strip()

def ask_and_speak_streaming(question):
    context = retrieve(question)

    stream = ollama.chat(
        model="fieldmind",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        stream=True,                 # <-- the key change
    )

    buffer = ""
    full_answer = ""
    print("🤖 FieldMind: ", end="", flush=True)

    for chunk in stream:
        token = chunk["message"]["content"]
        print(token, end="", flush=True)   # live text in console
        buffer += token
        full_answer += token

        # When we hit a sentence end, speak that sentence
        if re.search(r"[.!?]\s*$", buffer):
            sentence = buffer.strip()
            if sentence:
                speak(sentence)            # speak while next sentence streams
            buffer = ""

    # Speak any leftover text with no final punctuation
    if buffer.strip():
        speak(buffer.strip())

    print()  # newline
    return full_answer
def speak(text):
    engine = pyttsx3.init()      # fresh engine each time
    engine.setProperty("rate", 175)
    engine.say(text)
    engine.runAndWait()
    engine.stop()
    del engine

# ── Main loop ──
print("\n✅ FieldMind is ready. Press Ctrl+C to stop.\n")
speak("Field Mind is online and ready.")

try:
    while True:
        question = listen(duration=5)

        if not question:
            print("(heard nothing, listening again)")
            continue

        print(f"🧑 Operator: {question}")

        answer = ask_and_speak_streaming(question)
        if "ESCALATE" in answer.upper():
            speak("I am transferring you to a specialist now.")

except KeyboardInterrupt:
    print("\n👋 FieldMind stopped.")