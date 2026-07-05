"""core/emotional_simulation.py — before delivering advice, simulate how
it will land emotionally, not just whether it's correct. Opt-in — one
extra LLM call per use, so it's called selectively (from Executor on
explicit request, or via server/routes/ultimate_brain.py), not on every
message."""

CALIBRATIONS = {
    "stressed": "Be brief and immediately useful. Pure signal.",
    "sad": "Be warm. Acknowledge before solving.",
    "excited": "Match the energy briefly.",
    "frustrated": "Skip sympathy. Just solve it.",
    "anxious": "Be calm. Structure clearly. No surprises.",
}


class EmotionalSimulator:

    def calibrate_for_state(self, response: str, emotion: str, intensity: int) -> str:
        if intensity < 4:
            return response
        calibration = CALIBRATIONS.get(emotion, "")
        if not calibration:
            return response
        from core.llm.router import think
        return think(
            f"Rewrite with this emotional calibration:\n"
            f"Calibration: {calibration}\nOriginal: {response[:400]}\n"
            f"Keep all information. Change delivery only.",
            force_model="instant",
        )

    def simulate_impact(self, response: str, emotion: str) -> dict:
        from core.llm.router import think
        import json
        import re
        result = think(
            f"How will this response land for someone feeling {emotion}?\n"
            f"Response: {response[:400]}\n"
            f"Reply as JSON: {{reaction, helpful, needs_adjustment, adjustment_suggestion}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"helpful": True, "needs_adjustment": False}


emotional_sim = EmotionalSimulator()
