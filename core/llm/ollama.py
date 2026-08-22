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


# ── LLMProvider adapter (core/interfaces/llm_provider.py) ─────────────────────

import asyncio
from core.interfaces.llm_provider import LLMProvider, GenerateRequest, ModelResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def is_available(self) -> bool:
        # Unlike the API-key-gated providers, availability here means "is a
        # local server actually reachable" — cascade.py's _ollama_available()
        # does a real request for the same reason; mirrored rather than
        # imported to avoid this module depending on the (otherwise unused)
        # cascade.py.
        try:
            import urllib.request
            urllib.request.urlopen(OLLAMA_BASE_URL, timeout=2)
            return True
        except Exception:
            return False

    async def generate(self, request: GenerateRequest) -> ModelResponse:
        # chat() below has no `model` param — it always uses OLLAMA_MODEL
        # from config/settings.py, so request.model is ignored here.
        messages = list(request.messages)
        if request.system:
            messages = [{"role": "system", "content": request.system}] + messages
        data = await asyncio.to_thread(chat, messages, request.max_tokens, request.temperature)
        return ModelResponse(
            content=data["content"], model=data["model"], provider=self.name,
            usage=data.get("usage", {}), raw=data,
        )
