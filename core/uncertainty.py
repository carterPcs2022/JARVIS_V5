"""core/uncertainty.py — knows WHY it's uncertain, not just THAT it is.
Opt-in — one "instant"-tier LLM call per analysis, exposed via
server/routes/ultimate_brain.py rather than run on every response."""

UNCERTAINTY_TYPES = {
    "missing_data": "I'd need more information —",
    "ambiguous_query": "Your question could mean several things —",
    "conflicting_evidence": "The evidence points both ways —",
    "model_limitation": "This is near the edge of my knowledge —",
    "recency": "My information may be outdated here —",
    "domain_specific": "This requires expertise I may lack —",
}


class UncertaintyDecomposer:

    def analyze(self, query: str, response: str) -> dict:
        from core.llm.router import think
        import json
        import re
        result = think(
            f"Analyze uncertainty in this response:\n"
            f"Query: {query}\nResponse: {response[:300]}\n"
            f"Uncertainty types: {list(UNCERTAINTY_TYPES.keys())}\n"
            f"Reply as JSON: {{types, confidence, main_source}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            data = json.loads(clean)
        except Exception:
            data = {"confidence": 75, "main_source": "general"}
        data["prefix"] = UNCERTAINTY_TYPES.get(data.get("main_source", ""), "")
        return data

    def add_marker(self, response: str, analysis: dict) -> str:
        confidence = analysis.get("confidence", 75)
        prefix = analysis.get("prefix", "")
        if confidence >= 70 or not prefix:
            return response
        if confidence >= 50:
            return f"{prefix} {response}"
        return f"Treat this as provisional — {response}"


uncertainty = UncertaintyDecomposer()
