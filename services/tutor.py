"""services/tutor.py — JARVIS teaches you things using proven learning techniques."""
import json
from pathlib import Path
from config.settings import BASE_DIR

FLASHCARDS_FILE = BASE_DIR / "memory" / "flashcards.json"


def _load_cards() -> dict:
    if FLASHCARDS_FILE.exists():
        try:
            return json.loads(FLASHCARDS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_cards(data: dict):
    FLASHCARDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FLASHCARDS_FILE.write_text(json.dumps(data, indent=2))


class JarvisTutor:

    def explain(self, topic: str, level: str = "auto") -> str:
        from core.llm.router import think

        if level == "auto":
            try:
                from core.memory import get_profile
                vocab = get_profile().get("vocab", "medium")
                level = "expert" if vocab == "advanced" else "beginner" if vocab == "simple" else "intermediate"
            except Exception:
                level = "intermediate"

        level_directions = {
            "eli5":         "Explain like I'm five years old. Simple words, concrete analogies.",
            "beginner":     "Explain for a complete beginner. Define jargon. Use everyday analogies.",
            "intermediate": "Explain assuming general background knowledge but no specialist expertise.",
            "expert":       "Explain at an expert level. Precise terminology, no hand-holding.",
        }
        direction = level_directions.get(level, level_directions["intermediate"])
        return think(f"{direction}\n\nTopic: {topic}", max_tokens=500)

    def socratic_mode(self, topic: str, prior_exchange: str = "") -> str:
        from core.llm.router import think
        prompt = (
            f"You are teaching '{topic}' using the Socratic method — never give the "
            f"answer directly, ask a guiding question instead that leads the student to "
            f"discover it themselves.\n\n"
            + (f"Prior exchange:\n{prior_exchange}\n\n" if prior_exchange else "")
            + "Ask the next guiding question (one question only)."
        )
        return think(prompt, max_tokens=150)

    def flashcard_session(self, topic: str, n_cards: int = 10) -> list[dict]:
        from core.llm.router import think
        raw = think(
            f"Generate {n_cards} flashcards for '{topic}'. Format each as "
            f"'Q: <question> | A: <answer>' on its own line.",
            max_tokens=800,
        )
        cards = []
        for line in raw.split("\n"):
            if "Q:" in line and "A:" in line and "|" in line:
                q_part, a_part = line.split("|", 1)
                q = q_part.split("Q:", 1)[1].strip()
                a = a_part.split("A:", 1)[1].strip()
                cards.append({"question": q, "answer": a, "correct_count": 0, "wrong_count": 0})

        data = _load_cards()
        data.setdefault(topic, [])
        data[topic].extend(cards)
        _save_cards(data)
        return cards

    def review_card(self, topic: str, question: str, correct: bool) -> dict:
        data = _load_cards()
        for card in data.get(topic, []):
            if card["question"] == question:
                card["correct_count" if correct else "wrong_count"] += 1
                _save_cards(data)
                return card
        return {"error": "card not found"}

    def due_cards(self, topic: str, limit: int = 10) -> list[dict]:
        """Prioritize cards you've struggled with (more wrong than right)."""
        data = _load_cards()
        cards = data.get(topic, [])
        cards_sorted = sorted(cards, key=lambda c: c.get("wrong_count", 0) - c.get("correct_count", 0), reverse=True)
        return cards_sorted[:limit]

    def quiz_me(self, topic: str, difficulty: str = "medium") -> dict:
        from core.llm.router import think
        raw = think(
            f"Write one {difficulty}-difficulty quiz question about '{topic}' with 4 "
            f"multiple choice options (A-D) and indicate the correct answer. Format:\n"
            f"Q: ...\nA) ...\nB) ...\nC) ...\nD) ...\nCorrect: <letter>",
            max_tokens=300,
        )
        return {"topic": topic, "difficulty": difficulty, "quiz": raw}

    def language_lesson(self, language: str, lesson_type: str = "vocabulary") -> dict:
        from core.llm.router import think
        type_prompts = {
            "vocabulary":   f"Teach 10 useful {language} vocabulary words with pronunciation guides and example sentences.",
            "grammar":      f"Explain one useful {language} grammar rule with 3 example sentences.",
            "conversation": f"Write a short practice conversation scenario in {language} with English translation.",
            "pronunciation": f"Give phonetic pronunciation guides for 10 common {language} words/phrases.",
        }
        prompt = type_prompts.get(lesson_type, type_prompts["vocabulary"])
        return {"language": language, "lesson_type": lesson_type, "content": think(prompt, max_tokens=500)}

    def study_plan(self, subject: str, goal: str, weeks: int = 4) -> dict:
        from core.llm.router import think
        prompt = (
            f"Build a {weeks}-week study plan for '{subject}' with the goal: '{goal}'.\n"
            "Week by week breakdown, daily study duration suggestion, resources to use, "
            "and milestones to hit each week."
        )
        return {"subject": subject, "goal": goal, "weeks": weeks, "plan": think(prompt, max_tokens=800)}

    def explain_error(self, error_message: str, language: str = "python") -> str:
        from core.llm.router import think
        return think(
            f"Explain this {language} error clearly: what it means, likely cause, and "
            f"how to fix it.\n\nError:\n{error_message}",
            max_tokens=400,
        )


tutor = JarvisTutor()
