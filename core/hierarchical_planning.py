"""core/hierarchical_planning.py — vision-to-next-action goal decomposition."""
from core.llm.router import think


class HierarchicalPlanner:

    LEVELS = ["vision", "annual", "monthly", "weekly", "daily", "next_action"]

    def plan(self, goal: str, depth: int = 4) -> dict:
        hierarchy = {}
        context = f"Goal: {goal}"
        for level in self.LEVELS[:depth]:
            result = think(
                f"{context}\n\nWhat are the {level} actions/goals?\n"
                f"Be specific. Each must serve the level above.",
                force_model="standard",
            )
            hierarchy[level] = result
            context += f"\n{level}: {result[:150]}"
        next_action = think(
            f"Goal: {goal}\nPlan: {str(hierarchy)[:400]}\n\n"
            f"Single next physical action to take RIGHT NOW? One sentence.",
            force_model="instant",
        )
        hierarchy["next_action"] = next_action
        return {"goal": goal, "hierarchy": hierarchy, "next_action": next_action}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "plan for", "how do i achieve", "roadmap",
            "break down my goal",
        ])


hierarchical = HierarchicalPlanner()
