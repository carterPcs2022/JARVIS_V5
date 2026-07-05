"""core/structured_debate.py — thesis -> antithesis -> rebuttal ->
synthesis, formal argumentation for controversial/two-sided questions.
Opt-in, exposed via POST /stark/brain/debate. 4 LLM calls per invocation
(one at the paid "fable" tier for synthesis) — real cost, not for casual
use."""


class StructuredDebate:

    def debate(self, proposition: str, context: str = "") -> dict:
        from core.llm.router import think

        thesis = think(
            f"Argue as strongly as possible FOR: '{proposition}'\n"
            f"Context: {context}\nBe rigorous and evidence-based.",
            force_model="reasoning",
        )
        antithesis = think(
            f"Argue as strongly as possible AGAINST: '{proposition}'\n"
            f"Challenge these points:\n{thesis[:300]}",
            force_model="reasoning",
        )
        rebuttal = think(
            f"The FOR position responds to:\n{antithesis[:300]}\n"
            f"Which objections are valid? Which can be defeated?",
            force_model="standard",
        )
        synthesis = think(
            f"Proposition: '{proposition}'\n"
            f"FOR: {thesis[:200]}\nAGAINST: {antithesis[:200]}\nRebuttal: {rebuttal[:200]}\n\n"
            f"What is the most defensible nuanced position? "
            f"Find genuine truth — don't just split the difference.",
            force_model="fable",
        )
        return {
            "proposition": proposition, "thesis": thesis, "antithesis": antithesis,
            "synthesis": synthesis, "method": "structured_debate",
        }

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in (
            "is it true that", "controversial", "both sides",
            "what's the truth about", "debatable",
        ))


debate = StructuredDebate()
