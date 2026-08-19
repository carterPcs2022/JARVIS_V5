"""core/interfaces/permissions.py — a shared pending-action store for any
Tool with requires_confirmation=True.

Generalizes the pattern core/tools/gmail_send.py already proved out for
one tool (draft_email() stores a pending action; only a separate, explicit
send_pending_draft() call executes it; unconfirmed drafts expire): propose
an action, get back an id; a later, explicit confirm(id) call is the only
way it actually runs.

gmail_send.py itself is NOT migrated to use this — it already works
correctly and rewiring proven, correct code onto shared infrastructure for
its own sake isn't worth the regression risk. This exists for every other
tool that gets requires_confirmation=True going forward.

In-memory only (module-level dict), not persisted like gmail_send.py's
file-backed draft — fine for this module's actual callers (see
core/mac_dispatcher.py), which propose and confirm within the same
process's lifetime; a restart losing an unconfirmed pending action (e.g.
"empty the trash") is the safe failure direction anyway.
"""
from __future__ import annotations
import time
import uuid

_PENDING: dict[str, dict] = {}
EXPIRY_SECONDS = 600   # matches gmail_send.py's _DRAFT_EXPIRY_SECONDS


def propose(tool_name: str, args: dict) -> dict:
    """Records a pending action and returns its descriptor (including the
    id a caller must pass back to confirm() or discard())."""
    pending_id = uuid.uuid4().hex[:12]
    entry = {"id": pending_id, "tool": tool_name, "args": args, "created": time.time()}
    _PENDING[pending_id] = entry
    return entry


def get_pending(pending_id: str) -> dict | None:
    """None if unknown or expired (expired entries are cleaned up as a
    side effect of checking, same convention as gmail_send.get_pending_draft())."""
    entry = _PENDING.get(pending_id)
    if not entry:
        return None
    if time.time() - entry["created"] > EXPIRY_SECONDS:
        _PENDING.pop(pending_id, None)
        return None
    return entry


def confirm(pending_id: str) -> dict | None:
    """Returns and removes the pending entry if it exists and hasn't
    expired — the caller is expected to actually execute it immediately
    after. None means there was nothing valid to confirm."""
    entry = get_pending(pending_id)
    if entry:
        _PENDING.pop(pending_id, None)
    return entry


def discard(pending_id: str) -> bool:
    return _PENDING.pop(pending_id, None) is not None
