"""core/llm/embeddings.py — text embeddings via Voyage AI.

Neither Groq nor Anthropic offer a real embeddings endpoint (the old
core/llm/openai.py embed() called Groq with an OpenAI model name and always
404'd, silently swallowed by its own try/except). Voyage is Anthropic's own
recommended embeddings partner and has a genuine 200M free-token allowance
on voyage-4-lite.

Every function here degrades to None/unchanged on any failure — a missing
key, a timeout, or a Voyage outage must never break chat, only fall back to
the TF-IDF-only recall that already worked before this existed.
"""
import httpx
from config.settings import VOYAGE_API_KEY, VOYAGE_MODEL, VOYAGE_EMBED_DIM

_ENDPOINT = "https://api.voyageai.com/v1/embeddings"
_TIMEOUT_SECONDS = 1.5  # recall() sits on the blocking chat-response path


def embed(text: str, input_type: str = "document") -> list[float] | None:
    """input_type: "document" when storing a memory, "query" when recalling."""
    if not VOYAGE_API_KEY or not text:
        return None
    try:
        r = httpx.post(
            _ENDPOINT,
            json={
                "input": text,
                "model": VOYAGE_MODEL,
                "input_type": input_type,
                "output_dimension": VOYAGE_EMBED_DIM,
            },
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            timeout=_TIMEOUT_SECONDS,
        )
        if r.status_code == 200:
            return r.json()["data"][0]["embedding"]
    except Exception:
        pass
    return None


def embed_batch(texts: list[str], input_type: str = "document") -> list[list[float] | None]:
    """Batch embed (Voyage allows up to 1000 texts/call) — used for the
    one-time backfill of existing long_term entries. Returns one entry per
    input text, None in that slot if the whole batch call failed."""
    if not VOYAGE_API_KEY or not texts:
        return [None] * len(texts)
    try:
        r = httpx.post(
            _ENDPOINT,
            json={
                "input": texts,
                "model": VOYAGE_MODEL,
                "input_type": input_type,
                "output_dimension": VOYAGE_EMBED_DIM,
            },
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            timeout=30,
        )
        if r.status_code == 200:
            return [d["embedding"] for d in r.json()["data"]]
    except Exception:
        pass
    return [None] * len(texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
