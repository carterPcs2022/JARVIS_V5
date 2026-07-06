"""
core/llm/openai.py — Groq client (OpenAI-compatible endpoint).
Named openai.py because Groq uses the OpenAI API format exactly.
"""
import time
import httpx
from typing import AsyncIterator
from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL

TIMEOUT = 30


async def stream_chat(messages: list[dict], max_tokens: int = 1024,
                      temperature: float = 0.7) -> AsyncIterator[str]:
    """Yield token strings as they arrive from Groq SSE stream."""
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      True,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        async with c.stream("POST", f"{GROQ_BASE_URL}/chat/completions",
                            json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                import json
                try:
                    data = json.loads(chunk)
                    token = data["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except Exception:
                    continue


def chat(messages: list[dict], max_tokens: int = 1024,
         temperature: float = 0.7, model: str | None = None) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       model or GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }

    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{GROQ_BASE_URL}/chat/completions",
                   json=payload, headers=headers)

        # Respect Groq's own retry-after rather than a fixed guess — capped
        # at 30s so one slow-to-recover rate limit can't block a request
        # thread indefinitely. Up to 2 retries (3 attempts total).
        attempts = 0
        while r.status_code == 429 and attempts < 2:
            retry_after = int(r.headers.get("retry-after", 10))
            wait = min(retry_after, 30)
            print(f"[Groq] Rate limited — waiting {wait}s (attempt {attempts + 1}/2)")
            time.sleep(wait)
            r = c.post(f"{GROQ_BASE_URL}/chat/completions",
                      json=payload, headers=headers)
            attempts += 1

        r.raise_for_status()
        data = r.json()

    return {
        "content": data["choices"][0]["message"]["content"],
        "model":   data.get("model", GROQ_MODEL),
        "usage":   data.get("usage", {}),
    }


def embed(text: str) -> list[float] | None:
    """Text embedding via Groq/OpenAI endpoint."""
    if not GROQ_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        }
        payload = {"model": "text-embedding-ada-002", "input": text}
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{GROQ_BASE_URL}/embeddings",
                       json=payload, headers=headers)
            if r.status_code == 200:
                return r.json()["data"][0]["embedding"]
    except Exception:
        pass
    return None
