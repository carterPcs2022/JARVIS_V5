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

    from core.turso_store import put as turso_put
    return turso_put(_turso_key(path), data)


# ── Short-term memory ─────────────────────────────────────────────────────────

def save_turn(user: str, ai: str):
    # Redaction is a safety boundary, so silently bypassing it is not
    # acceptable. If the shield cannot load, fail closed rather than storing
    # an unredacted conversation turn.
    from core.protocols import shield
    user = shield.scan_and_redact(user)
    ai   = shield.scan_and_redact(ai)

    turns = _load(SHORT_TERM_FILE)
    turns.append({
        "user": user, "ai": ai,
        "ts": datetime.now().isoformat()
    })
    turns = turns[-MAX_SHORT_TERM:]
    _save(SHORT_TERM_FILE, turns)
    _append_conversation(user, ai)
    if len(turns) >= MAX_SHORT_TERM:
        compress_if_needed(threshold=MAX_SHORT_TERM)

    try:
        import threading
        threading.Thread(target=_auto_extract_facts, args=(user,), daemon=True).start()
    except Exception:
        pass

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
    entry = {
        "ts":     datetime.now().isoformat(),
        "user":   user,
        "ai":     ai,
        "tags":   tags or [],
        "tokens": _tokenize(text),
    }
    try:
        from core.llm.embeddings import embed
        vector = embed(text, input_type="document")
        if vector:
            entry["embedding"] = vector
    except Exception:
        pass
    entries.append(entry)
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

    def tfidf_score(e):
        toks = e.get("tokens", [])
        tf = defaultdict(int)
        for t in toks:
            tf[t] += 1
        return sum((tf[t] / max(len(toks), 1)) * idf.get(t, 0) for t in q_tokens)

    q_vector = None
    try:
        from core.llm.embeddings import embed, cosine_similarity
        q_vector = embed(query, input_type="query")
    except Exception:
        pass

    def score(e):
        s = tfidf_score(e)
        if q_vector and e.get("embedding"):
            s += cosine_similarity(q_vector, e["embedding"])
        return s

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


def backfill_embeddings(batch_size: int = 1000) -> dict:
    entries = _load(LONG_TERM_FILE)
    missing = [e for e in entries if not e.get("embedding")]
    if not missing:
        return {"total": len(entries), "backfilled": 0, "skipped": 0}

    from core.llm.embeddings import embed_batch
    backfilled = 0
    for i in range(0, len(missing), batch_size):
        chunk = missing[i:i + batch_size]
        texts = [f"{e.get('user', '')} {e.get('ai', '')}" for e in chunk]
        vectors = embed_batch(texts, input_type="document")
        for e, v in zip(chunk, vectors):
            if v:
                e["embedding"] = v
                backfilled += 1

    _save(LONG_TERM_FILE, entries)
    return {"total": len(entries), "backfilled": backfilled, "skipped": len(missing) - backfilled}


def check_if_repeated(query: str, threshold: float = 0.75) -> dict | None:
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
        "short_term_turns": len(short),
        "long_term_memories": len(long),
        "total_conversations": len(convs),
        "profile_keys": list(get_profile().keys()),
    }


def clear_short_term():
    _save(SHORT_TERM_FILE, [])


# ── Conversation compression ───────────────────────────────────────────────────

def compress_if_needed(threshold: int = 50):
    turns = _load(SHORT_TERM_FILE)
    if len(turns) < threshold:
        return
    try:
        from core.llm.router import think
        sample = turns[-threshold:]
        text = "\n".join(f"User: {t['user']}\nJARVIS: {t['ai']}" for t in sample)
        prompt = ("Summarize these conversation turns into key facts, decisions, and topics. "
                  "Be concise — this will be stored as a long-term memory. Max 300 words.\n\n" + text)
        summary = think(prompt, max_tokens=400)
        store_long_term("[COMPRESSION]", summary, tags=["compression", "auto"])
        _save(SHORT_TERM_FILE, turns[-10:])
        logging.getLogger(__name__).info("Memory compressed: %d turns → summary", threshold)
    except Exception as e:
        logging.getLogger(__name__).warning("Compression failed: %s", e)


def get_compression_summary() -> str | None:
    entries = _load(LONG_TERM_FILE)
    for entry in reversed(entries):
        if "compression" in entry.get("tags", []):
            return entry.get("ai", "")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Six-type memory architecture (working/short-term already exists above)
# ═══════════════════════════════════════════════════════════════════════════

from config.settings import BASE_DIR

