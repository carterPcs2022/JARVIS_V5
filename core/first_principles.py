"""core/first_principles.py — strip assumptions, rebuild from fundamentals."""
from core.llm.router import think


class FirstPrinciples:

    def reason(self, problem: str) -> dict:
        assumptions = think(
            f"List every assumption being made about: {problem}\n"
            f"What conventional wisdom are we accepting uncritically?",
            force_model="reasoning",
        )
        fundamentals = think(
            f"Problem: {problem}\nAssumptions: {assumptions[:200]}\n\n"
            f"Strip all assumptions. What are the absolute fundamental truths?",
            force_model="reasoning",
        )
        # Opus, not Fable — this path triggers on common phrasing ("fundamentally",
        # "from scratch") and would burn through Fable's much smaller daily cap
        # in routine use. Fable stays reserved for its explicit ask-for-it triggers.
        solution = think(
            f"Problem: {problem}\nFundamentals: {fundamentals[:200]}\n\n"
            f"Rebuild from first principles. Ignore how it's normally done.",
            force_model="opus",
        )
        return {"problem": problem, "assumptions": assumptions,
                "fundamentals": fundamentals, "solution": solution}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "first principles", "from scratch", "fundamentally",
            "why do we even", "question everything",
        ])


first_principles = FirstPrinciples()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class FirstPrinciplesStrategy(ReasoningStrategy):
    name = "first_principles"

    def should_use(self, query: str) -> bool:
        return first_principles.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        data = await asyncio.to_thread(first_principles.reason, query)
        return ReasoningResult(
            answer=data["solution"], strategy=self.name,
            assumptions=[data.get("assumptions", "")],
            metadata={"fundamentals": data.get("fundamentals", "")},
        )
