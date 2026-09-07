"""Verification helpers for JARVIS tool outcomes.

Verification is deliberately separate from response-text validation: a tool
can run without raising an exception while still returning a real failure.
The helpers below detect the error conventions already used by JARVIS tools
and provide bounded retry behavior for reversible transient failures.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass
class VerificationResult:
    success: bool
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recommended_action: str | None = None


_TEXT_ERROR_RE = re.compile(
    r"^\[[A-Za-z ]*[Ee]rror[^\]]*\]|^\[JARVIS OFFLINE\]|All LLM providers failed"
)

_TRANSIENT_MARKERS = (
    "timed out", "timeout", "connection refused", "connection reset",
    "temporarily unavailable", "rate limit", "429", "could not reach",
    "network", "connection error",
)


def _extract_error(raw_output: Any) -> str | None:
    """Return an error message when a tool result follows a known convention."""
    if isinstance(raw_output, dict):
        error = raw_output.get("error")
        return str(error) if error else None
    if isinstance(raw_output, list) and raw_output and isinstance(raw_output[0], dict):
        error = raw_output[0].get("error")
        return str(error) if error else None
    if isinstance(raw_output, str):
        text = raw_output.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _extract_error(json.loads(text))
            except Exception:
                pass
        m = _TEXT_ERROR_RE.match(text)
        if m:
            return text
    return None


def is_transient(error_message: str) -> bool:
    low = error_message.lower()
    return any(marker in low for marker in _TRANSIENT_MARKERS)


def verify_tool_result(raw_output: Any, *, reversible: bool = True) -> VerificationResult:
    """Verify a tool's reported outcome without pretending to know its goal.

    This catches the important "no Python exception, but the handler reported
    failure" case. Tool-specific postconditions remain the responsibility of
    the tool that knows what success actually means.
    """
    error = _extract_error(raw_output)
    if error is None:
        return VerificationResult(
            success=True,
            confidence=0.8,
            evidence=[str(raw_output)[:200]],
        )

    transient = is_transient(error)
    return VerificationResult(
        success=False,
        confidence=0.9,
        errors=[error],
        recommended_action=("retry" if (transient and reversible) else "ask_user"),
    )


def with_retry(
    fn: Callable[[], T],
    *,
    verify: Callable[[T], VerificationResult],
    max_attempts: int = 3,
    backoff_base: float = 0.5,
) -> tuple[T, VerificationResult]:
    """Bounded synchronous retry for reversible transient failures."""
    result: T
    verdict: VerificationResult
    for attempt in range(1, max_attempts + 1):
        result = fn()
        verdict = verify(result)
        if verdict.success or verdict.recommended_action != "retry" or attempt == max_attempts:
            _record_outcome(verdict.success)
            return result, verdict
        _record_outcome(None)
        time.sleep(backoff_base * (2 ** (attempt - 1)))
    _record_outcome(verdict.success)  # pragma: no cover
    return result, verdict


async def async_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    verify: Callable[[T], VerificationResult],
    max_attempts: int = 3,
    backoff_base: float = 0.5,
) -> tuple[T, VerificationResult]:
    """Bounded async retry counterpart used by async tool-calling loops."""
    result: T
    verdict: VerificationResult
    for attempt in range(1, max_attempts + 1):
        result = await fn()
        verdict = verify(result)
        if verdict.success or verdict.recommended_action != "retry" or attempt == max_attempts:
            _record_outcome(verdict.success)
            return result, verdict
        _record_outcome(None)
        await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))
    _record_outcome(verdict.success)  # pragma: no cover
    return result, verdict


def _record_outcome(success: bool | None):
    try:
        from services.metrics import record_verification
        record_verification("retry" if success is None else ("success" if success else "failure"))
    except Exception:
        pass