_EPISODIC_FILE = BASE_DIR / "memory" / "episodic.json"
_SEMANTIC_FILE = BASE_DIR / "memory" / "semantic.json"
_PROCEDURAL_FILE = BASE_DIR / "memory" / "procedural.json"
_EMOTIONAL_FILE = BASE_DIR / "memory" / "emotional.json"
_PROSPECTIVE_FILE = BASE_DIR / "memory" / "prospective.json"
_NOTES_FILE = BASE_DIR / "memory" / "notes.json"


def _tfidf_score(q_tokens: list[str], doc_tokens: list[str]) -> float:
    if not doc_tokens:
        return 0.0
    tf = defaultdict(int)
    for t in doc_tokens:
        tf[t] += 1
    return sum(tf.get(t, 0) / len(doc_tokens) for t in q_tokens)


def store_episode(event: str, importance: int = 5, emotions: list[str] | None = None,
                   people: list[str] | None = None, tags: list[str] | None = None) -> dict:
    episodes = _load(_EPISODIC_FILE)
    if not isinstance(episodes, list):
        episodes = []
    episode = {
        "id": str(len(episodes) + 1), "event": event, "ts": datetime.now().isoformat(),
        "importance": max(1, min(10, importance)), "emotions": emotions or [],
        "people": people or [], "tags": tags or [], "tokens": _tokenize(event),
    }
    episodes.append(episode)
    episodes.sort(key=lambda x: x["importance"], reverse=True)
    _save(_EPISODIC_FILE, episodes[:1000])
    return episode


def recall_episodes(query: str, k: int = 3) -> list[dict]:
    episodes = _load(_EPISODIC_FILE)
    if not isinstance(episodes, list) or not episodes:
        return []
    q_tokens = _tokenize(query)
    scored = [(_tfidf_score(q_tokens, ep.get("tokens", [])) * (1 + ep.get("importance", 5) / 10), ep)
              for ep in episodes]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ep for score, ep in scored[:k] if score > 0]


def episodes_as_context(query: str) -> str:
    hits = recall_episodes(query)
    if not hits:
        return ""
    lines = ["[Notable past events:]"]
    for e in hits:
        lines.append(f"  [{e['ts'][:10]}] {e['event']}")
    return "\n".join(lines)


def working_memory_as_context(query: str) -> str:
    try:
        from core.working_memory import working_mem
        return working_mem.get_relevant(query)
    except Exception:
        return ""


def extract_facts(conversation_turn: str) -> list[str]:
    STATEMENT_SIGNS = ("i am", "i'm", "my ", "i have", "i like", "i work",
                       "i live", "i prefer", "i need", "i want")
    low = (conversation_turn or "").lower()
    if not any(s in low for s in STATEMENT_SIGNS):
        return []
    from core.llm.router import think
    result = think(
        f"Extract discrete facts from this text as a JSON array of strings. "
        f"Each fact should be atomic and searchable. If there are no clear "
        f"facts, return an empty array.\n\nText: {conversation_turn}\n\nJSON array only:",
        force_model="instant", use_cache=True,
    )
    try:
        clean = re.sub(r"```json|```", "", result).strip()
        parsed = json.loads(clean)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def get_all_facts(n: int = 200) -> list[str]:
    facts = _load(_SEMANTIC_FILE)
    if not isinstance(facts, list):
        return []
    return [f["fact"] for f in facts[-n:] if f.get("fact")]


def store_fact(fact: str, confidence: float = 0.9, source: str = "conversation",
               category: str = "general") -> dict:
    facts = _load(_SEMANTIC_FILE)
    if not isinstance(facts, list):
        facts = []
    existing = recall_facts(fact, k=1)
    if existing and _contradicts(fact, existing[0]["fact"]):
        for f in facts:
            if f["fact"] == existing[0]["fact"]:
                f["fact"], f["confidence"] = fact, confidence
                f["updated"] = datetime.now().isoformat()
                _save(_SEMANTIC_FILE, facts)
                return f
    entry = {"fact": fact, "confidence": confidence, "source": source, "category": category,
             "ts": datetime.now().isoformat(), "tokens": _tokenize(fact)}
    facts.append(entry)
    _save(_SEMANTIC_FILE, facts[-2000:])
    return entry


def recall_facts(query: str, k: int = 5) -> list[dict]:
    facts = _load(_SEMANTIC_FILE)
    if not isinstance(facts, list) or not facts:
        return []
    q_tokens = _tokenize(query)
    scored = [(_tfidf_score(q_tokens, f.get("tokens", [])) * f.get("confidence", 0.9), f)
              for f in facts]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for score, f in scored[:k] if score > 0]


