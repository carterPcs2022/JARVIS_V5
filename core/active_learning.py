"""
core/active_learning.py — Every correction and piece of feedback becomes
training data. Weekly retraining applies all lessons.

record_correction/record_feedback are cheap (pure I/O). detect_implicit_
feedback and generate_synthetic_training_data cost an LLM call each — used
sparingly (implicit-feedback detection only makes sense right after a
response; synthetic data generation only runs as part of the weekly cycle,
not continuously).
"""
import json
import re
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR

CORRECTIONS_FILE = BASE_DIR / "memory" / "corrections.json"
FEEDBACK_FILE    = BASE_DIR / "memory" / "feedback.json"


class ActiveLearner:

    def record_correction(self, original_query: str, wrong_response: str,
                          correct_response: str, source: str = "user") -> dict:
        """"Actually JARVIS that's wrong, it should be..." — stored immediately
        as high-quality training data, weighted double."""
        corrections = self._load(CORRECTIONS_FILE)
        entry = {
            "query": original_query, "wrong": wrong_response, "correct": correct_response,
            "source": source, "ts": datetime.now().isoformat(), "weight": 2.0,
        }
        corrections.append(entry)
        self._save(CORRECTIONS_FILE, corrections)

        try:
            from core.reflexion import reflexion
            reflexion.evaluate_response(original_query, wrong_response, outcome="bad")
        except Exception:
            pass

        return entry

    def record_feedback(self, response_id: str, rating: int, comment: str = "") -> dict:
        """Explicit thumbs up/down. rating: 1-5."""
        feedback = self._load(FEEDBACK_FILE)
        entry = {"response_id": response_id, "rating": rating, "comment": comment,
                 "ts": datetime.now().isoformat()}
        feedback.append(entry)
        self._save(FEEDBACK_FILE, feedback)
        return entry

    def detect_implicit_feedback(self, user_message: str, last_response: str) -> dict:
        """Detect satisfaction/dissatisfaction without an explicit rating —
        cheap keyword pre-check first, LLM call only for genuinely ambiguous cases."""
        low = user_message.lower().strip()
        POSITIVE_WORDS = ("thanks", "thank you", "perfect", "exactly", "great", "nice", "awesome")
        NEGATIVE_WORDS = ("no", "wrong", "not what i meant", "actually", "that's not right")

        if any(w in low for w in POSITIVE_WORDS) and len(low.split()) < 8:
            return {"sentiment": "positive", "confidence": 0.85, "correction_indicated": False}
        if any(low.startswith(w) for w in ("no,", "no ", "actually")):
            return {"sentiment": "negative", "confidence": 0.7, "correction_indicated": True}

        try:
            from core.llm.router import think
            result = think(
                f"Did the user's message indicate satisfaction or dissatisfaction "
                f"with the previous AI response?\n\nPrevious response: {last_response[:200]}\n"
                f"User's next message: {user_message}\n\n"
                f'Reply as JSON: {{"sentiment": "positive/negative/neutral", '
                f'"confidence": 0-1, "correction_indicated": bool}}',
                force_model="instant", use_cache=True,
            )
            return json.loads(result.strip())
        except Exception:
            return {"sentiment": "neutral", "confidence": 0.5, "correction_indicated": False}

    def generate_synthetic_training_data(self, n: int = 20) -> list:
        """Dream mode: paraphrase real exchanges into training variations."""
        from core.memory import _load
        from core.llm.router import think
        from config.settings import CONVERSATIONS_FILE

        conversations = _load(CONVERSATIONS_FILE) or []
        if len(conversations) < 10:
            return []

        import random
        samples = random.sample(conversations, min(n, len(conversations)))

        synthetic = []
        for turn in samples:
            user, ai = turn.get("user", ""), turn.get("ai", "")
            if not user or not ai:
                continue
            try:
                variations = think(
                    f"Generate 2 paraphrased versions of this question that mean "
                    f"the same thing:\nOriginal: {user}\n\nReturn as JSON array of 2 strings only.",
                    force_model="instant",
                )
                clean = re.sub(r"```json|```", "", variations).strip()
                paraphrases = json.loads(clean)
                for p in paraphrases[:2]:
                    synthetic.append({"instruction": p, "output": ai, "synthetic": True})
            except Exception:
                continue

        return synthetic

    def weekly_learning_cycle(self) -> dict:
        """Full weekly cycle: collect corrections/feedback, generate synthetic
        data, retrain, report. Runs Sunday 4am via the scheduler."""
        print("[ActiveLearner] Starting weekly learning cycle...")
        from services.fine_tuning import fine_tuner

        corrections = self._load(CORRECTIONS_FILE)
        feedback = self._load(FEEDBACK_FILE)
        synthetic = self.generate_synthetic_training_data(50)
        result = fine_tuner.build_personal_model()

        report = {
            "week_ending": datetime.now().isoformat(), "corrections": len(corrections),
            "feedback_items": len(feedback), "synthetic_examples": len(synthetic),
            "retrain_success": result.get("success", False), "model": result.get("model", ""),
        }

        if result.get("success"):
            try:
                from core.event_bus import bus
                bus.system(
                    f"Weekly learning cycle complete. I've processed {len(corrections)} "
                    f"corrections and {len(synthetic)} synthetic examples. Personal model updated."
                )
            except Exception:
                pass

        return report

    def _load(self, path: Path) -> list:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return []
        return []

    def _save(self, path: Path, data: list):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data[-2000:], indent=2))


learner = ActiveLearner()
