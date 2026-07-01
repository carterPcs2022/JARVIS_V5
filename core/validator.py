"""
core/validator.py — JARVIS response validator.
Ensures responses are safe, sensible, and complete before delivery.
"""
import re

_INCOMPLETE_PATTERNS = [
    r"\.\.\.$", r"and so on$", r"etc\.$", r"\[continued\]",
    r"I'll continue", r"to be continued", r"\[truncated\]",
]
_ERROR_PATTERNS = [
    r"\[JARVIS OFFLINE\]", r"All LLM providers failed",
    r"Agent error:", r"\[Dream error:",
]


def validate(response: str, query: str = "") -> dict:
    """
    Validate a response before sending to user.
    Returns: {valid, issues, response}
    """
    issues = []

    if not response or len(response.strip()) < 5:
        issues.append("empty_response")

    if len(response) > 8000:
        response = response[:8000] + "\n\n[Response truncated for length]"
        issues.append("truncated")

    for pattern in _INCOMPLETE_PATTERNS:
        if re.search(pattern, response, re.I):
            issues.append("appears_incomplete")
            break

    for pattern in _ERROR_PATTERNS:
        if re.search(pattern, response, re.I):
            issues.append("contains_error_marker")
            break

    # Strip leading/trailing whitespace
    response = response.strip()

    return {
        "valid":    len([i for i in issues if i not in ("truncated",)]) == 0,
        "issues":   issues,
        "response": response,
    }


# ── Confidence & Honesty Engine ───────────────────────────────────────────────

_HEDGE_PATTERNS = [
    r"\bi\s+think\b", r"\bi\s+believe\b", r"\bprobably\b", r"\bmaybe\b",
    r"\bmight\b", r"\bcould\s+be\b", r"\bnot\s+sure\b", r"\buncertain\b",
    r"\bapproximately\b", r"\baround\b", r"\broughly\b", r"\bpossibly\b",
]

_STALE_KW = {
    "current", "today", "now", "latest", "recent", "price", "score",
    "live", "right now", "this week", "2024", "2025", "2026",
}


def score_confidence(query: str, response: str) -> int:
    score = 85  # start optimistic

    # Hedging language in response
    for pat in _HEDGE_PATTERNS:
        if re.search(pat, response, re.I):
            score -= 8

    # Time-sensitive query
    q_low = query.lower()
    if any(kw in q_low for kw in _STALE_KW):
        score -= 15

    # Error markers
    if any(re.search(p, response, re.I) for p in _ERROR_PATTERNS):
        score -= 40

    # Short response to a complex query
    if len(query.split()) > 8 and len(response.split()) < 20:
        score -= 10

    return max(0, min(100, score))


def add_confidence_marker(response: str, score: int) -> str:
    if score >= 70:
        return response
    if score >= 40:
        return f"I'm not certain, but — {response}"
    return f"This is my best guess — verify this: {response}"