def facts_as_context(query: str) -> str:
    hits = recall_facts(query)
    if not hits:
        return ""
    lines = ["[Known facts:]"]
    for f in hits:
        lines.append(f"  - {f['fact']}")
    return "\n".join(lines)


def _contradicts(new_fact: str, old_fact: str) -> bool:
    new_tokens, old_tokens = set(_tokenize(new_fact)), set(_tokenize(old_fact))
    if len(new_tokens & old_tokens) < 2:
        return False
    try:
        from core.llm.router import think
        result = think(
            f"Do these two statements contradict each other?\nStatement 1: {old_fact}\nStatement 2: {new_fact}\nReply only: YES or NO",
            force_model="instant", use_cache=True,
        )
        return "YES" in result.upper()
    except Exception:
        return False


def store_procedure(task: str, steps: list[str], success_rate: float = 1.0) -> dict:
    procs = _load(_PROCEDURAL_FILE)
    if not isinstance(procs, list):
        procs = []
    proc = {"task": task, "steps": steps, "success_rate": success_rate, "used_count": 0,
            "ts": datetime.now().isoformat(), "tokens": _tokenize(task)}
    procs.append(proc)
    _save(_PROCEDURAL_FILE, procs[-500:])
    return proc


def recall_procedure(task: str) -> dict | None:
    procs = _load(_PROCEDURAL_FILE)
    if not isinstance(procs, list) or not procs:
        return None
    q_tokens = _tokenize(task)
    scored = [(_tfidf_score(q_tokens, p.get("tokens", [])), p) for p in procs]
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    best = scored[0][1]
    best["used_count"] = best.get("used_count", 0) + 1
    _save(_PROCEDURAL_FILE, procs)
    return best


def store_emotional_memory(topic: str, emotion: str, intensity: int = 5, context: str = "") -> dict:
    memories = _load(_EMOTIONAL_FILE)
    if not isinstance(memories, list):
        memories = []
    memory = {"topic": topic, "emotion": emotion, "intensity": max(1, min(10, intensity)),
              "context": context, "ts": datetime.now().isoformat(), "tokens": _tokenize(topic)}
    memories.append(memory)
    _save(_EMOTIONAL_FILE, memories[-500:])
    return memory


def get_emotional_context(topic: str) -> str:
    memories = _load(_EMOTIONAL_FILE)
    if not isinstance(memories, list) or not memories:
        return ""
    q_tokens = _tokenize(topic)
    relevant = [m for m in memories if _tfidf_score(q_tokens, m.get("tokens", [])) > 0.3]
    if not relevant:
        return ""
    emotions = [m["emotion"] for m in relevant[:3]]
    return f"Emotional context: {', '.join(emotions)}"


def detect_emotion_in_text(text: str) -> dict:
    if len((text or "").split()) < 4:
        return {"emotion": "neutral", "intensity": 3, "should_acknowledge": False}
    try:
        from core.llm.router import think
        result = think(
            f"Detect the primary emotion in this text.\n"
            f'Reply as JSON: {{"emotion": str, "intensity": 1-10, "should_acknowledge": bool}}\n\n'
            f"Text: {text}",
            force_model="instant", use_cache=True,
        )
        cleaned = re.sub(r"```json|```", "", result).strip()
        return json.loads(cleaned)
    except Exception:
        return {"emotion": "neutral", "intensity": 5, "should_acknowledge": False}


def remember_to(task: str, when: str | None = None, trigger: str | None = None,
                 priority: int = 5) -> dict:
    todos = _load(_PROSPECTIVE_FILE)
    if not isinstance(todos, list):
        todos = []
    todo = {"task": task, "when": when, "trigger": trigger, "priority": priority,
            "done": False, "ts": datetime.now().isoformat()}
    todos.append(todo)
    _save(_PROSPECTIVE_FILE, todos)
    return todo


def get_pending_reminders() -> list[dict]:
    todos = _load(_PROSPECTIVE_FILE)
    if not isinstance(todos, list):
        return []
    return [t for t in todos if not t.get("done")]


def check_triggers(context: str) -> list[dict]:
    pending = get_pending_reminders()
    triggered = [t for t in pending if t.get("trigger") and t["trigger"].lower() in (context or "").lower()]
    if triggered:
        todos = _load(_PROSPECTIVE_FILE)
        for t in todos:
            if t in triggered:
                t["done"] = True
        _save(_PROSPECTIVE_FILE, todos)
    return triggered


