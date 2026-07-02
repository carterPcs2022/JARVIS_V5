"""
core/tree_of_thought.py — JARVIS explores multiple reasoning paths
simultaneously, evaluates each, and picks the best.

Opt-in: ~8-12 LLM calls per invocation (3 approaches x [expand + evaluate]
+ synthesis). Not wired into the default chat path — call directly or via
POST /stark/reasoning/tot for genuinely complex, high-stakes questions.
"""


class TreeOfThought:

    def think(self, problem: str, n_branches: int = 3, depth: int = 2, context: str = "") -> dict:
        approaches = self._generate_approaches(problem, n_branches, context)

        trees = []
        for approach in approaches:
            tree = self._expand_approach(problem, approach, depth)
            score = self._evaluate_branch(problem, tree)
            trees.append({"approach": approach, "tree": tree, "score": score})

        trees.sort(key=lambda x: x["score"], reverse=True)
        final = self._synthesize(problem, trees[:2]) if trees else "No approaches generated."

        return {
            "answer": final,
            "best_approach": trees[0]["approach"] if trees else None,
            "all_trees": trees,
            "method": "tree_of_thought",
        }

    def _generate_approaches(self, problem: str, n: int, context: str) -> list[str]:
        from core.llm.router import think
        prompt = (
            f"Problem: {problem}\n\n"
            f"Generate exactly {n} distinct, different approaches to solving this. "
            f"Number them 1-{n}. Each should be a fundamentally different angle. "
            f"One approach per line. Brief (1 sentence each)."
        )
        raw = think(prompt, context, force_model="standard")
        lines = [l.strip() for l in raw.split("\n") if l.strip() and l[0].isdigit()]
        return lines[:n] if lines else [raw]

    def _expand_approach(self, problem: str, approach: str, depth: int) -> list[str]:
        from core.llm.router import think
        prompt = (
            f"Problem: {problem}\nApproach: {approach}\n\n"
            f"Think through this step by step. Show {depth} concrete reasoning "
            f"steps that lead to a conclusion."
        )
        raw = think(prompt, force_model="reasoning")
        return [s.strip() for s in raw.split("\n") if s.strip()]

    def _evaluate_branch(self, problem: str, tree: list[str]) -> float:
        from core.llm.router import think
        prompt = (
            f"Problem: {problem}\nReasoning: {' '.join(tree)}\n\n"
            f"Score this reasoning 0-10 on: correctness, completeness, practicality. "
            f"Reply with just a number."
        )
        raw = think(prompt, force_model="instant", use_cache=True)
        try:
            return float("".join(c for c in raw if c.isdigit() or c == "."))
        except Exception:
            return 5.0

    def _synthesize(self, problem: str, top_trees: list[dict]) -> str:
        from core.llm.router import think
        combined = "\n\n".join(
            f"Approach {i+1} (score {t['score']:.1f}):\n{t['approach']}\n"
            f"{'  '.join(t['tree'][:3])}"
            for i, t in enumerate(top_trees)
        )
        return think(
            f"Problem: {problem}\n\nTop reasoning paths:\n{combined}\n\n"
            f"Synthesize the best answer drawing from the strongest elements "
            f"of each path. Be definitive and clear.",
            force_model="standard",
        )

    def should_use_tot(self, query: str) -> bool:
        triggers = [
            "plan", "strategy", "design", "architect", "best way to",
            "how should i approach", "complex", "multiple steps",
            "optimize", "figure out", "work through",
        ]
        return any(t in query.lower() for t in triggers)


tot = TreeOfThought()
