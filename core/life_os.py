"""core/life_os.py — Life OS: vision -> values -> life areas -> alignment.
JARVIS tracks whether daily activity matches what the user says matters,
not just whether tasks get checked off."""
import json
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

LIFE_OS_FILE = BASE_DIR / "memory" / "life_os.json"

_DEFAULT_FRAMEWORK = {
    "vision": {},
    "values": [],
    "areas": {},
}


class LifeOS:

    def __init__(self):
        self.framework = self._load()

    def set_vision(self, vision: str) -> dict:
        """"What does your ideal life look like in 10 years?" — stored and
        referenced during alignment_check()."""
        self.framework["vision"] = {"statement": vision, "set": datetime.now().isoformat()}
        self._save()
        return {"vision": vision}

    def set_values(self, values: list[str]) -> dict:
        self.framework["values"] = values
        self._save()
        return {"values": values}

    def add_life_area(self, area: str, current_state: str, desired_state: str, score: int = 5) -> dict:
        """Life areas: Health, Finance, Career, Relationships, Personal
        Growth, Fun, Environment, Family. score: 1-10, where you are now."""
        self.framework["areas"][area] = {
            "current": current_state, "desired": desired_state,
            "score": score, "updated": datetime.now().isoformat(),
        }
        self._save()
        return self.framework["areas"][area]

    def alignment_check(self) -> dict:
        """"Am I living aligned with what I said matters?" — one reasoning-
        tier LLM call comparing stated values/vision against recent activity."""
        from core.llm.router import think
        from core.memory import get_context_string

        recent_activity = get_context_string(20)
        framework = json.dumps(self.framework, indent=2)[:2000]

        result = think(
            f"Life OS Alignment Check:\n\n"
            f"Stated values and vision:\n{framework}\n\n"
            f"Recent activity:\n{recent_activity}\n\n"
            f"Is this person living aligned with their stated values and vision? "
            f"Where are the gaps? What's working well? What needs course correction?\n\n"
            f"Be honest. Be specific. Be kind.",
            force_model="reasoning",
        )
        return {"alignment_analysis": result, "checked": datetime.now().isoformat()}

    def weekly_review(self) -> dict:
        """Structured weekly review, meant to run every Sunday."""
        from core.llm.router import think
        from core.memory import get_context_string

        context = get_context_string(30)
        questions = [
            "What did you accomplish this week?",
            "What didn't get done? Why?",
            "What are you grateful for?",
            "What drained your energy?",
            "What energized you?",
            "What do you want to focus on next week?",
            "Is there anything you need to let go of?",
        ]

        synthesis = think(
            f"Based on this week's activity, provide a thoughtful weekly review covering:\n"
            + "\n".join(f"- {q}" for q in questions) +
            f"\n\nActivity this week:\n{context}\n\n"
            f"Be reflective, honest, and forward-looking.",
            force_model="reasoning",
        )
        return {"review": synthesis, "week_of": datetime.now().isoformat(), "questions": questions}

    def morning_intention(self) -> str:
        """The 3 most important things today, weighted by long-term goals
        rather than raw urgency."""
        from core.llm.router import think
        from services.goals import get_goals
        from services.calendar_intel import calendar_intel

        goals = get_goals("active")
        calendar = calendar_intel.get_today()

        return think(
            f"Based on active goals and today's calendar, what are the 3 most "
            f"important things to focus on today?\n"
            f"Goals: {json.dumps(goals[:5], default=str)}\n"
            f"Calendar: {json.dumps(calendar[:3], default=str)}\n\n"
            f"Prioritize by importance to long-term goals, not just urgency. "
            f"JARVIS-style delivery.",
            force_model="standard",
        )

    def dashboard(self) -> dict:
        """Everything the HUD's Life OS panel needs in one call — no LLM cost."""
        areas = self.framework.get("areas", {})
        top_areas = sorted(areas.items(), key=lambda kv: kv[1].get("score", 5))[:3]
        return {
            "vision": self.framework.get("vision", {}),
            "values": self.framework.get("values", []),
            "areas": areas,
            "lowest_scoring_areas": [{"area": a, **v} for a, v in top_areas],
        }

    def _load(self) -> dict:
        if LIFE_OS_FILE.exists():
            try:
                return json.loads(LIFE_OS_FILE.read_text())
            except Exception:
                pass
        return json.loads(json.dumps(_DEFAULT_FRAMEWORK))

    def _save(self):
        LIFE_OS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIFE_OS_FILE.write_text(json.dumps(self.framework, indent=2))


life_os = LifeOS()
