"""core/temporal_long.py — think across multiple time horizons
simultaneously (1 week -> 1 month -> 1 year -> 5 years) for decisions
with long-tail consequences. Opt-in, exposed via POST /stark/brain/longterm
— 5 LLM calls per invocation (4 horizons + synthesis at the paid "opus"
tier), real cost."""


class LongTermReasoner:

    _HORIZONS = (("1 week", "immediate"), ("1 month", "short-term"),
                 ("1 year", "medium-term"), ("5 years", "long-term"))

    def analyze(self, decision: str, context: str = "") -> dict:
        from core.llm.router import think

        analyses = {}
        for horizon, label in self._HORIZONS:
            analyses[horizon] = think(
                f"Decision: {decision}\nContext: {context}\n"
                f"Outcomes in {horizon}? Direct effects, second-order, compounding.",
                force_model="standard",
            )

        synthesis = think(
            f"Decision: {decision}\n\nTime analyses:\n"
            + "\n".join(f"{h}: {a[:150]}" for h, a in analyses.items()) +
            f"\n\nOptimal decision across all horizons? Hidden compounding effects?",
            force_model="opus",
        )
        return {"decision": decision, "horizons": analyses, "synthesis": synthesis}

    def compound_effect(self, action: str, frequency: str = "daily") -> str:
        from core.llm.router import think
        return think(
            f"Compound effects of '{action}' done {frequency}:\n"
            f"Project at: 1 week, 1 month, 6 months, 1 year, 5 years.\n"
            f"Include positive AND negative compounding.",
            force_model="reasoning",
        )

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in (
            "long term", "years from now", "in the future", "compound", "over time", "eventually",
        ))


long_term = LongTermReasoner()
