"""services/dead_mans_switch.py — if the owner doesn't check in for N
hours, JARVIS assumes something is wrong and escalates.

Distinct from core/protocols.py's existing Protocol 2 Dead Man's Switch:
that one reacts to the JARVIS *process* shutting down (a SIGTERM/SIGHUP
handler that backs up memory). This one reacts to the *owner* going silent
for a configured period — a different trigger, complementary rather than
duplicate. Starts disabled (config["enabled"] defaults False) — monitor()
is a safe no-op until configure() is explicitly called, so scheduling it
hourly by default doesn't risk anything firing unexpectedly."""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

from config.settings import BASE_DIR

DMS_FILE = BASE_DIR / "memory" / "dead_mans_switch.json"


class DeadMansSwitch:

    def __init__(self):
        self.config = self._load()

    def configure(self, check_in_hours: int = 24, warning_hours: int = 12,
                 emergency_contact: str = "", protective_action: str = "alert") -> dict:
        """protective_action: alert | encrypt | scatter."""
        self.config = {
            "enabled": True, "check_in_hours": check_in_hours, "warning_hours": warning_hours,
            "emergency_contact": emergency_contact, "protective_action": protective_action,
            "last_check_in": datetime.now().isoformat(), "status": "active",
            "warning_sent": False, "activated": False,
        }
        self._save()
        return self.config

    def check_in(self) -> dict:
        self.config["last_check_in"] = datetime.now().isoformat()
        self.config["warning_sent"] = False
        self.config["activated"] = False
        self.config["status"] = "active"
        self._save()
        return {
            "status": "checked_in",
            "next_required": (datetime.now() + timedelta(hours=self.config.get("check_in_hours", 24))).isoformat(),
        }

    def monitor(self):
        """Call every hour via the scheduler — no-op unless configured+enabled."""
        if not self.config.get("enabled"):
            return

        last_check_in = datetime.fromisoformat(self.config.get("last_check_in", datetime.now().isoformat()))
        hours_silent = (datetime.now() - last_check_in).total_seconds() / 3600
        check_in_hours = self.config.get("check_in_hours", 24)
        warning_hours = self.config.get("warning_hours", 12)

        from core.event_bus import bus

        if hours_silent >= check_in_hours - warning_hours and not self.config.get("warning_sent"):
            bus.alert(
                f"Dead Man's Switch warning: no check-in for {hours_silent:.0f} hours. "
                f"Check in within {warning_hours} hours or protective actions will activate.",
                severity="high", category="DEAD_MANS_SWITCH",
            )
            self._notify_emergency_contact(
                f"JARVIS has not heard from you in {hours_silent:.0f} hours. Please check in."
            )
            self.config["warning_sent"] = True
            self._save()
        elif hours_silent >= check_in_hours and not self.config.get("activated"):
            self._activate()

    def _activate(self):
        self.config["activated"] = True
        self.config["status"] = "activated"
        self._save()

        from core.event_bus import bus
        action = self.config.get("protective_action", "alert")

        bus.alert(f"DEAD MAN'S SWITCH ACTIVATED. No check-in detected. Executing protective action: {action}",
                 severity="critical", category="DEAD_MANS_SWITCH")
        self._notify_emergency_contact(
            "JARVIS Dead Man's Switch has activated. No check-in received. Protective actions are being taken."
        )

        if action == "scatter":
            try:
                from core.protocols import scatter_identity
                import os as _os
                scatter_identity(_os.getenv("AVENGERS_PASSPHRASE", ""))
            except Exception as e:
                print(f"[DeadMansSwitch] Scatter action failed: {e}")
        elif action == "encrypt":
            try:
                from services.stark_security import stark_security
                stark_security.encrypt_memory_files()
            except Exception as e:
                print(f"[DeadMansSwitch] Encrypt action failed: {e}")

    def _notify_emergency_contact(self, message: str):
        contact = self.config.get("emergency_contact", "")
        if not contact:
            return
        user = os.getenv("PUSHOVER_USER_KEY", "")
        token = os.getenv("PUSHOVER_API_TOKEN", "")
        if user and token:
            import httpx
            httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": token, "user": user, "title": "JARVIS Dead Man's Switch",
                     "message": message, "priority": 2, "retry": 60, "expire": 3600},
                timeout=10,
            )

    def status(self) -> dict:
        last = datetime.fromisoformat(self.config.get("last_check_in", datetime.now().isoformat()))
        hours = (datetime.now() - last).total_seconds() / 3600
        return {
            "enabled": self.config.get("enabled", False), "status": self.config.get("status", "inactive"),
            "hours_silent": round(hours, 1), "activated": self.config.get("activated", False),
            "last_check_in": self.config.get("last_check_in", ""),
        }

    def _load(self) -> dict:
        if DMS_FILE.exists():
            try:
                return json.loads(DMS_FILE.read_text())
            except Exception:
                pass
        return {"enabled": False}

    def _save(self):
        DMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DMS_FILE.write_text(json.dumps(self.config, indent=2))


dms = DeadMansSwitch()
