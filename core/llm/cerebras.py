"""
core/llm/cerebras.py — Cerebras client (OpenAI-compatible endpoint).
Free fallback tried after Groq/Ollama and before paid Anthropic — a
separate account/quota from Groq, so Groq's daily cap being exhausted
doesn't touch this one. Free tier: 5 RPM / 30K TPM / 1M TPD, verified
live against Cerebras's own docs, not third-party blog roundups.
"""
import re
import httpx
from config.settings import CEREBRAS_API_KEY, CEREBRAS_MODEL, CEREBRAS_BASE_URL

TIMEOUT = 30

# Same shape as Groq's rate-limit body parsing (core/llm/openai.py) — kept
# as a fallback for when there's no numeric Retry-After header.
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


class CerebrasRateLimitError(Exception):
    """429 from Cerebras. Carries retry_after (seconds) when available —
    same handling as GroqRateLimitError so services/circuit_breaker.py can
    honor the real wait instead of a fixed cooldown."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_TIMEOUT_CONFIG = httpx.Timeout(connect=3.0, read=TIMEOUT, write=5.0, pool=5.0)
_CLIENT = httpx.Client(
    timeout=_TIMEOUT_CONFIG,
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30),
)


def chat(messages: list[dict], max_tokens: int = 1024,
         temperature: float = 0.7, model: str | None = None) -> dict:
    if not CEREBRAS_API_KEY:
        raise ValueError("CEREBRAS_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {CEREBRAS_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       model or CEREBRAS_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }

    r = _CLIENT.post(f"{CEREBRAS_BASE_URL}/chat/completions",
                     json=payload, headers=headers)

    if r.status_code == 429:
        retry_after = _parse_retry_after(r)
        print(f"[Cerebras] Rate limited — failing fast "
              f"(retry after {retry_after if retry_after is not None else '?'}s)")
        raise CerebrasRateLimitError(
            f"429 rate limited on model {model or CEREBRAS_MODEL}", retry_after=retry_after)

    r.raise_for_status()
    data = r.json()

    # gpt-oss-120b (and other reasoning-style Cerebras models) return
    # internal chain-of-thought under a separate "reasoning" field, distinct
    # from "content" — not inline <think> tags in "content" the way Groq's
    # Qwen3 does. If max_tokens runs out mid-reasoning, "content" is absent
    # entirely (finish_reason "length"), which used to raise a bare
    # KeyError here — that crashed the whole request instead of letting the
    # router's normal fallback (this is itself a fallback tier) catch it
    # and move on to the next provider.
    message = data["choices"][0]["message"]
    content = message.get("content")
    if not content:
        raise RuntimeError(
            "Cerebras returned no content — likely ran out of max_tokens "
            "during internal reasoning before producing a final answer "
            f"(finish_reason={data['choices'][0].get('finish_reason')!r})"
        )

    return {
        "content": content,
        "model":   data.get("model", CEREBRAS_MODEL),
        "usage":   data.get("usage", {}),
    }
