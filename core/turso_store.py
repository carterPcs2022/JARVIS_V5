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

Talks to Turso's HTTP API directly (POST {url}/v2/pipeline) via `requests`
instead of the `libsql_client` package. That package's HTTP transport calls
the legacy v1/execute endpoint and reads response["result"] — once real
credentials were in place, every single call failed with KeyError('result'),
confirmed live: Turso's actual current API is v2/pipeline, and a successful
execute response is shaped {"results": [{"type": "ok", "response":
{"type": "execute", "result": {"cols": [...], "rows": [...]}}}]}, not a
top-level "result" key at all. v2/pipeline is Turso's documented, stable
HTTP interface (docs.turso.tech/sdk/http/reference) — talking to it
directly removes both that mismatch and the extra asyncio-executor-thread
machinery libsql_client's sync wrapper ran per client instance.

Every call is still wrapped so any transport/shape mismatch fails loudly
in logs and falls back to local JSON files rather than crashing anything."""
import json
import logging
from datetime import datetime, timezone

import requests

from config.settings import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

log = logging.getLogger(__name__)

_bootstrapped = False
_TIMEOUT_SECONDS = 10


def is_configured() -> bool:
    return bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)


def _pipeline_url() -> str:
    # Same libsql:// -> https:// normalization as before — Turso's
    # WebSocket (Hrana) scheme, not needed for the plain HTTP pipeline API.
    url = TURSO_DATABASE_URL.replace("libsql://", "https://", 1)
    return url.rstrip("/") + "/v2/pipeline"


def _arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _execute(sql: str, args: list) -> dict:
    """POST one statement (+ an implicit connection close) to Turso's
    v2/pipeline endpoint. Returns the execute step's "result" dict
    ({"cols": [...], "rows": [...]}). Raises on any HTTP/transport error
    or a non-"ok" pipeline result — every caller here catches broadly."""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}},
            {"type": "close"},
        ]
    }
    resp = requests.post(
        _pipeline_url(),
        json=payload,
        headers={"Authorization": f"Bearer {TURSO_AUTH_TOKEN}"},
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    body = resp.json()
    first = body["results"][0]
    if first.get("type") != "ok":
        raise RuntimeError(f"Turso pipeline error: {first}")
    return first["response"]["result"]


def _ensure_bootstrapped():
    global _bootstrapped
    if not _bootstrapped:
        _execute(
            "CREATE TABLE IF NOT EXISTS memory_files ("
            "path TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)",
            [],
        )
        _bootstrapped = True


def get(key: str):
    """Parsed JSON value stored at `key`, or None if not configured, not
    found, or the read failed for any reason — callers fall back to the
    local file in every one of those cases."""
    if not is_configured():
        return None
    try:
        _ensure_bootstrapped()
        result = _execute("SELECT data FROM memory_files WHERE path = ?", [key])
        rows = result.get("rows") or []
        if not rows:
            return None
        return json.loads(rows[0][0]["value"])
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
        _ensure_bootstrapped()
        _execute(
            "INSERT INTO memory_files (path, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            [key, json.dumps(value), datetime.now(timezone.utc).isoformat()],
        )
        return True
    except Exception as e:
        log.error("Turso write failed for %s, falling back to local file only: %s", key, e)
        return False
