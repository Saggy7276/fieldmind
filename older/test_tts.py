import pyttsx3

engine = pyttsx3.init()
engine.setProperty("rate", 175)   # speaking speed
engine.say("Field Mind voice assistant is online and ready.")
engine.runAndWait()