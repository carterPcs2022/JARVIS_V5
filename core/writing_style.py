"""core/writing_style.py — learns the user's writing style from samples,
then writes/rewrites content to match it."""
import json
import re

from config.settings import BASE_DIR

STYLE_FILE = BASE_DIR / "memory" / "writing_style.json"


class WritingStyleEngine:

    def analyze_style(self, samples: list[str]) -> dict:
        """"JARVIS learn how I write from these emails/messages" """
        from core.llm.router import think
        combined = "\n\n---\n\n".join(samples[:5])
        analysis = think(
            f"Analyze the writing style in these samples:\n\n{combined[:3000]}\n\n"
            f"Identify:\n1. Sentence length patterns\n2. Vocabulary level and preferences\n"
            f"3. Tone (formal/casual/etc)\n4. Common phrases and expressions\n"
            f"5. Punctuation habits\n6. How they open and close messages\n"
            f"7. Overall personality that comes through\n\n"
            f"Reply as JSON with these as keys.",
            force_model="opus",
        )
        try:
            clean = re.sub(r"```json|```", "", analysis).strip()
            style = json.loads(clean)
            self._save(style)
            return style
        except Exception:
            return {"raw": analysis}

    def write_in_my_style(self, content: str, format: str = "message") -> str:
        style = self._load()
        if not style:
            return content

        from core.llm.router import think
        return think(
            f"Rewrite this in the user's exact writing style:\n\n"
            f"Content: {content}\n\nTheir style profile: {json.dumps(style)}\n\n"
            f"Format: {format}\nMake it sound exactly like them. Not like an AI.",
            force_model="sonnet",
        )

    def _load(self) -> dict:
        if STYLE_FILE.exists():
            try:
                return json.loads(STYLE_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, style: dict):
        STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STYLE_FILE.write_text(json.dumps(style, indent=2))


writing_style = WritingStyleEngine()
