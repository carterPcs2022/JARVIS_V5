"""services/situation_room.py — one command activates maximum-monitoring
mode: combat voice, tactical status reporting. Does NOT actually change
polling intervals of other services (system_check, sentinel, etc. run on
their own fixed schedules) — this is a mode flag + on-demand tactical
report, not a scheduler rewrite."""
from datetime import datetime


class SituationRoom:

    def __init__(self):
        self._active = False

    def activate(self, reason: str = "") -> dict:
        self._active = True
        from core.state import state
        state.set("situation_room", True)
        state.set("voice_mode", "combat")

        from core.event_bus import bus
        bus.system(f"Situation room active. All systems at maximum alert. {reason}".strip())

        try:
            from services.elevenlabs_voice import speak_with_mode
            speak_with_mode("Situation room online. All monitoring at maximum. Standing by.", mode="combat")
        except Exception:
            pass

        return {"active": True, "reason": reason, "mode": "SITUATION_ROOM"}

    def deactivate(self) -> dict:
        self._active = False
        from core.state import state
        state.set("situation_room", False)
        state.set("voice_mode", "normal")
        from core.event_bus import bus
        bus.system("Situation room deactivated. Normal operations resumed.")
        return {"active": False}

    def status_report(self) -> dict:
        """Full tactical overview — everything at once."""
        from core.tools.system import snapshot
        from services.sentinel import summary as threat_summary
        from services.network_intel import NetworkIntelligence

        sys_data = snapshot()
        threats = threat_summary()
        internet = NetworkIntelligence().internet_health()

        return {
            "timestamp": datetime.now().isoformat(),
            "system": sys_data, "threats": threats, "network": internet,
            "mode": "SITUATION_ROOM", "all_clear": threats.get("last_24h", 0) == 0,
        }

    def is_active(self) -> bool:
        return self._active


situation_room = SituationRoom()
