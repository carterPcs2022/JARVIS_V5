"""core/dual_process.py — Kahneman's System 1 (fast) / System 2 (slow) thinking."""
from core.llm.router import think as llm


class DualProcessThinking:

    SYSTEM2_TRIGGERS = [
        "should i", "important decision", "carefully",
        "think through", "complex", "tradeoffs",
        "critical", "major", "significant",
    ]

    def classify(self, query: str) -> str:
        q = query.lower()
        if len(query.split()) > 20:
            return "system2"
        if any(t in q for t in self.SYSTEM2_TRIGGERS):
            return "system2"
        return "system1"

    def think(self, query: str, context: str = "") -> dict:
        mode = self.classify(query)
        if mode == "system1":
            return {"mode": "system1",
                    "response": llm(query, context, force_model="instant")}
        # Opus, not Fable — these triggers ("should i", "complex", word count
        # > 20) fire on ordinary chat constantly and would exhaust Fable's
        # small daily cap almost immediately if routed there by default.
        response = llm(
            f"[SLOW DELIBERATE THINKING]\nQuestion: {query}\n{context}",
            force_model="opus",
        )
        return {"mode": "system2", "response": response}


dual_process = DualProcessThinking()
