"""core.memory_gate — bounded memory retention and retrieval gate.

Memory should improve JARVIS without becoming an unfiltered transcript dump.
This module is intentionally deterministic: it does not call an LLM.
"""

from __future__ import annotations

import re
from collections import Counter
from math import log


_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)sk-[A-Za-z0-9_-]{16,}"),
)

_LOW_VALUE = {
    "ok", "okay", "thanks", "thank", "hi", "hello", "hey",
    "cool", "lol", "yes", "no",
}


def is_safe_to_retain(text: str) -> bool:
    """Return False for obvious credential-like material."""
    value = text or ""
    return not any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def importance_score(text: str, explicit: bool = False) -> float:
    """Estimate durable-memory value from deterministic signals (0..1)."""
    value = (text or "").strip()
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    if not tokens:
        return 0.0
    unique = len(set(tokens))
    score = min(0.45, unique / 40)
    if explicit:
        score += 0.35
    if any(x in value.lower() for x in (
        "remember", "always", "prefer", "project", "decision",
        "goal", "plan", "important", "my name", "i want",
    )):
        score += 0.2
    if len(tokens) > 80:
        score += 0.05
    if len(tokens) <= 3 and not explicit and not (set(tokens) - _LOW_VALUE):
        return 0.0
    return min(1.0, round(score, 3))


def rank_memory_candidates(candidates: list[dict], query: str, k: int = 8) -> list[dict]:
    """Rank already-retrieved memories by relevance plus durable importance."""
    q = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if not q:
        return candidates[:k]

    ranked = []
    for item in candidates:
        text = str(item.get("text") or item.get("event") or item.get("fact") or "")
        toks = set(re.findall(r"[a-z0-9]+", text.lower()))
        overlap = len(q & toks) / max(1, len(q))
        importance = float(item.get("importance", item.get("confidence", 0.5)) or 0.5)
        recency = 0.0
        ts = str(item.get("ts", ""))
        if ts:
            # Cheap date-shape signal; exact time decay remains source-specific.
            recency = 0.05
        score = overlap * 0.75 + min(1.0, importance) * 0.20 + recency
        ranked.append((score, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:k]]


def gate_context(context: str, query: str, max_chars: int = 14000) -> str:
    """Bound recalled context and strip obvious credential-like fragments."""
    if not context:
        return ""
    safe_parts = []
    for part in context.split("\n\n"):
        if is_safe_to_retain(part):
            safe_parts.append(part)
    result = "\n\n".join(safe_parts)
    if len(result) <= max_chars:
        return result
    return result[:max_chars].rsplit(" ", 1)[0] + " [memory context bounded]"
