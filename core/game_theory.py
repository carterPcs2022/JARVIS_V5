"""core/game_theory.py — strategic/negotiation analysis via game theory."""
from core.llm.router import think


class GameTheoryReasoner:

    def analyze(self, situation: str, players: list = []) -> dict:
        players_str = ", ".join(players) if players else "the relevant parties"
        analysis = think(
            f"Game theory analysis: '{situation}'\nPlayers: {players_str}\n\n"
            f"1. What does each player want?\n"
            f"2. What are each player's strategies?\n"
            f"3. What's the Nash equilibrium?\n"
            f"4. Is there a dominant strategy?\n"
            f"5. How should you play?",
            force_model="reasoning",
        )
        return {"situation": situation, "analysis": analysis}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "negotiate", "competition", "opponent",
            "what will they do", "strategic",
        ])


game_theory = GameTheoryReasoner()
