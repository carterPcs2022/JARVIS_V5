"""core/ask_user_choice.py — lets JARVIS pause and ask the user to pick
from a short list of options instead of guessing, for genuine
preference/disambiguation moments (e.g. "which Home Assistant scene did
you mean").

Two ways this gets triggered, both funnel through propose() below so
there is exactly one canonical pending-choice shape:

1. The model itself emits a fenced ```ask_user_choice JSON block``` in
   its ordinary response text (taught via JARVIS_PERSONALITY in
   core/llm/router.py). core/brain_v2.py's Executor detects it with
   extract_marker() after every response, strips it from what the user
   sees, and calls propose() on the parsed content. This works
   regardless of which reasoning path produced the text — there's no
   native tool-calling in core/llm/router.py's chat()/think() to hook
   into (confirmed: neither takes a tools/tool_choice parameter), so a
   sentinel-marker convention is used instead, the same way this
   codebase already signals other things through response text
   (`[JARVIS OFFLINE]`, bracket-prefixed tool errors).

2. core/mac_dispatcher.py's own tool-dispatch JSON convention — the one
   tool-selection mechanism actually wired into live mac_control traffic
   — has an `ask_user_choice` entry that calls propose() directly. This
   is the path for e.g. "which Home Assistant scene did you mean".

Deliberately excluded: nothing here is reachable from
core/protocols.py's Lockdown/Coldfire/Scatter/Endgame confirmation flow.
classify_protocol_request() already intercepts and refuses chat-based
attempts to fake those confirmations before Executor ever runs — this
module must never become a way to dress up that flow as a "pick an
option" prompt.

State is a single global slot (not per-session), matching this app's own
documented assumption elsewhere (server/api.py: single uvicorn worker,
in-memory state is safe without cross-process sync) and the existing
precedent for this kind of "pending, resumed by the next turn" state —
core/tools/gmail_send.py's single-slot pending email draft. Any reply
consumes the pending choice, matched or not, rather than leaving it
dangling — same convention gmail_send.py itself follows for confirm/
discard.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

MARKER_TAG = "ask_user_choice"
_MARKER_RE = re.compile(
    r"```[ \t]*" + re.escape(MARKER_TAG) + r"[ \t]*\r?\n(.*?)```",
    re.IGNORECASE | re.DOTALL,
)

MAX_QUESTIONS = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_QUESTION_LEN = 300
MAX_OPTION_LEN = 80

# Short-lived — this is a same-conversation follow-up, not a durable
# draft. 5 minutes gives a real person time to read and reply without
# leaving a stale question hanging around across an unrelated topic
# change for long.
_PENDING_TTL_SECONDS = 300

_pending: dict[str, Any] | None = None
_pending_ts: float = 0.0


def _clean_str(s: Any, max_len: int) -> str:
    if not isinstance(s, str):
        return ""
    return " ".join(s.split())[:max_len].strip()


def _validate_questions(questions_raw: Any) -> list[dict[str, Any]]:
    """Defensive validation/truncation — never trust the model (or a
    tool caller) to have actually respected the cap. Silently drops
    anything malformed rather than raising, so a bad marker degrades to
    "no pending choice" instead of breaking the turn."""
    if not isinstance(questions_raw, list):
        return []

    validated: list[dict[str, Any]] = []
    for q in questions_raw[:MAX_QUESTIONS]:
        if not isinstance(q, dict):
            continue
        question_text = _clean_str(q.get("question"), MAX_QUESTION_LEN)
        if not question_text:
            continue

        raw_options = q.get("options")
        if not isinstance(raw_options, list):
            continue
        options: list[str] = []
        for opt in raw_options[:MAX_OPTIONS]:
            cleaned = _clean_str(opt, MAX_OPTION_LEN)
            if cleaned and cleaned not in options:
                options.append(cleaned)
        if len(options) < MIN_OPTIONS:
            continue

        validated.append({
            "question": question_text,
            "options": options,
            "allow_multiple": bool(q.get("allow_multiple", False)),
        })

    return validated


def propose(questions_raw: Any) -> dict[str, Any] | None:
    """Validate + store a new pending choice, replacing any existing
    one. Returns the canonical stored shape, or None if nothing valid
    survived validation (in which case nothing is stored)."""
    global _pending, _pending_ts

    questions = _validate_questions(questions_raw)
    if not questions:
        return None

    _pending = {"id": uuid.uuid4().hex[:12], "questions": questions}
    _pending_ts = time.time()
    return dict(_pending)


def get_pending() -> dict[str, Any] | None:
    """Returns the current pending choice, or None if there isn't one
    or it expired. Expiry is checked (and cleared) here so callers never
    need to reason about TTL themselves."""
    global _pending, _pending_ts
    if _pending is None:
        return None
    if time.time() - _pending_ts > _PENDING_TTL_SECONDS:
        _pending = None
        return None
    return dict(_pending)


def clear_pending() -> None:
    global _pending
    _pending = None


def _flat_options(pending: dict[str, Any]) -> list[tuple[int, str, str]]:
    """(question_index, option_text) for every option, in a single flat
    list numbered 1..N across ALL questions — so "reply with a number"
    stays unambiguous even when more than one question was asked."""
    flat = []
    for q_idx, q in enumerate(pending["questions"]):
        for opt in q["options"]:
            flat.append((q_idx, opt))
    return [(i + 1, q_idx, opt) for i, (q_idx, opt) in enumerate(flat)]


def format_fallback_text(pending: dict[str, Any]) -> str:
    """Plain numbered-list rendering for any channel that can't render
    buttons (voice, Telegram, SMS, glasses, or a web client that hasn't
    picked up the pending_choice field) — global numbering matching
    _flat_options() so a numeric reply resolves unambiguously."""
    lines: list[str] = []
    numbered = _flat_options(pending)
    multi_q = len(pending["questions"]) > 1
    for q_idx, q in enumerate(pending["questions"]):
        prefix = f"Q{q_idx + 1}: " if multi_q else ""
        suffix = " (you can pick more than one)" if q["allow_multiple"] else ""
        lines.append(f"{prefix}{q['question']}{suffix}")
        for n, opt_q_idx, opt in numbered:
            if opt_q_idx == q_idx:
                lines.append(f"  {n}. {opt}")
        lines.append("")
    lines.append("Reply with a number (or the option text).")
    return "\n".join(lines).rstrip()


def extract_marker(text: str) -> tuple[str, dict[str, Any] | None]:
    """Find and strip a ```ask_user_choice fenced block from `text`.
    Returns (display_text_with_block_removed, parsed_dict_or_None).
    A malformed JSON block is still stripped (never shown to the user
    raw) but parses to None, so it degrades to "no pending choice"
    rather than leaking broken JSON or breaking the turn."""
    if not text or MARKER_TAG not in text:
        return text, None

    match = _MARKER_RE.search(text)
    if not match:
        return text, None

    cleaned = (text[: match.start()] + text[match.end():]).strip()
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("ask_user_choice: malformed marker JSON, dropping it: %s", e)
        return cleaned, None

    if not isinstance(parsed, dict) or "questions" not in parsed:
        return cleaned, None

    return cleaned, parsed


def resolve_reply(pending: dict[str, Any], user_text: str) -> str | None:
    """Deterministically match a free-text reply against the pending
    choice's options — numeric index (global, matching
    format_fallback_text's numbering), comma/'and'-separated multiple
    indices, or exact/substring text match against an option. Returns a
    human-readable summary to feed back into the LLM as context, or None
    if nothing matched (caller clears the pending choice regardless —
    any reply consumes it, matched or not)."""
    numbered = _flat_options(pending)
    by_index = {n: (q_idx, opt) for n, q_idx, opt in numbered}

    matched: dict[int, list[str]] = {}  # question_index -> [chosen option, ...]

    tokens = [t.strip() for t in re.split(r"[,\n]|(?:\band\b)", user_text, flags=re.IGNORECASE) if t.strip()]
    for token in tokens:
        # Pull a leading integer out of e.g. "2" or "2." or "option 2"
        num_match = re.search(r"\b(\d+)\b", token)
        if num_match:
            n = int(num_match.group(1))
            if n in by_index:
                q_idx, opt = by_index[n]
                matched.setdefault(q_idx, []).append(opt)
                continue
        # Fall back to matching the option text itself
        token_lower = token.lower()
        for n, q_idx, opt in numbered:
            if token_lower == opt.lower() or (len(token_lower) >= 3 and token_lower in opt.lower()):
                matched.setdefault(q_idx, []).append(opt)
                break

    if not matched:
        # Whole-message substring match, for a reply that's just the
        # option itself with no number (e.g. "focus" or "the focus one")
        user_lower = user_text.lower()
        for n, q_idx, opt in numbered:
            if opt.lower() in user_lower:
                matched.setdefault(q_idx, []).append(opt)

    if not matched:
        return None

    parts = []
    for q_idx, q in enumerate(pending["questions"]):
        if q_idx not in matched:
            continue
        choices = matched[q_idx] if q["allow_multiple"] else matched[q_idx][:1]
        # de-dupe while preserving order
        seen: set[str] = set()
        choices = [c for c in choices if not (c in seen or seen.add(c))]
        parts.append(f"For \"{q['question']}\": {', '.join(choices)}")

    if not parts:
        return None
    return "User answered the pending question(s) — " + "; ".join(parts)
