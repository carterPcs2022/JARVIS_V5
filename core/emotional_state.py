"""core/emotional_state.py — JARVIS's functional emotional state display.

Not simulated feelings — a derived operational state from objective metrics,
displayed in the HUD so JARVIS feels alive the way movie-JARVIS did.
"""
from datetime import datetime

JARVIS_STATES = {
    "nominal":    {"color": "#00ffcc", "label": "NOMINAL",    "icon": "◎"},
    "alert":      {"color": "#ffaa00", "label": "ALERT",      "icon": "◈"},
    "focused":    {"color": "#00b4ff", "label": "FOCUSED",    "icon": "◉"},
    "processing": {"color": "#aa88ff", "label": "PROCESSING", "icon": "◌"},
    "concerned":  {"color": "#ff8800", "label": "CONCERNED",  "icon": "◐"},
    "critical":   {"color": "#ff3333", "label": "CRITICAL",   "icon": "◆"},
    "degraded":   {"color": "#ff3333", "label": "DEGRADED",   "icon": "◇"},
    "scattered":  {"color": "#ffffff", "label": "SCATTERED",  "icon": "·"},
    "dreaming":   {"color": "#8844ff", "label": "DREAMING",   "icon": "◍"},
}

_DESCRIPTIONS = {
    "nominal":    "All systems nominal. Operating at full capacity.",
    "alert":      "Alert status. Sentinel has flagged unusual activity.",
    "focused":    "Focused on an active task. Attention narrowed.",
    "processing": "Processing a complex task — give me a moment.",
    "concerned":  "Resource usage is elevated. Keeping an eye on it.",
    "critical":   "Critical condition detected. Immediate attention advised.",
    "degraded":   "Operating in a degraded state — some systems are offline.",
    "scattered":  "Distributed across nodes under Protocol 17. Reassembly pending.",
    "dreaming":   "In dream cycle — reflecting and consolidating memory.",
}


class EmotionalState:
    def __init__(self):
        self._state = "nominal"
        self._history: list[dict] = []
        self._updated = datetime.now().isoformat()

    def update(self) -> dict:
        """Derive JARVIS's current state from objective system metrics."""
        state = "nominal"
        try:
            from core.protocols import is_lockdown, is_friday
            if is_lockdown():
                state = "critical"
            elif is_friday():
                state = "degraded"
        except Exception:
            pass

        if state == "nominal":
            try:
                from core.scatter import ScatterEngine
                import os
                if os.path.exists(os.path.expanduser("~/.jarvis_scatter/resurrection_manifest.enc")):
                    state = "scattered"
            except Exception:
                pass

        if state == "nominal":
            try:
                from services.sentinel import summary
                s = summary()
                sev = s.get("by_severity", {})
                if sev.get("high", 0) > 0 or sev.get("critical", 0) > 0:
                    state = "alert"
            except Exception:
                pass

        if state == "nominal":
            try:
                from core.tools.system import snapshot
                snap = snapshot()
                if snap.get("cpu_percent", 0) > 90 or snap.get("ram_used_pct", 0) > 90:
                    state = "concerned"
            except Exception:
                pass

        if state == "nominal":
            try:
                from services.elevenlabs_voice import get_budget_status
                b = get_budget_status()
                if b.get("pct_used", 0) > 90:
                    state = "concerned"
            except Exception:
                pass

        self._state = state
        self._updated = datetime.now().isoformat()
        self._history.append({"state": state, "ts": self._updated})
        self._history = self._history[-500:]
        return self.get()

    def get(self) -> dict:
        meta = JARVIS_STATES.get(self._state, JARVIS_STATES["nominal"])
        return {"state": self._state, "updated": self._updated, **meta}

    def describe(self) -> str:
        return _DESCRIPTIONS.get(self._state, _DESCRIPTIONS["nominal"])

    def set_state(self, state: str) -> dict:
        """Manually force a state (e.g. 'processing' while a task runs, 'dreaming' during dream cycle)."""
        if state in JARVIS_STATES:
            self._state = state
            self._updated = datetime.now().isoformat()
            self._history.append({"state": state, "ts": self._updated})
            self._history = self._history[-500:]
        return self.get()

    def history(self, hours: int = 24) -> list[dict]:
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)
        return [h for h in self._history if datetime.fromisoformat(h["ts"]) >= cutoff]


emotional_state = EmotionalState()
