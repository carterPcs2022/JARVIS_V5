"""core/agents/researcher.py — Research agent: web search + synthesis."""
from core.llm.router import think
from core.tools.web import search, fetch

def research(topic: str, depth: int = 3) -> dict:
    results = search(topic, max_results=depth)
    sources = []
    for r in results:
        if r.get("url"):
            content = fetch(r["url"], max_chars=1500)
            sources.append({"title": r.get("title",""), "content": content})
    combined = "\n\n".join(f"[{s['title']}]\n{s['content']}" for s in sources)
    synthesis = think(
        f"Synthesize these sources into a clear, factual answer about: {topic}\n\nSources:\n{combined}"
    )
    return {"topic": topic, "synthesis": synthesis, "sources_used": len(sources)}
