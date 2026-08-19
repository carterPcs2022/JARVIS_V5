"""core/interfaces/verification.py — the Verification Engine: did an
action actually succeed, not just "ran without a Python exception"?

Nothing in V5 does this today. core/validator.py validates response TEXT
QUALITY (empty, truncated, contains an error marker) and scores confidence
from linguistic heuristics — genuinely different from "did the tool call
achieve its goal." docs/AUDIT.md's audit findings include several real
fabrication bugs that were exactly this gap: a Python-level success (no
exception) papering over a real failure the handler itself reported
through its return value — a fabricated Windows system report, a
fabricated "note saved permanently" when it wasn't, and more, per
core/brain_v2.py's inline comments about incidents this exact class of bug
caused.

This module works generically off an existing, real, already-consistent
convention: every core/tools/*.py handler that fails reports it either as
{"error": "..."} (dict-returning tools) or a "[Xxx error: ...]" /
"[Error] ..." wrapped string (text-returning tools) — confirmed by
grepping every such tool. verify_tool_result() detects that convention
rather than inventing a new one, so it works for the tools that already
follow it without requiring each one to be rewritten.

Scope (see docs/AUDIT.md §11 for why): wired into core/executor.py's
execute_step() only — the one dispatcher where a chain of tool calls
(core/react.py, core/agents/planner_agent.py) making decisions off each
previous call's reported "success" makes an undetected fabricated success
most dangerous. Not wired into core/mac_dispatcher.py or
core/tool_calling.py's dispatch loops in this phase.

Retry/rollback: "Never endlessly retry" (V6's own engineering rules) —
with_retry() enforces a hard attempt cap and exponential backoff. Retry is
only ever recommended for errors that look transient (timeout, connection,
rate limit) AND tools marked reversible=True in the Tool registry — a
permanent failure (e.g. run_shell's "not in allowlist") or a
non-reversible tool never gets auto-retried. Rollback is NOT attempted
generically here — there is no safe, automatic way to "undo" most of
JARVIS's ~40 tools (you can't un-send a notification), and the one real
rollback mechanism that exists (core/sandbox.py's file backup/restore) is
scoped to code self-modification, a different subsystem. A
VerificationResult can still recommend "rollback" as a signal; actually
performing one is left to whichever caller has a real mechanism for that
specific action.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class VerificationResult:
    success: bool
    confidence: float = 0.5           # 0.0-1.0
    evidence: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recommended_action: str | None = None   # None | "retry" | "rollback" | "ask_user"


# Matches the [Xxx error: ...] / [Error] ... convention already used
# consistently across core/tools/*.py (browser.py, files.py, mac.py,
# vision.py, voice.py) for text-returning handlers, PLUS the two markers
# core/validator.py's own _ERROR_PATTERNS already treats as failures
# ("[JARVIS OFFLINE] ..." / "All LLM providers failed" — core.llm.router's
# literal fallback text, which doesn't itself contain the word "error" so
# the [Xxx error...] pattern alone would miss it).
_TEXT_ERROR_RE = re.compile(
    r"^\[[A-Za-z ]*[Ee]rror[^\]]*\]|^\[JARVIS OFFLINE\]|All LLM providers failed"
)

# Substrings that make an error look transient/worth one retry — narrow
# and conservative on purpose: anything not matched here is treated as
# permanent (e.g. "not in allowlist", "not configured", "not found",
# "path outside allowed area" are all deterministic — retrying changes
# nothing and just wastes an attempt).
_TRANSIENT_MARKERS = (
    "timed out", "timeout", "connection refused", "connection reset",
    "temporarily unavailable", "rate limit", "429", "could not reach",
    "network", "connection error",
)


def _extract_error(raw_output: Any) -> str | None:
    """None if `raw_output` doesn't look like one of core/tools/*.py's two
    error conventions; otherwise the error message."""
    if isinstance(raw_output, dict):
        return raw_output.get("error")
    if isinstance(raw_output, list) and raw_output and isinstance(raw_output[0], dict):
        return raw_output[0].get("error")
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
    """Generic outcome verification for anything a Tool handler returns.
    Does NOT know what the tool was supposed to accomplish beyond "did its
    own return value report success" — this catches the "no exception, but
    the handler's own output says it failed" class of bug; it cannot catch
    a handler that reports success while having done nothing (that needs a
    tool-specific verifier, out of scope here — see module docstring)."""
    error = _extract_error(raw_output)
    if error is None:
        return VerificationResult(success=True, confidence=0.8, evidence=[str(raw_output)[:200]])

    transient = is_transient(error)
    return VerificationResult(
        success=False,
        confidence=0.9,   # high confidence that this genuinely failed — the
                          # handler itself said so, not an inference
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
    """Calls fn(), verifies the result, and retries with exponential
    backoff ONLY when verify() recommends "retry" — never for "ask_user",
    "rollback", or None, and never past max_attempts regardless. Returns
    the last (result, VerificationResult) pair, success or not — callers
    decide what to do with a final failure; this never raises on a failed
    verification, only on fn() itself raising (matching the codebase's
    "degrade gracefully, don't crash" convention, but still surfacing the
    real error rather than swallowing it)."""
    result: T
    verdict: VerificationResult
    for attempt in range(1, max_attempts + 1):
        result = fn()
        verdict = verify(result)
        if verdict.success or verdict.recommended_action != "retry" or attempt == max_attempts:
            return result, verdict
        time.sleep(backoff_base * (2 ** (attempt - 1)))
    return result, verdict  # pragma: no cover — loop always returns above
