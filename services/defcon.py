"""services/defcon.py — Defense Readiness Condition. Five levels, each
tied to progressively more restrictive protocols. Auto-assessment reads
services/siem.py's real threat_level (GREEN/YELLOW/ORANGE/RED) — the
source spec called sentinel.get_threat_count()/ai_firewall.set_sensitivity(),
neither of which exists; siem.get_threat_level() is the real aggregate
signal already computed from actual event history."""
import json
from pathlib import Path
from datetime import datetime
from enum import IntEnum

DEFCON_FILE = Path("memory/defcon.json")


class DEFCON(IntEnum):
    FIVE = 5   # Normal peacetime
    FOUR = 4   # Elevated intelligence
    THREE = 3  # Guarded
    TWO = 2    # High
    ONE = 1    # Maximum — never set automatically

DEFCON_DESCRIPTIONS = {
    5: "NORMAL — Standard operations. All systems nominal.",
    4: "ELEVATED — Increased activity. Enhanced monitoring.",
    3: "GUARDED — AI firewall at maximum sensitivity. Increased scan frequency.",
    2: "HIGH — Maximum security posture. Two-man rule active for critical actions.",
    1: "MAXIMUM — Emergency footing. Manual-only; never set by auto-assessment.",
}

# Actions are logged/descriptive intents, not fictional API calls — only
# hooks that actually exist on the target modules are invoked in
# _execute_action(). Everything else here documents intent for the HUD/log.
DEFCON_ACTIONS = {
    4: ["Increase monitoring frequency", "Alert user to elevated activity"],
    3: ["Increase Sentinel scan frequency", "Log elevated posture to SIEM"],
    2: ["Disable non-essential external API calls", "Require Gold Code for protocol changes"],
    1: ["Full EMCON", "Emergency contact notification"],
}

_THREAT_LEVEL_TO_DEFCON = {"GREEN": 5, "YELLOW": 4, "ORANGE": 3, "RED": 2}


class DefconSystem:

    def __init__(self):
        self.level = self._load()
        self.history = []

    def set(self, level: int, reason: str = "") -> dict:
        if level not in range(1, 6):
            return {"error": "DEFCON must be 1-5"}

        old_level = self.level
        self.level = level

        actions_taken = []
        if level < old_level:  # Escalating toward higher readiness
            for l in range(level, old_level):
                for action in DEFCON_ACTIONS.get(l, []):
                    self._execute_action(action)
                    actions_taken.append(action)

        try:
            from services.voice import speak
            desc = DEFCON_DESCRIPTIONS.get(level, "")
            speak(f"DEFCON {level}. {desc.split('—')[1].strip() if '—' in desc else desc}")
        except Exception:
            pass

        entry = {
            "from": old_level, "to": level, "reason": reason,
            "ts": datetime.now().isoformat(), "actions": actions_taken,
        }
        self.history.append(entry)
        self._save()

        try:
            from core.event_bus import bus
            bus.alert(f"DEFCON changed: {old_level} -> {level}. {reason}",
                     severity="critical" if level <= 2 else "high", category="DEFCON")
        except Exception:
            pass

        return {"level": level, "from": old_level, "desc": DEFCON_DESCRIPTIONS.get(level, ""),
                "actions": actions_taken}

    def auto_assess(self) -> int:
        """Never escalates to DEFCON 1 — that's manual-only, reserved for
        a human call, not a heuristic's."""
        try:
            from services.siem import siem
            target = _THREAT_LEVEL_TO_DEFCON.get(siem.get_threat_level(), 5)
            if target != self.level:
                self.set(target, reason="auto_assessment")
            return target
        except Exception:
            return self.level

    def _execute_action(self, action: str):
        try:
            if "Sentinel scan" in action:
                from services import sentinel
                sentinel._scan()
            elif "SIEM" in action:
                from services.siem import siem
                siem.log_event("DEFCON_ESCALATION", severity="INFO")
        except Exception:
            pass

    def status(self) -> dict:
        return {"level": self.level, "description": DEFCON_DESCRIPTIONS.get(self.level, ""),
                "history": self.history[-10:]}

    def _load(self) -> int:
        if DEFCON_FILE.exists():
            try:
                return json.loads(DEFCON_FILE.read_text()).get("level", 5)
            except Exception:
                return 5
        return 5

    def _save(self):
        try:
            DEFCON_FILE.parent.mkdir(parents=True, exist_ok=True)
            DEFCON_FILE.write_text(json.dumps({
                "level": self.level, "updated": datetime.now().isoformat(),
            }))
        except Exception:
            pass


defcon = DefconSystem()
