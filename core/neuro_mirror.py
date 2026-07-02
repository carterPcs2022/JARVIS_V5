"""
core/neuro_mirror.py — Models how YOU think: analytical vs intuitive,
detail vs big-picture, direct vs exploratory. Responses aligned to your
actual cognitive style rather than generic best practice.

analyze_thinking_style() costs one LLM call — run periodically (weekly),
not per-message. get_style_prompt() is free (reads a cached profile) and
is safe to inject into every system prompt. align_response() costs an
extra LLM call per response it touches — available, but not auto-wired
into the default chat path for that reason.
"""
import json
import re
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR

_NEURO_FILE = BASE_DIR / "memory" / "neuro_profile.json"


class NeuroMirror:

    def __init__(self):
        self.profile = self._load()

    def analyze_thinking_style(self, conversations: list) -> dict:
        from core.llm.router import think

        sample = conversations[-30:]
        combined = "\n".join(f"User: {t.get('user', '')}" for t in sample if t.get("user"))
        if not combined.strip():
            return self.profile

        analysis = think(
            f"Analyze the cognitive and communication patterns in these messages. Identify:\n"
            f"1. Thinking style (analytical/intuitive/mixed)\n2. Information preference (detail/big-picture)\n"
            f"3. Communication style (direct/exploratory)\n4. Decision approach (data-driven/instinct)\n"
            f"5. Problem framing style\n\nMessages:\n{combined[:2000]}\n\n"
            f"Reply as JSON with these exact keys: thinking_style, info_preference, "
            f"comm_style, decision_approach, problem_framing, confidence",
            force_model="reasoning",
        )
        try:
            clean = re.sub(r"```json|```", "", analysis).strip()
            profile_update = json.loads(clean)
            self.profile.update(profile_update)
            self.profile["updated"] = datetime.now().isoformat()
            self._save()
            return self.profile
        except Exception:
            return {}

    def align_response(self, response: str, query: str) -> str:
        """Adjust a response to match the user's thinking style. Costs one
        extra LLM call — call deliberately, not automatically per-message."""
        if not self.profile:
            return response

        from core.llm.router import think
        style = self.profile.get("thinking_style", "mixed")
        info_pref = self.profile.get("info_preference", "mixed")
        comm = self.profile.get("comm_style", "direct")

        if style == "analytical" and info_pref == "detail":
            return response

        if comm == "direct" and len(response.split()) > 100:
            return think(
                f"Condense this response to be more direct and concise "
                f"without losing key information:\n\n{response}", force_model="instant",
            )

        if info_pref == "big-picture":
            return think(
                f"Rewrite this starting with a one-sentence summary, then details:\n\n{response}",
                force_model="instant",
            )

        return response

    def get_style_prompt(self) -> str:
        """Free — reads the cached profile, no LLM call. Safe to inject
        into every system prompt build."""
        if not self.profile:
            return ""

        style = self.profile.get("thinking_style", "")
        info_pref = self.profile.get("info_preference", "")
        comm = self.profile.get("comm_style", "")

        instructions = []
        if style == "analytical":
            instructions.append("User thinks analytically. Support claims with reasoning. Structure matters.")
        elif style == "intuitive":
            instructions.append("User thinks intuitively. Lead with conclusions. Trust their instincts.")

        if info_pref == "big-picture":
            instructions.append("Lead with the summary. Details second.")
        elif info_pref == "detail":
            instructions.append("Provide complete detail. Nothing omitted.")

        if comm == "direct":
            instructions.append("Be extremely direct. No preamble.")

        return "\n".join(instructions)

    def _load(self) -> dict:
        if _NEURO_FILE.exists():
            try:
                return json.loads(_NEURO_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        _NEURO_FILE.parent.mkdir(parents=True, exist_ok=True)
        _NEURO_FILE.write_text(json.dumps(self.profile, indent=2))


neuro = NeuroMirror()
