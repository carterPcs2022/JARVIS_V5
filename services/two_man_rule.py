"""services/two_man_rule.py — no single party can trigger the most
destructive actions alone, even with a valid token.

Scoping note: core/protocols.py's coldfire/lockdown already have a
double-confirmation flow (request_avengers_confirmation +
confirm_avengers — a time-boxed token you confirm back within 60s). That's
single-party-confirms-twice, which is real protection against an
accidental/automated call, but not true multi-party authorization — it
doesn't require a second, distinct secret held by a different person.
This module adds that as a genuinely separate mechanism, available for
whichever destructive actions you choose to gate with it — it does NOT
replace or get auto-wired into the existing coldfire/lockdown flow, since
forcing two distinct secrets onto an already-working single-user flow
would just lock you out unless you already have a second party's secret
ready to go."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import BASE_DIR, API_TOKEN, AVENGERS_PASSPHRASE, PEPPER_TOKEN

PENDING_FILE = BASE_DIR / "memory" / "pending_authorizations.json"

CRITICAL_ACTIONS = {
    "coldfire": {"required_parties": 2, "expiry_seconds": 300},
    "scatter": {"required_parties": 2, "expiry_seconds": 300},
    "reset_baseline": {"required_parties": 2, "expiry_seconds": 120},
    "delete_memory": {"required_parties": 2, "expiry_seconds": 120},
    "security_override": {"required_parties": 2, "expiry_seconds": 60},
    "disable_sentinel": {"required_parties": 2, "expiry_seconds": 60},
}


def _authorized_parties() -> dict:
    return {"primary": API_TOKEN, "secondary": AVENGERS_PASSPHRASE, "pepper": PEPPER_TOKEN}


class TwoManRule:

    def initiate_action(self, action: str, initiator_token: str, reason: str = "") -> dict:
        if action not in CRITICAL_ACTIONS:
            return {"error": f"Unknown critical action: {action}"}

        config = CRITICAL_ACTIONS[action]

        if not self._verify_party(initiator_token):
            return {"error": "Initiator not authorized"}

        auth_id = secrets.token_urlsafe(16)
        pending = {
            "id": auth_id, "action": action, "reason": reason,
            "initiator": self._hash_token(initiator_token),
            "approvals": [self._hash_token(initiator_token)],
            "required": config["required_parties"],
            "expires_at": (datetime.now() + timedelta(seconds=config["expiry_seconds"])).isoformat(),
            "status": "pending", "created": datetime.now().isoformat(),
        }
        self._save_pending(auth_id, pending)

        from core.event_bus import bus
        bus.alert(
            f"Two-Man Rule initiated: {action}. Authorization ID: {auth_id}. "
            f"Requires {config['required_parties']} approvals. Expires in {config['expiry_seconds']}s.",
            severity="high", category="TWO_MAN_RULE",
        )

        return {
            "auth_id": auth_id, "action": action, "status": "awaiting_second_approval",
            "expires_in": config["expiry_seconds"], "approvals_needed": config["required_parties"] - 1,
        }

    def approve_action(self, auth_id: str, approver_token: str) -> dict:
        pending = self._load_pending(auth_id)
        if not pending:
            return {"error": "Authorization not found or expired"}

        if datetime.now() > datetime.fromisoformat(pending["expires_at"]):
            return {"error": "Authorization expired"}

        approver_hash = self._hash_token(approver_token)
        if approver_hash in pending["approvals"]:
            return {"error": "Same party cannot approve twice"}

        if not self._verify_party(approver_token):
            return {"error": "Approver not authorized"}

        pending["approvals"].append(approver_hash)

        if len(pending["approvals"]) >= pending["required"]:
            pending["status"] = "approved"
            self._save_pending(auth_id, pending)
            return {"status": "approved", "action": pending["action"], "execute": True, "auth_id": auth_id}

        self._save_pending(auth_id, pending)
        return {
            "status": "partial_approval", "approvals": len(pending["approvals"]),
            "required": pending["required"], "still_needed": pending["required"] - len(pending["approvals"]),
        }

    def is_approved(self, auth_id: str) -> bool:
        pending = self._load_pending(auth_id)
        return bool(pending and pending.get("status") == "approved")

    def list_pending(self) -> list[dict]:
        return list(self._load_all().values())

    def _verify_party(self, token: str) -> bool:
        return any(hmac.compare_digest(token, party_token)
                  for party_token in _authorized_parties().values() if party_token)

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def _save_pending(self, auth_id: str, data: dict):
        all_pending = self._load_all()
        all_pending[auth_id] = data
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_FILE.write_text(json.dumps(all_pending, indent=2))

    def _load_pending(self, auth_id: str) -> dict | None:
        return self._load_all().get(auth_id)

    def _load_all(self) -> dict:
        if PENDING_FILE.exists():
            try:
                return json.loads(PENDING_FILE.read_text())
            except Exception:
                return {}
        return {}


two_man = TwoManRule()
