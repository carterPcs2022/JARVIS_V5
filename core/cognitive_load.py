"""core/cognitive_load.py — calibrate response length to context and time of day."""
from core.llm.router import think


class CognitiveLoadManager:

    def assess(self, query: str, hour: int) -> str:
        if hour >= 22 or hour < 6:
            return "minimal"
        if len(query.split()) < 5:
            return "minimal"
        if any(t in query.lower() for t in
               ["explain", "analyze", "detailed", "comprehensive"]):
            return "detailed"
        return "normal"

    def calibrate(self, response: str, level: str) -> str:
        if level == "minimal" and len(response.split()) > 30:
            return think(f"Condense to ONE sentence max:\n{response}", force_model="instant")
        return response


cog_load = CognitiveLoadManager()