def universal_recall(query: str, k: int = 3) -> str:
    parts = []
    episodes = recall_episodes(query, k)
    if episodes:
        parts.append("Relevant memories:\n" + "\n".join(f"[{e['ts'][:10]}] {e['event']}" for e in episodes))
    facts = recall_facts(query, k)
    if facts:
        parts.append("Known facts:\n" + "\n".join(f"• {f['fact']}" for f in facts))
    procedure = recall_procedure(query)
    if procedure:
        steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(procedure["steps"][:3]))
        parts.append(f"Known procedure for '{procedure['task']}':\n{steps}")
    emotional = get_emotional_context(query)
    if emotional:
        parts.append(emotional)
    pending = get_pending_reminders()
    triggered = [p for p in pending if p.get("trigger") and p["trigger"].lower() in query.lower()]
    if triggered:
        parts.append("Reminder: " + "; ".join(t["task"] for t in triggered[:2]))
    ltm = recall_as_context(query)
    if ltm:
        parts.append(ltm)
    return "\n\n".join(parts)


THINKING_LOG_FILE = Path("memory/thinking_log.json")


def store_thinking(query: str, response: str, thinking: str, model: str):
    log = _load(THINKING_LOG_FILE)
    if not isinstance(log, list):
        log = []
    log.append({"query": (query or "")[:200], "response": (response or "")[:500],
                "thinking": (thinking or "")[:2000], "model": model, "ts": datetime.now().isoformat()})
    _save(THINKING_LOG_FILE, log[-50:])


def get_last_thinking() -> dict | None:
    log = _load(THINKING_LOG_FILE)
    return log[-1] if isinstance(log, list) and log else None


def get_thinking_log(n: int = 10) -> list[dict]:
    log = _load(THINKING_LOG_FILE)
    return log[-n:] if isinstance(log, list) else []


def semantic_compress(memories: list, target_size: int = 10) -> list:
    if len(memories) <= target_size:
        return memories
    from core.llm.router import think
    all_text = "\n\n".join(
        f"[{m.get('ts','')[:10]}] User: {m.get('user','')} JARVIS: {m.get('ai','')[:80]}"
        for m in memories
    )
    result = think(
        f"Compress these {len(memories)} memories into {target_size} essential entries.\n\n"
        f"Memories:\n{all_text[:3000]}\n\n"
        f"Each entry captures the gist of a cluster.\n"
        f"Reply as JSON array: [{{summary, key_facts, timeframe, importance}}]",
        force_model="standard",
    )
    try:
        clean = re.sub(r"```json|```", "", result).strip()
        compressed = json.loads(clean)
        return [{"user": m.get("summary", ""), "ai": "", "ts": m.get("timeframe", ""),
                 "compressed": True, "key_facts": m.get("key_facts", ""), "importance": m.get("importance", 5)}
                for m in compressed[:target_size]]
    except Exception:
        return memories[-target_size:]


CLIPS_FILE = Path("memory/clips.json")


def save_clip(clip: dict):
    clips = _load(CLIPS_FILE)
    if not isinstance(clips, list):
        clips = []
    clips.append(clip)
    _save(CLIPS_FILE, clips[-500:])


def get_clips(limit: int = 10) -> list:
    clips = _load(CLIPS_FILE)
    if not isinstance(clips, list):
        return []
    return clips[-limit:]


# Turso-backed the same way every other memory file here is: _load()/_save()
# already try Turso first and fall back to a local file only when Turso
# isn't configured or the write/read fails (core/turso_store.py).

def store_note(text: str, title: str = "") -> dict:
    notes = _load(_NOTES_FILE)
    if not isinstance(notes, list):
        notes = []
    note = {
        "id": str(len(notes) + 1), "title": title, "text": text,
        "ts": datetime.now().isoformat(), "tokens": _tokenize(f"{title} {text}"),
    }
    durable = _save(_NOTES_FILE, notes + [note])
    note["durable"] = durable
    return note


def get_all_notes(n: int = 100) -> list[dict]:
    notes = _load(_NOTES_FILE)
    if not isinstance(notes, list):
        return []
    return notes[-n:]


def search_notes(query: str, k: int = 5) -> list[dict]:
    notes = _load(_NOTES_FILE)
    if not isinstance(notes, list) or not notes:
        return []
    q_tokens = _tokenize(query)
    scored = [(_tfidf_score(q_tokens, n.get("tokens", [])), n) for n in notes]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [n for score, n in scored[:k] if score > 0]
