"""
core/llm/ollama.py — Ollama local inference client.
Fallback when Groq is unavailable.
"""
import httpx
from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL

TIMEOUT = 90


def chat(messages: list[dict], max_tokens: int = 1024,
         temperature: float = 0.7) -> dict:
    payload = {
        "model":   OLLAMA_MODEL,
        "messages": messages,
        "stream":  False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }

    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        # Ollama isn't running — this is an expected, common state (not every
        # setup runs it), so don't spam the log with a traceback on every call.
        raise RuntimeError("Ollama unavailable (connection refused)")
    except Exception as e:
        print(f"[Ollama] Error: {e}")
        raise

    return {
        "content": data["message"]["content"],
        "model":   OLLAMA_MODEL,
        "usage":   {},
    }


def list_models() -> list[str]:
    try:
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{OLLAMA_BASE_URL}/api/tags")
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def pull_model(model: str) -> bool:
    try:
        with httpx.Client(timeout=300) as c:
            r = c.post(f"{OLLAMA_BASE_URL}/api/pull",
                       json={"name": model, "stream": False})
            return r.status_code == 200
    except Exception:
        return False
