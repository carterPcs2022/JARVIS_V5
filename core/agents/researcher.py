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


# ── Agent adapter (core/interfaces/agent.py) ───────────────────────────────────

import asyncio
from core.interfaces.agent import Agent, AgentResult


class ResearcherAgent(Agent):
    name = "researcher"

    async def run(self, task: str, context: dict | None = None) -> AgentResult:
        depth = (context or {}).get("depth", 3)
        result = await asyncio.to_thread(research, task, depth)
        return AgentResult(output=result, success=result.get("sources_used", 0) > 0)
