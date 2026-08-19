"""
core/multi_agent.py — Mixture of Agents. Three JARVIS personas debate a
hard question from different angles, then a synthesizer combines the
strongest insights into one answer.

Opt-in: 4 LLM calls per invocation (3 agents run concurrently + 1 synthesis).
Not wired into the default chat path — call directly, via
asyncio.run(mixture_of_agents(...)), or POST /stark/reasoning/moa.
"""
import asyncio

_AGENT_PERSONAS = [
    ("analytical", "You are purely analytical. Focus on facts, data, and logical reasoning only."),
    ("creative",   "You are creative and lateral thinking. Consider unconventional angles and possibilities."),
    ("critical",   "You are a critical thinker. Challenge assumptions, find weaknesses, be skeptical."),
]


async def _run_agent(name: str, persona: str, question: str, context: str) -> dict:
    from core.llm.router import think
    response = await asyncio.to_thread(
        think, f"Context: {context}\n\nQuestion: {question}", "", persona, 1024, False, "standard",
    )
    return {"agent": name, "response": response}


async def mixture_of_agents(question: str, context: str = "") -> dict:
    """Three agents with different approaches debate the answer, concurrently."""
    from core.llm.router import think

    results = await asyncio.gather(*[
        _run_agent(name, persona, question, context) for name, persona in _AGENT_PERSONAS
    ])

    combined = "\n\n".join(f"[{r['agent'].upper()} AGENT]:\n{r['response']}" for r in results)
    synthesis = await asyncio.to_thread(
        think,
        f"Original question: {question}\n\n{combined}",
        "",
        "You are JARVIS synthesizing three different analytical perspectives. "
        "Take the strongest insights from each agent and form a single, "
        "nuanced, complete response. Do not mention the agents — just give "
        "the best answer.",
        1024, False, "standard",
    )

    return {"final": synthesis, "agents": list(results), "method": "mixture_of_agents"}


def needs_moa(query: str) -> bool:
    """Does this question benefit from multiple perspectives?"""
    triggers = [
        "should i", "what do you think", "best decision", "recommend",
        "opinion", "advice", "worth it", "help me decide", "pros and cons", "tradeoffs",
    ]
    return any(t in query.lower() for t in triggers)


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────
# mixture_of_agents() is already async — solve() awaits it directly instead
# of the asyncio.to_thread() wrapping the other (synchronous) strategies need.

from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class MixtureOfAgentsStrategy(ReasoningStrategy):
    name = "mixture_of_agents"

    def should_use(self, query: str) -> bool:
        return needs_moa(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        data = await mixture_of_agents(query, context)
        result = ReasoningResult.from_legacy(self.name, data)
        result.evidence = [f"[{a['agent']}] {a['response']}" for a in data.get("agents", [])]
        return result
