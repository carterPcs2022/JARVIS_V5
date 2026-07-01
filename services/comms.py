"""
services/comms.py — CommunicationsIntelligence: drafting, follow-ups, translation, transcription.
"""
import json
import uuid
from datetime import datetime, date
from pathlib import Path

from core.llm.router import think
from core.event_bus import bus

_PEOPLE_FILE    = Path("/Users/kisha/Downloads/JARVIS_V5/memory/people.json")
_FOLLOWUPS_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/followups.json")


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


class CommunicationsIntelligence:

    # ------------------------------------------------------------------ #
    # Messaging                                                            #
    # ------------------------------------------------------------------ #

    def draft_message(self, recipient: str, intent: str, channel: str = "email") -> dict:
        """LLM drafts a message — never sent automatically."""
        prompt = (
            f"Draft a {channel} message to {recipient}. "
            f"Intent: {intent}. "
            "Write in JARVIS's typical professional but warm voice. Be concise and clear."
        )
        draft = think(prompt)
        return {
            "draft": draft,
            "recipient": recipient,
            "channel": channel,
            "status": "awaiting_approval",
            "note": (
                "PROTOCOL 1: Message requires explicit approval before sending. "
                "JARVIS never sends automatically."
            ),
        }

    # ------------------------------------------------------------------ #
    # People context                                                       #
    # ------------------------------------------------------------------ #

    def get_people_context(self, person_name: str) -> str:
        """Return stored context for a person from memory/people.json."""
        people = _load_json(_PEOPLE_FILE, {})

        # Support both dict-of-name and list-of-record formats
        if isinstance(people, list):
            for p in people:
                if p.get("name", "").lower() == person_name.lower():
                    return json.dumps(p, indent=2)
        elif isinstance(people, dict):
            for key, val in people.items():
                if key.lower() == person_name.lower():
                    return json.dumps(val, indent=2)

        return f"No stored context for {person_name}."

    # ------------------------------------------------------------------ #
    # Meeting prep                                                         #
    # ------------------------------------------------------------------ #

    def meeting_prep(self, person_name: str) -> str:
        """Generate a comprehensive meeting brief for a person."""
        context = self.get_people_context(person_name)
        prompt = (
            f"Generate a comprehensive meeting brief for a meeting with {person_name}.\n"
            f"Known context: {context}\n\n"
            "Include: key talking points, things to remember, any open items, "
            "suggested agenda, and tips for the conversation. Be practical and specific."
        )
        return think(prompt)

    # ------------------------------------------------------------------ #
    # Follow-up tracker                                                    #
    # ------------------------------------------------------------------ #

    def follow_up_tracker(self) -> list:
        """Return all follow-ups sorted by due_date, with overdue flagged."""
        followups = _load_json(_FOLLOWUPS_FILE, [])
        today_str = date.today().isoformat()

        for f in followups:
            if f.get("status") == "pending":
                f["overdue"] = f.get("due_date", "9999-99-99") < today_str
            else:
                f["overdue"] = False

        return sorted(followups, key=lambda x: x.get("due_date", "9999-99-99"))

    def add_follow_up(self, person: str, context: str, due_date: str) -> dict:
        """Add a new follow-up entry to memory/followups.json."""
        followups = _load_json(_FOLLOWUPS_FILE, [])

        new_entry = {
            "id": str(uuid.uuid4()),
            "person": person,
            "context": context,
            "due_date": due_date,
            "created": datetime.now().isoformat(),
            "status": "pending",
        }
        followups.append(new_entry)
        _save_json(_FOLLOWUPS_FILE, followups)
        return new_entry

    def complete_follow_up(self, follow_up_id: str) -> dict:
        """Mark a follow-up as complete."""
        followups = _load_json(_FOLLOWUPS_FILE, [])

        for f in followups:
            if f.get("id") == follow_up_id:
                f["status"] = "complete"
                f["completed_at"] = datetime.now().isoformat()
                _save_json(_FOLLOWUPS_FILE, followups)
                return f

        return {"error": f"Follow-up {follow_up_id} not found."}

    # ------------------------------------------------------------------ #
    # Translation                                                          #
    # ------------------------------------------------------------------ #

    def translation(self, text: str, target_lang: str) -> dict:
        """Translate text — tries LibreTranslate, falls back to LLM."""
        try:
            import requests as _requests
            resp = _requests.post(
                "http://libretranslate.com/translate",
                json={
                    "q": text,
                    "source": "auto",
                    "target": target_lang,
                    "format": "text",
                },
                timeout=8,
            )
            resp.raise_for_status()
            translated = resp.json().get("translatedText", "")
            if translated:
                return {"translation": translated, "source": "libretranslate"}
        except Exception:
            pass

        # LLM fallback
        translated = think(f"Translate to {target_lang}: {text}")
        return {"translation": translated, "source": "llm"}

    # ------------------------------------------------------------------ #
    # Call transcription                                                   #
    # ------------------------------------------------------------------ #

    def call_transcription(self, audio_path: str) -> dict:
        """Transcribe a call and extract structured intelligence."""
        from services.voice import transcribe

        transcript = transcribe(audio_path)

        prompt = (
            f"Analyze this call transcript and extract structured information.\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Return a JSON object with keys:\n"
            '  "action_items": list of action items mentioned\n'
            '  "decisions": list of decisions made\n'
            '  "people": list of people mentioned\n'
            '  "summary": one-paragraph summary\n'
            "Return only valid JSON."
        )
        raw = think(prompt)

        try:
            import re
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(json_match.group(0)) if json_match else {}
        except Exception:
            parsed = {}

        return {
            "transcript": transcript,
            "action_items": parsed.get("action_items", []),
            "decisions": parsed.get("decisions", []),
            "people": parsed.get("people", []),
            "summary": parsed.get("summary", raw),
        }


# Module-level singleton
comms = CommunicationsIntelligence()
