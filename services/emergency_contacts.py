"""services/emergency_contacts.py — Real people to alert in a distress
situation, via the existing Twilio phone integration (services/phone.py).

Deliberately NOT a 911/emergency-dispatch integration: JARVIS has no way to
verify a real emergency, most 911 centers won't accept an unattended
automated call, and a false report to actual dispatch carries real legal
risk. This alerts a small list of real people the user has designated —
family, friends, a personal contact who happens to be a first responder —
by SMS and/or a real phone call, so an actual human who knows the user's
situation can judge whether to call EMS.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
_CONTACTS_FILE = Path("data/emergency_contacts.json")


def _load() -> list[dict]:
    _CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _CONTACTS_FILE.exists():
        try:
            return json.loads(_CONTACTS_FILE.read_text())
        except Exception:
            pass
    return []


def _save(contacts: list[dict]):
    _CONTACTS_FILE.write_text(json.dumps(contacts, indent=2))


def add_contact(name: str, phone: str, call: bool = True, sms: bool = True) -> dict:
    if not name or not phone:
        return {"ok": False, "error": "Both name and phone are required"}
    contacts = [c for c in _load() if c["name"].lower() != name.lower()]  # replace if re-added
    contacts.append({"name": name, "phone": phone, "call": call, "sms": sms})
    _save(contacts)
    return {"ok": True, "contacts": contacts}


def remove_contact(name: str) -> dict:
    contacts = _load()
    remaining = [c for c in contacts if c["name"].lower() != name.lower()]
    if len(remaining) == len(contacts):
        return {"ok": False, "error": f"No contact named '{name}'"}
    _save(remaining)
    return {"ok": True, "contacts": remaining}


def list_contacts() -> list[dict]:
    return _load()


def alert_all(message: str, reason: str = "distress") -> dict:
    """Text and/or call every configured contact with `message`. Best-effort
    per contact — one failing (bad number, Twilio down) never blocks the
    rest, since in a real distress situation reaching *someone* matters
    more than a clean all-or-nothing result."""
    contacts = _load()
    if not contacts:
        log.warning("Emergency alert triggered (%s) but no emergency contacts configured", reason)
        return {"ok": False, "error": "No emergency contacts configured", "results": []}

    from services.messaging import send_sms
    from services.phone import phone, _twilio_configured

    if not _twilio_configured():
        return {"ok": False, "error": "Twilio not configured", "results": []}

    results = []
    for contact in contacts:
        entry = {"name": contact["name"], "phone": contact["phone"]}
        if contact.get("sms", True):
            try:
                sms_result = send_sms(message, to=contact["phone"])
                entry["sms"] = sms_result
            except Exception as e:
                entry["sms"] = {"ok": False, "error": str(e)}
        if contact.get("call", True):
            try:
                entry["call"] = phone.send_alert_call(message, contact["phone"])
            except Exception as e:
                entry["call"] = {"error": str(e)}
        results.append(entry)
        log.info("Emergency alert (%s) sent to %s", reason, contact["name"])

    return {"ok": True, "reason": reason, "contacts_notified": len(results), "results": results}
