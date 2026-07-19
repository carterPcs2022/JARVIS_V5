"""services/audit_log.py — Immutable, cryptographically chained audit log.

Distinct from core/protocols.py's _log_protocol_event (a plain append-only
JSON list already used for per-protocol events): this hash-chains every
entry to the previous one, so altering or deleting any past entry breaks
the chain from that point forward — mathematically detectable, the same
technique used for tamper-evident logs in finance/nuclear-facility systems.
Use this for the subset of actions where "did anyone tamper with this
history" actually matters (chat responses, protocol triggers, security
events); it isn't a replacement for the higher-volume protocol log.

Two fixes applied here after a real historical chain break was found and
investigated:

1. Turso-backed (same convention as core/memory.py) so the log survives
   Render's ephemeral disk across redeploys. Previously a raw local file
   only — every redeploy reset it to empty, so "tamper-evident history"
   only actually held within a single deploy's uptime. The local JSONL
   file is still written unconditionally (same convention as
   core/memory.py's _save()) as a working cache/fallback, not just for
   compatibility.

2. record() used to read the last hash once at __init__ and cache it in
   memory with no lock — two ImmutableAuditLog instances (e.g. two
   threads calling record() close together) could each read the same
   starting hash and then append independently, forking the chain. This
   is exactly what happened to real historical entries from 2026-07-07,
   discovered while investigating a reported chain-verification failure —
   left as a documented historical anomaly rather than rewritten, since
   altering past entries would defeat the whole point of a tamper-evident
   log. record() now holds a lock across the entire read-last-hash +
   append sequence, closing the race for concurrent threads within one
   process (this matches the actual deployment model — Render runs
   WEB_CONCURRENCY=1 — a true multi-process race would need a
   database-level transaction, which is a bigger change than this
   deployment currently needs).
"""
import hashlib
import json
import threading
import time
from datetime import datetime

from config.settings import BASE_DIR

AUDIT_FILE = BASE_DIR / "logs" / "immutable_audit.jsonl"
_TURSO_KEY = "logs/immutable_audit.jsonl"


def _load_entries() -> list[dict]:
    """Turso first (durable across redeploys), local JSONL file as
    fallback — same precedence as core/memory.py's _load()."""
    from core.turso_store import get as turso_get
    remote = turso_get(_TURSO_KEY)
    if remote is not None:
        return remote

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
    return entries


def _save_entries(entries: list[dict]):
    """Local file unconditionally (a Turso outage must not lose the
    write, only stop it from surviving the next redeploy), Turso as a
    best-effort mirror — same convention as core/memory.py's _save()."""
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    from core.turso_store import put as turso_put
    turso_put(_TURSO_KEY, entries)


class ImmutableAuditLog:

    def __init__(self):
        self._lock = threading.Lock()

    def record(self, action: str, actor: str = "jarvis",
               details: dict | None = None, result: str = "success") -> str:
        """Record an action permanently. Each entry is chained to the
        previous one via prev_hash — altering any entry breaks the chain
        for every entry after it. The whole read-last-hash-then-append
        sequence is under one lock so two concurrent callers can't each
        read the same starting hash and fork the chain."""
        details = details or {}
        with self._lock:
            entries = _load_entries()
            last_hash = entries[-1]["hash"] if entries else "genesis"

            ts = time.time()
            entry = {
                "ts": ts,
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "action": action,
                "actor": actor,
                "details": details,
                "result": result,
                "prev_hash": last_hash,
            }

            entry_json = json.dumps(entry, sort_keys=True)
            entry_hash = hashlib.sha256(entry_json.encode()).hexdigest()
            entry["hash"] = entry_hash

            entries.append(entry)
            _save_entries(entries)

        return entry_hash

    def verify_chain(self) -> dict:
        """Verify the entire audit log chain. Any tampering breaks it."""
        entries = [dict(e) for e in _load_entries()]  # copy — pop() below must not mutate the stored entries
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

    def get_recent(self, n: int = 20) -> list:
        return _load_entries()[-n:]


audit_log = ImmutableAuditLog()
