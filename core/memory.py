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


# ═══════════════════════════════════════════════════════════════════════════
# Six-type memory architecture (working/short-term already exists above)
# ═══════════════════════════════════════════════════════════════════════════

from config.settings import BASE_DIR

_EPISODIC_FILE   = BASE_DIR / "memory" / "episodic.json"
_SEMANTIC_FILE   = BASE_DIR / "memory" / "semantic.json"
_PROCEDURAL_FILE = BASE_DIR / "memory" / "procedural.json"
_EMOTIONAL_FILE  = BASE_DIR / "memory" / "emotional.json"
_PROSPECTIVE_FILE = BASE_DIR / "memory" / "prospective.json"


def _tfidf_score(q_tokens: list[str], doc_tokens: list[str]) -> float:
    if not doc_tokens:
        return 0.0
    tf = defaultdict(int)
    for t in doc_tokens:
        tf[t] += 1
    return sum(tf.get(t, 0) / len(doc_tokens) for t in q_tokens)


# ── 2. Episodic Memory — specific events and when they happened ─────────────

def store_episode(event: str, importance: int = 5, emotions: list[str] | None = None,
                   people: list[str] | None = None, tags: list[str] | None = None) -> dict:
    """importance: 1-10, higher surfaces more readily in recall."""
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
    scored = [
        (_tfidf_score(q_tokens, ep.get("tokens", [])) * (1 + ep.get("importance", 5) / 10), ep)
        for ep in episodes
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ep for score, ep in scored[:k] if score > 0]


# ── 3. Semantic Memory — discrete facts about the world ──────────────────────

def extract_facts(conversation_turn: str) -> list[str]:
    """Extract discrete, atomic, searchable facts from a piece of text.
    Cheap keyword pre-check first — most messages don't state facts worth
    extracting, and this avoids a wasted LLM call on those."""
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
    """Flat list of the most recent stored fact strings — for external
    consumers (e.g. FRIDAY's training sync) that just want the knowledge,
    not the confidence/source/category bookkeeping recall_facts() carries."""
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

    entry = {
        "fact": fact, "confidence": confidence, "source": source, "category": category,
        "ts": datetime.now().isoformat(), "tokens": _tokenize(fact),
    }
    facts.append(entry)
    _save(_SEMANTIC_FILE, facts[-2000:])
    return entry


def recall_facts(query: str, k: int = 5) -> list[dict]:
    facts = _load(_SEMANTIC_FILE)
    if not isinstance(facts, list) or not facts:
        return []
    q_tokens = _tokenize(query)
    scored = [
        (_tfidf_score(q_tokens, f.get("tokens", [])) * f.get("confidence", 0.9), f)
        for f in facts
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for score, f in scored[:k] if score > 0]


def _contradicts(new_fact: str, old_fact: str) -> bool:
    """Cheap heuristic first (avoids an LLM call for obviously-unrelated facts),
    LLM check only when there's real token overlap worth verifying."""
    new_tokens, old_tokens = set(_tokenize(new_fact)), set(_tokenize(old_fact))
    if len(new_tokens & old_tokens) < 2:
        return False
    try:
        from core.llm.router import think
        result = think(
            f"Do these two statements contradict each other?\n"
            f"Statement 1: {old_fact}\nStatement 2: {new_fact}\nReply only: YES or NO",
            force_model="instant", use_cache=True,
        )
        return "YES" in result.upper()
    except Exception:
        return False


# ── 4. Procedural Memory — how to do things ───────────────────────────────────

def store_procedure(task: str, steps: list[str], success_rate: float = 1.0) -> dict:
    procs = _load(_PROCEDURAL_FILE)
    if not isinstance(procs, list):
        procs = []
    proc = {
        "task": task, "steps": steps, "success_rate": success_rate, "used_count": 0,
        "ts": datetime.now().isoformat(), "tokens": _tokenize(task),
    }
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


# ── 5. Emotional Memory — what matters emotionally and why ───────────────────

def store_emotional_memory(topic: str, emotion: str, intensity: int = 5, context: str = "") -> dict:
    memories = _load(_EMOTIONAL_FILE)
    if not isinstance(memories, list):
        memories = []
    memory = {
        "topic": topic, "emotion": emotion, "intensity": max(1, min(10, intensity)),
        "context": context, "ts": datetime.now().isoformat(), "tokens": _tokenize(topic),
    }
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
    """Cheap keyword pre-check before spending an LLM call — most messages
    are emotionally neutral and don't need one."""
    NEUTRAL_SIGNS = len((text or "").split()) < 4
    if NEUTRAL_SIGNS:
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


# ── 6. Prospective Memory — things to do in the future ───────────────────────

def remember_to(task: str, when: str | None = None, trigger: str | None = None,
                 priority: int = 5) -> dict:
    todos = _load(_PROSPECTIVE_FILE)
    if not isinstance(todos, list):
        todos = []
    todo = {
        "task": task, "when": when, "trigger": trigger, "priority": priority,
        "done": False, "ts": datetime.now().isoformat(),
    }
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


# ── Universal recall — searches all six memory types + long-term vector store ─

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


# ── Thinking traces (Anthropic extended thinking) ─────────────────────────────
THINKING_LOG_FILE = Path("memory/thinking_log.json")


def store_thinking(query: str, response: str, thinking: str, model: str):
    """Store an extended-thinking trace so "why did you say that?" can be
    answered later — only called when a tier actually used thinking
    (sonnet/opus/fable with a nonzero budget)."""
    log = _load(THINKING_LOG_FILE)
    if not isinstance(log, list):
        log = []
    log.append({
        "query": (query or "")[:200], "response": (response or "")[:500],
        "thinking": (thinking or "")[:2000], "model": model,
        "ts": datetime.now().isoformat(),
    })
    _save(THINKING_LOG_FILE, log[-50:])


def get_last_thinking() -> dict | None:
    log = _load(THINKING_LOG_FILE)
    return log[-1] if isinstance(log, list) and log else None


def get_thinking_log(n: int = 10) -> list[dict]:
    log = _load(THINKING_LOG_FILE)
    return log[-n:] if isinstance(log, list) else []


def semantic_compress(memories: list, target_size: int = 10) -> list:
    """Compress many memories into fewer, richer ones — gist rather than
    verbatim, the way human memory works. One "standard"-tier LLM call.
    Not auto-wired; core/memory.py's existing compress_if_needed() already
    handles short-term compaction on its own schedule — this is available
    for callers who want to compress an arbitrary memory list on demand."""
    if len(memories) <= target_size:
        return memories

    from core.llm.router import think
    import re

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
        return [
            {"user": m.get("summary", ""), "ai": "", "ts": m.get("timeframe", ""),
             "compressed": True, "key_facts": m.get("key_facts", ""), "importance": m.get("importance", 5)}
            for m in compressed[:target_size]
        ]
    except Exception:
        return memories[-target_size:]

    return "\n\n".join(parts)
