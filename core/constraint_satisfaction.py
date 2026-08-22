"""core/constraint_satisfaction.py — find solutions that satisfy every constraint at once."""
from core.llm.router import think


class ConstraintSolver:

    def solve(self, problem: str, constraints: list) -> dict:
        c_str = "\n".join(f"{i+1}. {c}" for i, c in enumerate(constraints))
        solution = think(
            f"Problem: {problem}\n\nAll constraints MUST be met:\n{c_str}\n\n"
            f"Find solution satisfying ALL simultaneously. "
            f"Confirm each constraint is met.",
            force_model="reasoning",
        )
        return {"problem": problem, "constraints": constraints, "solution": solution}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "all of these", "must satisfy", "requirements",
            "all conditions",
        ])


constraint_solver = ConstraintSolver()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────
# Named "constraint_solver" to match core/brain_v2.py's engine name for this
# technique (not "constraint_satisfaction", the module's own filename).

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class ConstraintSolverStrategy(ReasoningStrategy):
    name = "constraint_solver"

    def should_use(self, query: str) -> bool:
        return constraint_solver.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        # core/brain_v2.py always calls solve(raw, []) — no constraint list
        # is ever actually extracted from the intent — matched here.
        data = await asyncio.to_thread(constraint_solver.solve, query, [])
        return ReasoningResult(answer=data["solution"], strategy=self.name)
