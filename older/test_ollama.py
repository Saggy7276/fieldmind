import ollama

response = ollama.chat(
    model="fieldmind",
    messages=[
        {"role": "system", "content": "You are a helpful field operations voice assistant. If you are uncertain or the query is out of scope, respond with exactly: ESCALATE"},
        {"role": "user", "content": "How do I reset a faulty meter reading?"},
    ],
)
print(response["message"]["content"])