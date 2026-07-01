"""core/personal_search.py — Unified search across every data source JARVIS has.

One query searches conversations, notes, documents, people, projects, and
compression summaries simultaneously, ranked by relevance + recency.
"""
import math
import re
from collections import defaultdict
from datetime import datetime


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _collect_conversations() -> list[dict]:
    try:
        from core.memory import _load
        from config.settings import CONVERSATIONS_FILE
        convs = _load(CONVERSATIONS_FILE)
        return [
            {"source": "conversations", "content": f"User: {c['user']}\nJARVIS: {c['ai']}",
             "date": c.get("ts", ""), "metadata": {}}
            for c in convs
        ]
    except Exception:
        return []


def _collect_notes() -> list[dict]:
    try:
        from services.productivity import productivity, NOTES_FILE
        from core.memory import _load
        notes = _load(NOTES_FILE) if hasattr(productivity, "_load") else []
    except Exception:
        notes = []
    try:
        import json
        from pathlib import Path
        from config.settings import BASE_DIR
        path = BASE_DIR / "data" / "notes.json"
        if path.exists():
            notes = json.loads(path.read_text())
    except Exception:
        pass
    return [
        {"source": "notes", "content": n.get("content", ""), "date": n.get("ts", ""),
         "metadata": {"tags": n.get("tags", [])}}
        for n in (notes or [])
    ]


def _collect_documents() -> list[dict]:
    try:
        from services.documents import list_documents
        docs = list_documents()
        return [
            {"source": "documents", "content": f"{d.get('name','')}: {d.get('summary','')}",
             "date": d.get("ts", ""), "metadata": {"id": d.get("id")}}
            for d in docs
        ]
    except Exception:
        return []


def _collect_people() -> list[dict]:
    try:
        from services.people import list_people
        people = list_people()
        return [
            {"source": "people", "content": f"{p.get('name','')} ({p.get('relationship','')}): {p.get('last_context','')}",
             "date": p.get("last_mentioned", ""), "metadata": {"name": p.get("name")}}
            for p in people
        ]
    except Exception:
        return []


def _collect_projects() -> list[dict]:
    try:
        from services.workshop import workshop
        projects = workshop.list_projects()
        return [
            {"source": "projects", "content": f"{p.get('name','')}: {p.get('description','')} — {p.get('status','')}",
             "date": p.get("updated", ""), "metadata": {"name": p.get("name")}}
            for p in projects
        ]
    except Exception:
        return []


def _collect_second_brain() -> list[dict]:
    try:
        from services.second_brain import second_brain
        notes = second_brain.list_notes()
        return [
            {"source": "second_brain", "content": f"{n.get('title','')}: {n.get('content','')}",
             "date": n.get("created", ""), "metadata": {"id": n.get("id")}}
            for n in notes
        ]
    except Exception:
        return []


_COLLECTORS = {
    "conversations": _collect_conversations,
    "notes":         _collect_notes,
    "documents":     _collect_documents,
    "people":        _collect_people,
    "projects":      _collect_projects,
    "second_brain":  _collect_second_brain,
}

SOURCES = list(_COLLECTORS.keys())


def _score(entry: dict, q_tokens: list[str], idf: dict) -> float:
    toks = _tokenize(entry["content"])
    if not toks:
        return 0.0
    tf = defaultdict(int)
    for t in toks:
        tf[t] += 1
    relevance = sum((tf[t] / len(toks)) * idf.get(t, 0) for t in q_tokens)

    # Recency boost
    recency = 0.0
    try:
        date_str = entry.get("date", "")
        if date_str:
            age_days = (datetime.now() - datetime.fromisoformat(date_str.replace("Z", ""))).days
            recency = max(0, 1 - age_days / 365)
    except Exception:
        pass

    return relevance + recency * 0.15


def search(query: str, sources: list[str] | None = None, limit: int = 20) -> dict:
    """Search across every configured data source. Ranked by relevance + recency."""
    sources = sources or SOURCES
    entries: list[dict] = []
    for src in sources:
        collector = _COLLECTORS.get(src)
        if collector:
            entries.extend(collector())

    q_tokens = _tokenize(query)
    if not q_tokens or not entries:
        return {"query": query, "total_results": 0, "results": [], "synthesis": ""}

    df: dict = defaultdict(int)
    for e in entries:
        for t in set(_tokenize(e["content"])):
            df[t] += 1
    n = len(entries)
    idf = {t: math.log(n / (v + 1)) for t, v in df.items()}

    scored = [(e, _score(e, q_tokens, idf)) for e in entries]
    scored = [(e, s) for e, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    results = [
        {"source": e["source"], "content": e["content"][:500], "relevance": round(s, 4),
         "date": e.get("date", ""), "metadata": e.get("metadata", {})}
        for e, s in scored[:limit]
    ]

    return {"query": query, "total_results": len(scored), "results": results, "synthesis": ""}


def search_and_synthesize(query: str) -> str:
    """Search everything, then have JARVIS synthesize the findings into a coherent answer."""
    results = search(query, limit=10)
    if not results["results"]:
        return f"I couldn't find anything about '{query}' across your conversations, notes, documents, people, or projects."

    context = "\n\n".join(
        f"[{r['source']}, {r['date'][:10] if r['date'] else 'undated'}]\n{r['content']}"
        for r in results["results"]
    )
    try:
        from core.llm.router import think
        prompt = (
            f"The user asked: \"{query}\"\n\n"
            f"Here is everything found across their personal data:\n\n{context}\n\n"
            f"Synthesize a direct, concise answer. Cite which source(s) informed it."
        )
        return think(prompt, max_tokens=500)
    except Exception:
        return "\n\n".join(f"[{r['source']}] {r['content'][:200]}" for r in results["results"][:5])
