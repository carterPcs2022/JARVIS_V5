"""core/bayesian.py — mathematically-framed confidence: prior, evidence
for/against, posterior, rather than vague hedging. Opt-in, exposed via
POST /stark/brain/bayesian."""
import json
import re


class BayesianReasoner:

    def estimate_probability(self, claim: str, context: str = "") -> dict:
        from core.llm.router import think
        result = think(
            f"Bayesian analysis for: '{claim}'\nContext: {context}\n\n"
            f"1. Prior probability (before evidence)\n"
            f"2. Evidence FOR this claim\n3. Evidence AGAINST this claim\n"
            f"4. Posterior probability after evidence\n5. Key uncertainty sources\n\n"
            f"Reply as JSON: {{prior, evidence_for, evidence_against, posterior, uncertainties}}",
            force_model="reasoning",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"posterior": 50, "raw": result}

    def compare_hypotheses(self, hypotheses: list[str], evidence: str) -> dict:
        from core.llm.router import think
        formatted = "\n".join(f"H{i+1}: {h}" for i, h in enumerate(hypotheses))
        result = think(
            f"Evidence: {evidence}\nRank these hypotheses by probability:\n{formatted}\n"
            f"Reply as JSON array: [{{hypothesis, probability, support, weakness}}]",
            force_model="reasoning",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return {"ranked": json.loads(clean)}
        except Exception:
            return {"ranked": []}

    def confidence_statement(self, posterior: float) -> str:
        if posterior >= 95:
            return "I'm virtually certain —"
        if posterior >= 85:
            return "I'm highly confident —"
        if posterior >= 70:
            return "The evidence suggests —"
        if posterior >= 55:
            return "On balance, I'd say —"
        if posterior >= 40:
            return "This is genuinely uncertain, but —"
        return "I'd treat this as speculative —"


bayesian = BayesianReasoner()
