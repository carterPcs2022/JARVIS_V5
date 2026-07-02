"""
core/reflexion.py — JARVIS evaluates his own past responses, identifies
what went wrong, and stores lessons that improve future responses.

Based on "Reflexion: Language Agents with Verbal Reinforcement Learning"
(Shinn et al. 2023).

Off by default (USE_REFLEXION=false) — evaluate_response() costs one LLM
call per turn even when run in a background thread, which doubles total
call volume for the session if wired into every message. Enable via
config/settings.py USE_REFLEXION or call directly for specific responses
worth learning from.
"""
import json
from datetime import datetime
from pathlib import Path
from config.settings import BASE_DIR

_REFLEXION_FILE = BASE_DIR / "memory" / "reflexion.json"


class ReflexionEngine:

    def evaluate_response(self, query: str, response: str, outcome: str = "unknown") -> dict:
        """outcome: 'good' | 'bad' | 'partial' | 'unknown'."""
        from core.llm.router import think

        eval_prompt = (
            f"Evaluate this AI response:\nQuery: {query}\nResponse: {response}\n"
            f"Known outcome: {outcome}\n\n"
            f"What could be improved? What lesson should be learned? Reply as JSON only: "
            f'{{"quality": 1-10, "lesson": str, "category": str, "should_store": bool}}'
        )
        raw = think(eval_prompt, force_model="instant")
        try:
            evaluation = json.loads(raw.strip())
        except Exception:
            evaluation = {"quality": 7, "lesson": "", "should_store": False}

        if evaluation.get("should_store") and evaluation.get("lesson"):
            self._store_lesson(
                query_pattern=query[:100], lesson=evaluation["lesson"],
                category=evaluation.get("category", "general"), quality=evaluation.get("quality", 5),
            )

        return evaluation

    def _store_lesson(self, query_pattern: str, lesson: str, category: str, quality: int):
        lessons = self._load()
        lessons.append({
            "pattern": query_pattern, "lesson": lesson, "category": category,
            "quality": quality, "ts": datetime.now().isoformat(), "applied": 0,
        })
        self._save(lessons[-200:])

    def get_relevant_lessons(self, query: str, k: int = 3) -> list[str]:
        lessons = self._load()
        if not lessons:
            return []
        q_lower = query.lower()
        relevant = [
            l for l in lessons
            if any(word in q_lower for word in l["pattern"].lower().split()[:5])
        ]
        relevant.sort(key=lambda x: x.get("quality", 5), reverse=True)
        return [l["lesson"] for l in relevant[:k]]

    def inject_lessons(self, query: str, system_prompt: str) -> str:
        lessons = self.get_relevant_lessons(query)
        if not lessons:
            return system_prompt
        lesson_str = "\n".join(f"- {l}" for l in lessons)
        return system_prompt + f"\n\nLessons from past interactions:\n{lesson_str}"

    def _load(self) -> list:
        if _REFLEXION_FILE.exists():
            try:
                return json.loads(_REFLEXION_FILE.read_text())
            except Exception:
                return []
        return []

    def _save(self, lessons: list):
        _REFLEXION_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REFLEXION_FILE.write_text(json.dumps(lessons, indent=2))


reflexion = ReflexionEngine()
