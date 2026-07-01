"""core/privacy_mode.py — Ephemeral, zero-logging JARVIS sessions.

When active: no memory writes, no evolution logging, no long-term storage.
Forces the local Ollama model (nothing leaves the machine) and offline TTS.
"""
from datetime import datetime
from config.settings import PRIVACY_MODE_PASSPHRASE


class PrivacyMode:
    def __init__(self):
        self._active = False
        self._session_start: str | None = None
        self._session_history: list[dict] = []

    def enable(self, passphrase: str | None = None) -> dict:
        if PRIVACY_MODE_PASSPHRASE and passphrase != PRIVACY_MODE_PASSPHRASE:
            return {"ok": False, "message": "Incorrect passphrase."}
        self._active = True
        self._session_start = datetime.now().isoformat()
        self._session_history = []
        return {"ok": True, "message": "Privacy mode active. No data will be retained.",
                "started": self._session_start}

    def disable(self) -> dict:
        self._active = False
        turns = len(self._session_history)
        self._session_history = []
        self._session_start = None
        return {"ok": True, "message": "Privacy mode deactivated. Normal operation resumed.",
                "turns_discarded": turns}

    def is_active(self) -> bool:
        return self._active

    def status(self) -> dict:
        return {
            "active": self._active,
            "session_start": self._session_start,
            "turns_this_session": len(self._session_history),
        }

    def private_think(self, user_input: str) -> str:
        """Think without saving anything. Ollama only (local, private)."""
        self._session_history.append({"role": "user", "content": user_input})
        history_context = "\n".join(
            f"{t['role']}: {t['content']}" for t in self._session_history[-10:]
        )

        try:
            from core.llm.ollama import chat as ollama_chat
            from config.settings import JARVIS_PERSONALITY
            messages = [
                {"role": "system", "content": JARVIS_PERSONALITY + "\n\n[PRIVACY MODE ACTIVE — nothing about this conversation will be saved.]"},
                {"role": "system", "content": f"Recent (in-memory only) context:\n{history_context}"},
                {"role": "user", "content": user_input},
            ]
            result = ollama_chat(messages, max_tokens=1024, temperature=0.6)
            response = result.get("content", "")
        except Exception as e:
            response = f"[Privacy mode] Local model unavailable: {e}"

        self._session_history.append({"role": "assistant", "content": response})
        self._session_history = self._session_history[-50:]
        return response


privacy_mode = PrivacyMode()
