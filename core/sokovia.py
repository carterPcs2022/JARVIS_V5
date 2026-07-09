"""core/sokovia.py — Age of Ultron's mass-casualty-prevention framing:
structured emergency/evacuation analysis and safety-margin calculation for
a proposed action. Thin, purpose-built prompt wrapper over
core.llm.router.think() — real output, no fictional physics."""
from datetime import datetime

from core.llm.router import think


class SokoviaProtocol:

    def evacuation_analysis(self, situation: str, location: str = "", population: int = 0) -> dict:
        analysis = think(
            f"Emergency evacuation analysis:\n"
            f"Situation: {situation}\n"
            f"Location: {location}\n"
            f"Population affected: {population or 'unknown'}\n\n"
            f"Calculate:\n"
            f"1. Immediate evacuation priority zones\n"
            f"2. Estimated time to safely evacuate\n"
            f"3. Critical infrastructure to protect\n"
            f"4. Emergency services to contact\n"
            f"5. Minimum safe perimeter\n"
            f"6. What NOT to do (could increase casualties)\n\n"
            f"Be precise and actionable.",
            force_model="opus",
        )
        return {"protocol": "SOKOVIA", "situation": situation, "analysis": analysis,
                "ts": datetime.now().isoformat()}

    def calculate_safe_action(self, action: str, constraints: list | None = None) -> dict:
        """Age of Ultron: FRIDAY calculated that capping with Thor's hammer
        would vaporize the city. Same idea — safety margins for a proposed
        action, not literal physics."""
        analysis = think(
            f"Safety calculation for action: {action}\n"
            f"Constraints: {constraints or []}\n\n"
            f"What are the safe parameters? What could go catastrophically wrong?\n"
            f"What is the minimum intervention needed?\n"
            f"Red lines that must not be crossed?\n\n"
            f"Precise. Fast.",
            force_model="standard",
        )
        return {"action": action, "analysis": analysis}


sokovia = SokoviaProtocol()
