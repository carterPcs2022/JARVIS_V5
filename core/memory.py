"""
core/memory.py — JARVIS unified memory system.
Short-term (recent turns) + Long-term (vector search) + Profile.
"""
import json, math, re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from config.settings import (SHORT_TERM_FILE, LONG_TERM_FILE,
                              CONVERSATIONS_FILE, PROFILE_FILE,
                              MAX_SHORT_TERM, MAX_LONG_TERM)


def _load(path: Path) -> list | dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        with open(path) as f:
            return json.load(f)
    return [] if "profile" not in path.name else {}


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Short-term memory ─────────────────────────────────────────────────────────

def save_turn(user: str, ai: str):
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


def get_short_term(n: int = 10) -> list[dict]:
    return _load(SHORT_TERM_FILE)[-n:]


def get_context_string(n: int = 10) -> str:
    turns = get_short_term(n)
    return "\n".join(f"User: {t['user']}\nJARVIS: {t['ai']}" for t in turns)


def _append_conversation(user: str, ai: str):
    convs = _load(CONVERSATIONS_FILE)
    convs.append({
        "user": user, "ai": ai,
        "ts": datetime.now().isoformat()
    })
    _save(CONVERSATIONS_FILE, convs[-5000:])


# ── Long-term memory (TF-IDF vector search) ───────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def store_long_term(user: str, ai: str, tags: list[str] | None = None):
    entries = _load(LONG_TERM_FILE)
    text = f"{user} {ai}"
    entries.append({
        "ts":     datetime.now().isoformat(),
        "user":   user,
        "ai":     ai,
        "tags":   tags or [],
        "tokens": _tokenize(text),
    })
    _save(LONG_TERM_FILE, entries[-MAX_LONG_TERM:])


def recall(query: str, k: int = 5) -> list[dict]:
    entries = _load(LONG_TERM_FILE)
    if not entries:
        return []

    q_tokens = _tokenize(query)
    df = defaultdict(int)
    for e in entries:
        for t in set(e.get("tokens", [])):
            df[t] += 1
    N = len(entries)
    idf = {t: math.log(N / (v + 1)) for t, v in df.items()}

    def score(e):
        toks = e.get("tokens", [])
        tf = defaultdict(int)
        for t in toks:
            tf[t] += 1
        return sum(
            (tf[t] / max(len(toks), 1)) * idf.get(t, 0)
            for t in q_tokens
        )

    ranked = sorted(entries, key=score, reverse=True)
    return ranked[:k]


def recall_as_context(query: str) -> str:
    hits = recall(query)
    if not hits:
        return ""
    lines = ["[Relevant past conversations:]"]
    for h in hits:
        lines.append(f"  [{h['ts'][:10]}] User: {h['user'][:100]}")
        lines.append(f"            JARVIS: {h['ai'][:200]}")
    return "\n".join(lines)


def check_if_repeated(query: str, threshold: float = 0.75) -> dict | None:
    """Has the user asked essentially this before? Compares token-set overlap
    (Jaccard similarity) against past user messages specifically — recall()
    is TF-IDF relevance for general context, which isn't the same question as
    "is this literally a repeat." Returns the most similar past entry (with
    a computed 'similarity' and 'days_ago') if above threshold, else None."""
    entries = _load(LONG_TERM_FILE)
    if not entries:
        return None

    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return None

    best_entry, best_sim = None, 0.0
    for e in entries:
        user_tokens = set(_tokenize(e.get("user", "")))
        if not user_tokens:
            continue
        intersection = len(q_tokens & user_tokens)
        union = len(q_tokens | user_tokens)
        sim = intersection / union if union else 0.0
        if sim > best_sim:
            best_sim, best_entry = sim, e

    if not best_entry or best_sim < threshold:
        return None

    try:
        days_ago = (datetime.now() - datetime.fromisoformat(best_entry["ts"])).days
    except Exception:
        days_ago = None

    return {**best_entry, "similarity": round(best_sim, 3), "days_ago": days_ago}


# ── Profile ───────────────────────────────────────────────────────────────────

def get_profile() -> dict:
    return _load(PROFILE_FILE)


def update_profile(updates: dict):
    profile = get_profile()
    profile.update(updates)
    profile["last_updated"] = datetime.now().isoformat()
    _save(PROFILE_FILE, profile)


def memory_stats() -> dict:
    short = _load(SHORT_TERM_FILE)
    long  = _load(LONG_TERM_FILE)
    convs = _load(CONVERSATIONS_FILE)
    return {
        "short_term_turns":    len(short),
        "long_term_memories":  len(long),
        "total_conversations": len(convs),
        "profile_keys":        list(get_profile().keys()),
    }


def clear_short_term():
    _save(SHORT_TERM_FILE, [])


# ── Conversation compression ───────────────────────────────────────────────────

def compress_if_needed(threshold: int = 50):
    """Auto-compress memory every N turns to keep context sharp."""
    turns = _load(SHORT_TERM_FILE)
    if len(turns) < threshold:
        return

    try:
        from core.llm.router import think
        sample = turns[-threshold:]
        text   = "\n".join(f"User: {t['user']}\nJARVIS: {t['ai']}" for t in sample)
        prompt = (
            "Summarize these conversation turns into key facts, decisions, and topics. "
            "Be concise — this will be stored as a long-term memory. Max 300 words.\n\n" + text
        )
        summary = think(prompt, max_tokens=400)
        store_long_term("[COMPRESSION]", summary, tags=["compression", "auto"])

        # Keep only the most recent 10 turns
        _save(SHORT_TERM_FILE, turns[-10:])
        import logging
        logging.getLogger(__name__).info("Memory compressed: %d turns → summary", threshold)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Compression failed: %s", e)


def get_compression_summary() -> str | None:
    entries = _load(LONG_TERM_FILE)
    for entry in reversed(entries):
        if "compression" in entry.get("tags", []):
            return entry.get("ai", "")
    return None
