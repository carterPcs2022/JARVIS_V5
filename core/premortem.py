"""core/premortem.py — pre-mortem + inversion analysis (NASA/military technique)."""
from core.llm.router import think


class PreMortem:

    def analyze(self, plan: str, timeframe: str = "6 months") -> dict:
        failures = think(
            f"It is {timeframe} from now. '{plan}' failed spectacularly.\n"
            f"Post-mortem: what went wrong? Be specific and brutal.",
            force_model="reasoning",
        )
        inversion = think(
            f"Plan: {plan}\n\nWhat would GUARANTEE failure? "
            f"List the top 10 ways to make this definitely fail.",
            force_model="standard",
        )
        mitigations = think(
            f"Plan: {plan}\nFailure modes: {failures[:300]}\n\n"
            f"For each major failure mode, what action NOW prevents it?",
            force_model="opus",
        )
        return {"plan": plan, "failure_modes": failures,
                "inversion": inversion, "mitigations": mitigations}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "plan", "strategy", "launch", "should i do this",
            "thinking about starting", "pre-mortem",
        ])


premortem = PreMortem()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class PremortemStrategy(ReasoningStrategy):
    name = "premortem"

    def should_use(self, query: str) -> bool:
        return premortem.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        data = await asyncio.to_thread(premortem.analyze, query)
        return ReasoningResult(
            answer=data["mitigations"], strategy=self.name,
            evidence=[data.get("failure_modes", "")],
            metadata={"inversion": data.get("inversion", "")},
        )
