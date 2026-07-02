"""
core/self_consistency.py — Generate N independent answers, pick the most
consistent one. Improves accuracy on factual questions at the cost of
n_samples + 2 extra LLM calls.

Opt-in — not wired into the default chat path.
"""


class SelfConsistency:

    def answer(self, query: str, context: str = "", n_samples: int = 3) -> dict:
        from core.llm.router import think

        answers = [think(query, context, force_model="standard") for _ in range(n_samples)]

        consistency_prompt = (
            f"These {n_samples} answers were given to: '{query}'\n\n"
            + "\n\n".join(f"Answer {i+1}: {a}" for i, a in enumerate(answers))
            + "\n\nWhich answer is most consistent with the others and most "
              "likely correct? Return that answer verbatim."
        )
        final = think(consistency_prompt, force_model="instant")
        agreement = self._measure_agreement(answers)

        return {
            "answer": final, "agreement": agreement, "samples": answers,
            "method": "self_consistency", "confidence": min(100, int(agreement * 100)),
        }

    def _measure_agreement(self, answers: list[str]) -> float:
        if len(answers) < 2:
            return 1.0
        from core.llm.router import think
        result = think(
            "How much do these answers agree? Reply with a number 0.0 to 1.0 only.\n\n"
            + "\n".join(f"Answer {i+1}: {a[:200]}" for i, a in enumerate(answers)),
            force_model="instant",
        )
        try:
            return float("".join(c for c in result if c.isdigit() or c == "."))
        except Exception:
            return 0.7

    def should_use_sc(self, query: str) -> bool:
        triggers = [
            "what is", "who is", "when did", "how many", "what year",
            "is it true", "fact check", "verify", "confirm", "accurate",
        ]
        return any(t in query.lower() for t in triggers)


sc = SelfConsistency()
