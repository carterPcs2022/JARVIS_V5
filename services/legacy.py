"""services/legacy.py — Digital Legacy Protocol.

Defines what happens to JARVIS and your data if you're incapacitated or gone.
Stored encrypted; never exposed in the normal HUD. Requires master token auth.
"""
import json
from datetime import datetime
from pathlib import Path
from config.settings import BASE_DIR, EMERGENCY_CONTACT_EMAIL, EMERGENCY_CONTACT_NAME, INACTIVITY_DAYS

LEGACY_FILE = BASE_DIR / "memory" / "legacy.json.enc"


def _load() -> dict:
    if not LEGACY_FILE.exists():
        return {}
    try:
        from core.crypto import open_sealed
        from config.settings import SECRET_KEY
        raw = LEGACY_FILE.read_bytes()
        return json.loads(open_sealed(raw, SECRET_KEY).decode())
    except Exception as e:
        print(f"[Legacy] Failed to decrypt legacy.json.enc: {e}")
        return {}


def _save(data: dict):
    try:
        from core.crypto import seal
        from config.settings import SECRET_KEY
        LEGACY_FILE.parent.mkdir(parents=True, exist_ok=True)
        blob = seal(json.dumps(data).encode(), SECRET_KEY)
        LEGACY_FILE.write_bytes(blob)
    except Exception as e:
        print(f"[Legacy] Failed to encrypt legacy config: {e}")


class DigitalLegacy:

    def set_emergency_contact(self, name: str, email: str, access_level: str = "read_only") -> dict:
        data = _load()
        data["emergency_contact"] = {"name": name, "email": email, "access_level": access_level}
        _save(data)
        return data["emergency_contact"]

    def set_inactivity_protocol(self, days: int = 30) -> dict:
        data = _load()
        data["inactivity_days"] = days
        data["last_configured"] = datetime.now().isoformat()
        _save(data)
        return {"inactivity_days": days}

    def write_final_message(self, message: str) -> dict:
        data = _load()
        data["final_message"] = message
        data["final_message_set"] = datetime.now().isoformat()
        _save(data)
        return {"ok": True, "set_at": data["final_message_set"]}

    def data_will(self, categories: dict | None = None) -> dict:
        """categories: e.g. {"conversations": "keep", "financial": "delete", "projects": "transfer"}"""
        data = _load()
        if categories:
            data["data_will"] = categories
            _save(data)
        return data.get("data_will", {
            "conversations": "keep", "financial": "delete",
            "health": "delete", "projects": "keep",
        })

    def legacy_status(self) -> dict:
        data = _load()
        days_since_interaction = None
        try:
            from core.state import state
            last = state.get("last_interaction")
            if last:
                days_since_interaction = (datetime.now() - datetime.fromisoformat(last)).days
        except Exception:
            pass

        return {
            "emergency_contact": data.get("emergency_contact"),
            "inactivity_days":   data.get("inactivity_days", INACTIVITY_DAYS),
            "final_message_set": bool(data.get("final_message")),
            "data_will":         data.get("data_will", {}),
            "days_since_last_interaction": days_since_interaction,
        }

    def check_inactivity(self) -> dict:
        """Called periodically (e.g. daily) to check if the inactivity protocol should trigger."""
        status = self.legacy_status()
        threshold = status["inactivity_days"]
        days = status["days_since_last_interaction"]

        if days is None or days < threshold:
            return {"triggered": False}

        contact = status.get("emergency_contact")
        if not contact:
            return {"triggered": False, "reason": "no emergency contact configured"}

        try:
            from core.protocols import start_endgame_loop
            from services.backup import backup_all
            backup_all()
        except Exception:
            pass

        try:
            from core.event_bus import bus
            bus.alert(
                f"Inactivity protocol: no interaction for {days} days (threshold: {threshold}). "
                f"Emergency contact {contact['name']} would be notified.",
                "critical", category="LEGACY_PROTOCOL"
            )
        except Exception:
            pass

        return {"triggered": True, "days_inactive": days, "contact": contact}


digital_legacy = DigitalLegacy()
