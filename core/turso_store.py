"""
core/turso_store.py — key -> JSON-blob persistence for core/memory.py's
_load()/_save(), backed by Turso (hosted libSQL) instead of the local
filesystem. Render's disk is ephemeral (wiped on every redeploy) — this
survives that, unlike a plain JSON file under memory/.

Deliberately a *separate* Turso database from FRIDAY's, not the same one —
sharing a database couples two independently-deployed, independently-
evolving codebases through mutable shared state, and FRIDAY's schema isn't
visible from here. Provisioning a second Turso DB under the same account is
a one-command operation; a write conflict or a silent schema change on
FRIDAY's side breaking JARVIS isn't worth risking to save that one command.

Every JSON "file" core/memory.py used to read/write becomes one row, keyed
by the file's relative path string (e.g. "memory/short_term.json") — this
preserves _load()/_save()'s exact (path -> list|dict) contract, so none of
core/memory.py's other ~15 functions needed to change.

Not independently verified against live Turso/libsql_client docs (no
network access to check the exact client API from here) — every call is
wrapped so a mismatch fails loudly in logs and falls back to local JSON
files rather than crashing anything. Smoke-test once real credentials are
in place; the error message will say exactly what's wrong if the client
API differs from what's written here."""
import json
import logging
from datetime import datetime, timezone

from config.settings import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

log = logging.getLogger(__name__)

_client = None
_bootstrapped = False


def is_configured() -> bool:
    return bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)


def _get_client():
    global _client, _bootstrapped
    if _client is None:
        import libsql_client
        # A libsql:// URL tells the client to use its WebSocket (Hrana)
        # transport — Turso's server rejected that handshake outright (400
        # on the upgrade, "Invalid response status") the one time this got
        # smoke-tested, so force plain HTTPS instead. That's also the
        # better fit here regardless: this store does occasional
        # independent reads/writes, not a rapid sequence of queries that
        # would benefit from a persistent streaming connection.
        url = TURSO_DATABASE_URL.replace("libsql://", "https://", 1)
        _client = libsql_client.create_client_sync(
            url=url, auth_token=TURSO_AUTH_TOKEN,
        )
    if not _bootstrapped:
        _client.execute(
            "CREATE TABLE IF NOT EXISTS memory_files ("
            "path TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        _bootstrapped = True
    return _client


def get(key: str):
    """Parsed JSON value stored at `key`, or None if not configured, not
    found, or the read failed for any reason — callers fall back to the
    local file in every one of those cases."""
    if not is_configured():
        return None
    try:
        client = _get_client()
        rs = client.execute("SELECT data FROM memory_files WHERE path = ?", [key])
        if not rs.rows:
            return None
        return json.loads(rs.rows[0][0])
    except Exception as e:
        log.error("Turso read failed for %s, falling back to local file: %s", key, e)
        return None


def put(key: str, value) -> bool:
    """True on success, False if not configured or the write failed —
    callers write the local file either way, so a transient Turso outage
    never loses data, it just stops persisting across redeploys until
    Turso is reachable again."""
    if not is_configured():
        return False
    try:
        client = _get_client()
        client.execute(
            "INSERT INTO memory_files (path, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            [key, json.dumps(value), datetime.now(timezone.utc).isoformat()],
        )
        return True
    except Exception as e:
        log.error("Turso write failed for %s, falling back to local file only: %s", key, e)
        return False
