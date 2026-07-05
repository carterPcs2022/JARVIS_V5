"""core/abductive.py — Sherlock mode: given observations, find the most
likely explanation. Used for debugging/diagnosis/security analysis.
Opt-in, exposed via POST /stark/brain/abductive."""
import json
import re


class AbductiveReasoner:

    def best_explanation(self, observations: list[str], domain: str = "") -> dict:
        from core.llm.router import think
        obs_text = "\n".join(f"• {o}" for o in observations)
        result = think(
            f"Abductive reasoning for these observations:\n"
            f"Domain: {domain or 'general'}\nObservations:\n{obs_text}\n\n"
            f"1. List all plausible explanations\n"
            f"2. How well does each explain ALL observations?\n"
            f"3. Eliminate contradicted explanations\n"
            f"4. Rank by simplicity and explanatory power\n"
            f"5. Best explanation with confidence\n\n"
            f"Reply as JSON: {{best_explanation, confidence, alternatives, eliminated}}",
            force_model="reasoning",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"best_explanation": result, "confidence": 60}

    def debug_system(self, symptoms: list[str], context: str = "") -> dict:
        from core.llm.router import think
        result = self.best_explanation(symptoms, f"debugging: {context}")
        result["fix"] = think(
            f"Given diagnosis: {result.get('best_explanation','')}\n"
            f"What is the most likely fix? Specific steps.",
            force_model="standard",
        )
        return result

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in (
            "why is", "what caused", "what's wrong", "why did",
            "how did this happen", "diagnose", "doesn't make sense",
            "debug", "root cause",
        ))


abductive = AbductiveReasoner()
