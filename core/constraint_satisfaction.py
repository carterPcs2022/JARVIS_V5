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
