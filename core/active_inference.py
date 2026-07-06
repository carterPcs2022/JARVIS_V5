"""core/active_inference.py — predict the user's actual need vs. literal query."""
import json, re
from core.llm.router import think


class ActiveInferenceEngine:

    def predict_intent(self, query: str, history: list) -> dict:
        recent = "\n".join(f"User: {t.get('user', '')}" for t in history[-5:])
        result = think(
            f"Context:\n{recent}\n\nCurrent: {query}\n\n"
            f"Reply JSON: {{literal, actual_need, predicted_next}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"literal": query, "actual_need": query}


active_inf = ActiveInferenceEngine()
