"""core/temporal_reasoning.py — Time-aware reasoning and recall.
Understands relative time references ("last week", "before the project")."""


class TemporalReasoning:

    def parse_temporal_reference(self, text: str) -> dict:
        """Parse natural language time references into a concrete anchor."""
        from core.llm.router import think
        from datetime import datetime
        result = think(
            f"Today is {datetime.now().strftime('%Y-%m-%d')}.\n"
            f"Parse the temporal reference in: '{text}'\n"
            f"Reply as JSON only: "
            f'{{"reference": str, "approximate_date": str, "is_relative": bool, "anchor": str}}',
            force_model="instant", use_cache=True,
        )
        import json
        try:
            return json.loads(result.strip())
        except Exception:
            return {"reference": text, "approximate_date": None, "is_relative": True, "anchor": None}

    def time_aware_recall(self, query: str, temporal_ref: str = "") -> str:
        from core.memory import recall_as_context
        context = recall_as_context(query)
        if temporal_ref:
            parsed = self.parse_temporal_reference(temporal_ref)
            context = f"[Temporal filter: {parsed.get('reference', temporal_ref)}]\n" + context
        return context


temporal = TemporalReasoning()
