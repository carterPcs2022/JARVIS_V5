"""core/fermi.py — Fermi estimation for order-of-magnitude questions."""
from core.llm.router import think


class FermiEstimator:

    def estimate(self, question: str) -> dict:
        decomposition = think(
            f"Apply Fermi Estimation to: '{question}'\n\n"
            f"Break into estimable components.\n"
            f"Show every step. Give final estimate with range.",
            force_model="reasoning",
        )
        sanity = think(
            f"Fermi estimate for '{question}': {decomposition[:300]}\n"
            f"Sanity check: right order of magnitude? What would make it wrong?",
            force_model="instant",
        )
        return {"question": question, "decomposition": decomposition,
                "sanity_check": sanity}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "how many", "how much would it cost",
            "estimate", "approximately how", "ballpark",
        ])


fermi = FermiEstimator()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class FermiStrategy(ReasoningStrategy):
    name = "fermi"

    def should_use(self, query: str) -> bool:
        return fermi.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        data = await asyncio.to_thread(fermi.estimate, query)
        # core/brain_v2.py's Executor._reasoning_engine() combines these two
        # fields into one answer string this same way — preserved here so
        # routing this engine through the registry doesn't change its output.
        answer = f"{data['decomposition']}\n\n{data['sanity_check']}"
        return ReasoningResult(answer=answer, strategy=self.name)
