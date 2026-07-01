"""core/tools/voice.py — TTS tool wrapper (delegates to services/voice.py)."""

def speak(text: str) -> str:
    try:
        from services.voice import speak as svc_speak
        return svc_speak(text)
    except Exception as e:
        return f"[Voice error: {e}]"

def listen() -> str:
    try:
        from services.voice import listen as svc_listen
        return svc_listen()
    except Exception as e:
        return f"[Listen error: {e}]"
