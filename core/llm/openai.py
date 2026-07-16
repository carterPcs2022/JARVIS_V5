"""
core/llm/openai.py — Groq client (OpenAI-compatible endpoint).
Named openai.py because Groq uses the OpenAI API format exactly.
"""
import re
import httpx
from typing import AsyncIterator
from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL

TIMEOUT = 30

# Matches Groq's rate-limit error body, e.g. "Please try again in
# 43m2.847s." or "Please try again in 4.521s." — used when the response
# doesn't carry a numeric Retry-After header (seen in practice for
# tokens-per-day limits, unlike the shorter-lived per-minute ones).
_RETRY_AFTER_BODY_RE = re.compile(
    r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.I
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        message = response.json().get("error", {}).get("message", "")
    except Exception:
        return None
    m = _RETRY_AFTER_BODY_RE.search(message)
    if not m or not any(m.groups()):
        return None
    hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds


class GroqRateLimitError(Exception):
    """429 from Groq. Carries retry_after (seconds, from the Retry-After
    header, or parsed from Groq's error message body when no header is
    sent) when available — a TPM (tokens-per-minute) limit resets in
    single-digit seconds and a TPD (tokens-per-day) limit can reset 40+
    minutes out; this lets callers (services/circuit_breaker.py) honor the
    real wait instead of retrying against a fixed cooldown that has no idea
    which one was hit."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after

# Connect-timeout, not a flat total-request timeout: a fixed few-second cap
# on the *whole* call would kill the "research" tier's own legitimate
# generations (up to 8192 output tokens — even at Groq's speed that can
# take longer than a few seconds to fully stream). A tight connect timeout
# still gets the actual goal (fail fast if the connection itself is
# hanging/broken) without cutting off an already-in-progress, working
# response.
_TIMEOUT_CONFIG = httpx.Timeout(connect=3.0, read=TIMEOUT, write=5.0, pool=5.0)

# Module-level clients, reused across every call instead of opening a
# fresh TCP+TLS connection per request — Groq is the primary provider,
# hit on nearly every chat message, so keep-alive connection reuse here
# is a real, cheap latency win (not needed for Anthropic/Ollama, which
# are called far less often). httpx.Client is documented as safe for
# concurrent use across threads, so a single shared instance is fine
# even though chat()/embed() can be called from multiple request threads.
_CLIENT = httpx.Client(
    timeout=_TIMEOUT_CONFIG,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
)
_ASYNC_CLIENT: httpx.AsyncClient | None = None


def _get_async_client() -> httpx.AsyncClient:
    # Created lazily on first use (inside an async context) rather than at
    # import time, so it binds to whatever event loop is actually running
    # instead of risking construction before one exists.
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        _ASYNC_CLIENT = httpx.AsyncClient(
            timeout=_TIMEOUT_CONFIG,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
        )
    return _ASYNC_CLIENT


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

    c = _get_async_client()
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

    r = _CLIENT.post(f"{GROQ_BASE_URL}/chat/completions",
                     json=payload, headers=headers)

    # Fail fast on 429 instead of sleeping through Groq's retry-after
    # (previously up to 30s, twice — a single request could block for
    # a minute before core/llm/router.py's chat() cascade ever got a
    # chance to fall back to Ollama). Raising GroqRateLimitError (not just
    # relying on raise_for_status()'s generic httpx.HTTPStatusError) carries
    # the real Retry-After value through to services/circuit_breaker.py, so
    # a tokens-per-day exhaustion (resets in 40+ minutes) isn't treated the
    # same as a tokens-per-minute one (resets in seconds) — check_groq() in
    # core/llm/router.py catches this specifically alongside
    # httpx.HTTPStatusError and still treats a 429 as "up, just rate
    # limited" rather than down.
    if r.status_code == 429:
        retry_after = _parse_retry_after(r)
        print(f"[Groq] Rate limited — failing fast "
              f"(retry after {retry_after if retry_after is not None else '?'}s)")
        raise GroqRateLimitError(
            f"429 rate limited on model {model or GROQ_MODEL}", retry_after=retry_after)

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
        r = _CLIENT.post(f"{GROQ_BASE_URL}/embeddings",
                         json=payload, headers=headers)
        if r.status_code == 200:
            return r.json()["data"][0]["embedding"]
    except Exception:
        pass
    return None
