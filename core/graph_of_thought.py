"""core/graph_of_thought.py — reasoning as an expanding tree of steps,
synthesized from the leaves. Implemented with a plain dict-based graph
rather than adding a networkx dependency for one opt-in feature.

Opt-in, exposed via server/routes/ultimate_brain.py. Cost is real:
depth=2/breadth=3 defaults to ~4 "instant"-tier expansion calls + 1
"standard" synthesis call — the source spec's depth=3/breadth=3 default
would be ~13 calls, lowered here since this is meant to be occasionally
invoked, not a default per-message reasoning path."""


class GraphOfThought:

    def think(self, problem: str, depth: int = 2, breadth: int = 3) -> dict:
        from core.llm.router import think

        nodes: dict[str, dict] = {"problem": {"content": problem, "children": []}}
        prev_layer = ["problem"]

        for d in range(depth):
            curr_layer = []
            for parent in prev_layer:
                parent_content = nodes[parent]["content"]
                expansions = think(
                    f"Problem: {problem}\nCurrent: {parent_content}\n"
                    f"Generate {breadth} next steps. One per line.",
                    force_model="instant",
                ).strip().split("\n")[:breadth]

                for i, exp in enumerate(expansions):
                    if not exp.strip():
                        continue
                    nid = f"d{d}_{parent}_{i}"
                    nodes[nid] = {"content": exp.strip(), "children": []}
                    nodes[parent]["children"].append(nid)
                    curr_layer.append(nid)
            prev_layer = curr_layer

        leaves = [nid for nid, n in nodes.items() if not n["children"]]
        leaf_contents = [nodes[l]["content"] for l in leaves[:8]]
        solution = think(
            f"Problem: {problem}\n\n"
            f"After exploring {len(nodes)} reasoning steps:\n"
            + "\n".join(f"• {c}" for c in leaf_contents) +
            f"\n\nSynthesize the best final answer.",
            force_model="standard",
        )
        return {"solution": solution, "nodes": len(nodes), "method": "graph_of_thought"}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in (
            "complex", "multifaceted", "interconnected", "many factors", "systems thinking",
        ))


got = GraphOfThought()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────
# Named GraphOfThoughtStrategy here to avoid clashing with the GraphOfThought
# class above; both live in this file, "in place" per the Phase 1 plan.

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class GraphOfThoughtStrategy(ReasoningStrategy):
    name = "graph_of_thought"

    def should_use(self, query: str) -> bool:
        return got.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        # got.think() has no context parameter (see class above) — context
        # is accepted here only for interface uniformity and is dropped.
        data = await asyncio.to_thread(got.think, query)
        result = ReasoningResult.from_legacy(self.name, data)
        result.metadata["nodes_explored"] = data.get("nodes", 0)
        return result
