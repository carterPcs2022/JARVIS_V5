"""core/six_hats.py — Edward de Bono's Six Thinking Hats."""
from core.llm.router import think as llm

HATS = {
    "white":  "Facts only. No opinions. What do we know for certain?",
    "red":    "Pure emotion and instinct. Gut feeling. No logic.",
    "black":  "Devil's advocate. What could go wrong?",
    "yellow": "Pure optimism. Best case. What is the upside?",
    "green":  "Creative alternatives. What else could we do?",
    "blue":   "Process. Are we thinking about this correctly?",
}


class SixThinkingHats:

    def think(self, topic: str) -> dict:
        responses = {}
        for hat, prompt in HATS.items():
            responses[hat] = llm(
                f"[{hat.upper()} HAT — {prompt}]\nTopic: {topic}",
                force_model="standard",
            )
        synthesis = llm(
            f"Topic: {topic}\n\nSix perspectives:\n"
            + "\n".join(f"[{h}]: {r[:120]}" for h, r in responses.items())
            + "\n\nSynthesize into one balanced view.",
            force_model="opus",
        )
        return {"topic": topic, "hats": responses, "synthesis": synthesis}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "all angles", "different perspectives",
            "complete picture", "six hats",
        ])


six_hats = SixThinkingHats()
