"""
core/llm/openai.py — Groq client (OpenAI-compatible endpoint).
Named openai.py because Groq uses the OpenAI API format exactly.
"""
import json
import os
import re
import httpx
from typing import AsyncIterator
from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL

TIMEOUT = 30

# Groq can reject an oversized HTTP request with 413 before model inference.
# Keep a safety ceiling below typical proxy/request-body limits while leaving
# the model's much larger context window available to normal calls.
GROQ_MAX_REQUEST_BYTES = int(os.getenv("GROQ_MAX_REQUEST_BYTES", "450000"))
GROQ_MAX_MESSAGE_CHARS = int(os.getenv("GROQ_MAX_MESSAGE_CHARS", "120000"))

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
    """429 from Groq, carrying the server-provided retry delay when available."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class GroqPayloadTooLargeError(Exception):
    """413 from Groq or a client-side payload that is too large.

    The router can treat this as a provider/request-size failure and fall
    back cleanly instead of turning it into a misleading application result.
    """
    def __init__(self, message: str, request_bytes: int | None = None):
        super().__init__(message)
        self.request_bytes = request_bytes


def _message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def _compact_messages(messages: list[dict]) -> tuple[list[dict], int]:
    """Bound Groq request size while preserving system + newest conversation.

    JARVIS already budgets its assembled context, but a later pipeline stage
    can add system/tool/history content. This is the final provider boundary,
    so it must enforce a real byte limit on the JSON body rather than relying
    only on approximate token counts.
    """
    normalized = [dict(m) for m in messages]
    raw = json.dumps(
        {"model": GROQ_MODEL, "messages": normalized},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(raw) <= GROQ_MAX_REQUEST_BYTES:
        return normalized, len(raw)

    # Preserve the system prompt, the newest user message, and then the most
    # recent messages that fit. Never silently replace the newest user input.
    system = [m for m in normalized if m.get("role") == "system"][:1]
    newest_user_index = next(
        (i for i in range(len(normalized) - 1, -1, -1)
         if normalized[i].get("role") == "user"),
        None,
    )
    newest_user = [normalized[newest_user_index]] if newest_user_index is not None else []

    selected = []
    seen = set()
    for m in system + newest_user:
        marker = id(m)
        if marker not in seen:
            selected.append(m)
            seen.add(marker)

    # Add recent messages from the end, oldest-to-newest ordering restored.
    for m in reversed(normalized):
        if id(m) in seen:
            continue
        candidate = [*selected, m]
        size = len(json.dumps(
            {"model": GROQ_MODEL, "messages": candidate},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"))
        if size > GROQ_MAX_REQUEST_BYTES:
            continue
        selected.append(m)
        seen.add(id(m))

    # Restore original ordering.
    selected.sort(key=lambda m: normalized.index(m))

    # If one individual message is itself huge, trim only its content.
    for m in selected:
        text = _message_text(m)
        if len(text) <= GROQ_MAX_MESSAGE_CHARS:
            continue
        clipped = text[:GROQ_MAX_MESSAGE_CHARS] + "\n[provider-boundary truncation]"
        m["content"] = clipped

    selected.sort(key=lambda m: normalized.index(m))
    size = len(json.dumps(
        {"model": GROQ_MODEL, "messages": selected},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8"))
    return selected, size


_TIMEOUT_CONFIG = httpx.Timeout(connect=3.0, read=TIMEOUT, write=5.0, pool=5.0)

_CLIENT = httpx.Client(
    timeout=_TIMEOUT_CONFIG,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
)
_ASYNC_CLIENT: httpx.AsyncClient | None = None


def _get_async_client() -> httpx.AsyncClient:
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

    messages, request_bytes = _compact_messages(messages)
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }

    print(f"[Groq] stream request: {request_bytes} bytes, {len(messages)} messages")
    c = _get_async_client()
    async with c.stream("POST", f"{GROQ_BASE_URL}/chat/completions",
                        json=payload, headers=headers) as resp:
        if resp.status_code == 413:
            raise GroqPayloadTooLargeError(
                f"Groq rejected streaming payload (HTTP 413, {request_bytes} bytes)",
                request_bytes,
            )
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
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

    messages, request_bytes = _compact_messages(messages)
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    r = _CLIENT.post(f"{GROQ_BASE_URL}/chat/completions",
                     json=payload, headers=headers)

    if r.status_code == 413:
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = ""
        print(
            f"[Groq] Payload too large — {request_bytes} bytes"
            + (f": {detail}" if detail else "")
        )
        raise GroqPayloadTooLargeError(
            f"413 payload too large for Groq ({request_bytes} bytes)"
            + (f": {detail}" if detail else ""),
            request_bytes,
        )

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
        "model": data.get("model", GROQ_MODEL),
        "usage": data.get("usage", {}),
    }


def embed(text: str) -> list[float] | None:
    """Text embedding via Groq/OpenAI endpoint."""
    if not GROQ_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": "text-embedding-ada-002", "input": text}
        r = _CLIENT.post(f"{GROQ_BASE_URL}/embeddings",
                         json=payload, headers=headers)
        if r.status_code == 200:
            return r.json()["data"][0]["embedding"]
    except Exception:
        pass
    return None


import asyncio
from core.interfaces.llm_provider import LLMProvider, GenerateRequest, ModelResponse


class GroqProvider(LLMProvider):
    name = "groq"

    def is_available(self) -> bool:
        return bool(GROQ_API_KEY)

    async def generate(self, request: GenerateRequest) -> ModelResponse:
        messages = list(request.messages)
        if request.system:
            messages = [{"role": "system", "content": request.system}] + messages
        data = await asyncio.to_thread(
            chat, messages, request.max_tokens, request.temperature, request.model,
        )
        return ModelResponse(
            content=data["content"], model=data["model"], provider=self.name,
            usage=data.get("usage", {}), raw=data,
        )
