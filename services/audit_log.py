"""services/audit_log.py — Immutable, cryptographically chained audit log.

Distinct from core/protocols.py's _log_protocol_event (a plain append-only
JSON list already used for per-protocol events): this hash-chains every
entry to the previous one, so altering or deleting any past entry breaks
the chain from that point forward — mathematically detectable, the same
technique used for tamper-evident logs in finance/nuclear-facility systems.
Use this for the subset of actions where "did anyone tamper with this
history" actually matters (chat responses, protocol triggers, security
events); it isn't a replacement for the higher-volume protocol log.
"""
import hashlib
import json
import time
from datetime import datetime

from config.settings import BASE_DIR

AUDIT_FILE = BASE_DIR / "logs" / "immutable_audit.jsonl"


class ImmutableAuditLog:

    def __init__(self):
        self._last_hash = self._get_last_hash()

    def record(self, action: str, actor: str = "jarvis",
               details: dict | None = None, result: str = "success") -> str:
        """Record an action permanently. Each entry is chained to the
        previous one via prev_hash — altering any entry breaks the chain
        for every entry after it."""
        details = details or {}
        ts = time.time()
        entry = {
            "ts": ts,
            "timestamp": datetime.fromtimestamp(ts).isoformat(),
            "action": action,
            "actor": actor,
            "details": details,
            "result": result,
            "prev_hash": self._last_hash,
        }

        entry_json = json.dumps(entry, sort_keys=True)
        entry_hash = hashlib.sha256(entry_json.encode()).hexdigest()
        entry["hash"] = entry_hash
        self._last_hash = entry_hash

        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return entry_hash

    def verify_chain(self) -> dict:
        """Verify the entire audit log chain. Any tampering breaks it."""
        if not AUDIT_FILE.exists():
            return {"valid": True, "entries": 0}

        entries = []
        with open(AUDIT_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass

        if not entries:
            return {"valid": True, "entries": 0}

        prev_hash = "genesis"
        violations = []
        for i, entry in enumerate(entries):
            stored_hash = entry.pop("hash", "")
            expected_prev = entry.get("prev_hash", "")

            if expected_prev != prev_hash:
                violations.append({"entry": i, "issue": "Chain broken — previous hash mismatch"})

            computed = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
            if computed != stored_hash:
                violations.append({
                    "entry": i, "issue": "Hash mismatch — entry may have been altered",
                    "ts": entry.get("timestamp", ""),
                })

            entry["hash"] = stored_hash
            prev_hash = stored_hash

        return {"valid": len(violations) == 0, "entries": len(entries),
                "violations": violations, "last_hash": prev_hash}

    def _get_last_hash(self) -> str:
        if not AUDIT_FILE.exists():
            return "genesis"
        try:
            with open(AUDIT_FILE) as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if line:
                    return json.loads(line).get("hash", "genesis")
        except Exception:
            pass
        return "genesis"

    def get_recent(self, n: int = 20) -> list:
        if not AUDIT_FILE.exists():
            return []
        entries = []
        with open(AUDIT_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        return entries[-n:]


audit_log = ImmutableAuditLog()
