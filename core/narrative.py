"""core/narrative.py — tracks the conversation's story arc: theme, the
user's deeper goal beneath surface questions, where it's heading. Updates
periodically (every 5th turn) rather than every message, since the arc
doesn't meaningfully shift turn-to-turn. One "instant"-tier LLM call per
update. Opt-in — get_context() is free to call, update_arc() costs a
call only on its update turns."""


class NarrativeEngine:

    def __init__(self):
        self.current_arc = {"theme": "", "deeper_goal": "", "tension": "", "heading": ""}

    def update_arc(self, user_input: str, response: str, turn: int) -> dict:
        if turn < 3 or turn % 5 != 0:
            return self.current_arc

        from core.llm.router import think
        from core.memory import get_short_term
        import json
        import re

        recent = get_short_term(8)
        context = "\n".join(f"User: {t.get('user','')}\nJARVIS: {t.get('ai','')}" for t in recent)
        result = think(
            f"Analyze the narrative arc:\n{context}\n\n"
            f"Reply as JSON: {{theme, deeper_goal, tension, heading}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            self.current_arc = json.loads(clean)
        except Exception:
            pass
        return self.current_arc

    def get_context(self) -> str:
        arc = self.current_arc
        if not arc.get("theme"):
            return ""
        return f"Conversation arc: theme={arc.get('theme','')}, user_goal={arc.get('deeper_goal','')}"


narrative = NarrativeEngine()
