"""services/emcon.py — Emissions Control. Voluntary, explicit dial-down of
outbound activity (voice announcements, non-essential endpoints), separate
from services/friday_protocols.py-style automatic degradation — this one
only ever changes because someone asked it to."""
from datetime import datetime

EMCON_LEVELS = {
    1: "Restrict non-essential API calls",
    2: "Disable non-essential logging",
    3: "Minimal operations only — health + core chat",
    4: "Complete radio silence — health check only",
}


class EMCON:

    def __init__(self):
        self.active = False
        self.level = 0
        self.activated = None

    def activate(self, level: int = 2, reason: str = "") -> dict:
        self.active = True
        self.level = level
        self.activated = datetime.now()

        try:
            from services.voice import speak
            speak(f"EMCON level {level} active. Minimizing digital footprint.")
        except Exception:
            pass

        return {"active": True, "level": level, "desc": EMCON_LEVELS.get(level, ""), "reason": reason}

    def deactivate(self) -> dict:
        was_level = self.level
        self.active = False
        self.level = 0

        try:
            from services.voice import speak
            speak("EMCON deactivated. Normal operations resumed.")
        except Exception:
            pass

        return {"active": False, "was_level": was_level}

    def should_allow(self, operation: str) -> bool:
        """Check before processing a non-essential request. Health/chat/
        voice always pass regardless of level, so EMCON can never lock the
        owner out of the assistant entirely — only trim what surrounds it."""
        if not self.active:
            return True

        always_allowed = ("health", "chat", "voice", "stark/chat", "ws/chat")
        if any(a in operation for a in always_allowed):
            return True

        if self.level >= 4:
            return "health" in operation
        if self.level >= 3:
            return False

        return True

    def status(self) -> dict:
        return {
            "active": self.active, "level": self.level,
            "desc": EMCON_LEVELS.get(self.level, "Inactive"),
            "activated": self.activated.isoformat() if self.activated else None,
        }


emcon = EMCON()
