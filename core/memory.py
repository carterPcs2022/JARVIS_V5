"""
core/memory.py — JARVIS unified memory system.
Short-term (recent turns) + Long-term (vector search) + Profile.
"""
import json, logging, math, re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from config.settings import (SHORT_TERM_FILE, LONG_TERM_FILE,
                              CONVERSATIONS_FILE, PROFILE_FILE,
                              MAX_SHORT_TERM, MAX_LONG_TERM)

log = logging.getLogger(__name__)


def _turso_key(path: Path) -> str:
    from config.settings import BASE_DIR
    return str(path.relative_to(BASE_DIR)) if path.is_absolute() else str(path)


def _write_local_cache(path: Path, data) -> None:
    """Best-effort local cache write after a successful durable read.

    Render's filesystem is ephemeral, so Turso remains authoritative. The
    local copy is still useful as a fast/offline fallback if Turso becomes
    temporarily unreachable later in the same process lifetime.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.debug("Could not refresh local memory cache %s: %s", path, e)


def _load(path: Path) -> list | dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    default = [] if "profile" not in path.name else {}

    # Turso first — it's the durable copy on Render's ephemeral disk.
    # Falls through to the local file below on any failure (not
    # configured, network error, or a malformed row), same as before this
    # existed; the local file is a working cache/fallback, not just dead
    # weight kept for compatibility.
    from core.turso_store import get as turso_get
    remote = turso_get(_turso_key(path))
    if remote is not None:
        # Seed the local cache when a redeploy restored memory from Turso but
        # the ephemeral filesystem has no copy yet. This makes the fallback
        # path useful for the rest of the process without changing Turso's
        # role as the source of truth.
        if not path.exists() or path.stat().st_size == 0:
            _write_local_cache(path, remote)
        return remote

    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            # A truncated/corrupted file (e.g. from a crash mid-write)
            # must not take down every caller of this — this is the
            # foundational loader for the whole memory system. But silently
            # returning an empty default let a month of wiped-disk data loss
            # go unnoticed — log loudly so it surfaces instead.
            log.error("Memory file corrupted, treating as empty: %s (%s)", path, e)
            return default
    if not path.exists():
        # A missing file is normal on a fresh Render instance: durable memory
        # may simply have no row yet. _save() creates it on first write.
        # Keep that expected bootstrap quiet; Turso itself already logs a
        # real connectivity failure when applicable.
        log.debug("Memory file not initialized yet: %s", path)
    return default


def _save(path: Path, data) -> bool:
    """Returns whether the Turso mirror write actually succeeded — not
    just whether Turso is configured (TURSO_DATABASE_URL/AUTH_TOKEN
    present), which was the bug found while building notes: env vars can
    be set while the actual write still silently falls back to local-only
    (e.g. libsql_client not installed), and every existing caller of
    _save() ignored this return value anyway, so exposing it doesn't
    change their behavior — only a caller that wants to make an accurate
    "did this actually persist durably" claim needs to look at it. See
    core.memory.store_note()'s docstring for why this specific caller
    can't just trust core.turso_store.is_configured() the way earlier
    code implicitly assumed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    # Mirror to Turso so this survives the next Render redeploy — the
    # local write above still happens unconditionally, so a Turso outage
    # degrades to "doesn't persist across redeploys right now" rather
    # than losing the write entirely.
    from core.turso_store import put as turso_put
    return turso_put(_turso_key(path), data)


# ── Short-term memory ─────────────────────────────────────────────────────────

def save_turn(user: str, ai: str):
    # Protocol 26 — Shield: redact credit cards/SSNs/passwords/API keys
    # before anything ever touches disk.
    try:
        from core.protocols import shield
        user = shield.scan_and_redact(user)
        ai   = shield.scan_and_redact(ai)
    except Exception:
        pass

    turns = _load(SHORT_TERM_FILE)
    turns.append({
        "user": user, "ai": ai,
        "ts": datetime.now().isoformat()
    })
    turns = turns[-MAX_SHORT_TERM:]
    _save(SHORT_TERM_FILE, turns)
    _append_conversation(user, ai)
    # Auto-compress every 50 turns
    if len(turns) >= MAX_SHORT_TERM:
        compress_if_needed(threshold=MAX_SHORT_TERM)

    # Semantic memory (facts) was built (extract_facts(), store_fact(),
    # recall_facts(), all wired into universal_recall() for context) but
    # nothing in the live chat pipeline ever called extract_facts() — it
    # only ran from a manual REST endpoint nobody hits, and from
    # core/orchestrator.py, which isn't the live pipeline either (that's
    # core/brain_v2.py). save_turn() is the one choke point every real
    # conversation turn already passes through exactly once, so this is the
    # correct place to wire it rather than adding a call at every one of
    # brain_v2.py's dozen+ save_turn() call sites individually.
    # Backgrounded (extract_facts() has its own cheap keyword pre-check
    # before it ever calls an LLM, but even that pre-check plus the
    # occasional real call shouldn't add latency to the response path the
    # user is waiting on).
    try:
        import threading
        threading.Thread(target=_auto_extract_facts, args=(user,), daemon=True).start()
    except Exception:
        pass

    # Working memory (core/working_memory.py) — active per-turn attention,
    # a salience-ranked scratchpad get_relevant(query) can search by
    # content, distinct from get_context_string()'s FIFO "last N raw
    # turns" above. save_turn() is the same real choke point already used
    # for fact extraction, for the same reason (every real turn passes
    # through here exactly once). No LLM call, matching
    # core/working_memory.py's own "Free" design — importance is a cheap
    # heuristic (longer messages tend to carry more substance than a bare
    # "ok"/"thanks"), not a judgment call worth spending a model call on.
    try:
        from core.working_memory import working_mem
        key = f"turn_{datetime.now().strftime('%H%M%S%f')}"
        importance = min(1.0, 0.3 + len(user.split()) / 40)
        working_mem.hold(key, user, importance=importance)
    except Exception:
        pass


def _auto_extract_facts(user_text: str):
    try:
        for fact in extract_facts(user_text):
            store_fact(fact, source="conversation")
    except Exception as e:
        log.warning("Background fact extraction failed: %s", e)


# ── The remainder of this module is unchanged below this point. ─────────────
