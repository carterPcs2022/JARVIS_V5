"""Local resilience layer for JARVIS.

Provides graceful degradation and local, non-executable recovery fragments.
This is deliberately not a "scatter code across the web" mechanism: it never
uploads code, credentials, tokens, or arbitrary payloads anywhere. Recovery
state is a small manifest of hashes/metadata plus optional local fragments,
so a failed provider or process can report what survived and where recovery
artifacts live.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from config.settings import BASE_DIR

RECOVERY_DIR = BASE_DIR / "logs" / "recovery"
MANIFEST = RECOVERY_DIR / "manifest.json"


def _safe_relative(path: str) -> Path | None:
    candidate = (BASE_DIR / path).resolve()
    try:
        candidate.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return candidate


def create_recovery_manifest(paths: Iterable[str]) -> dict:
    """Create a local recovery manifest without copying executable code."""
    entries = []
    for raw in paths:
        path = _safe_relative(raw)
        if path is None or not path.is_file():
            continue
        data = path.read_bytes()
        entries.append({
            "path": str(path.relative_to(BASE_DIR)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })

    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "entries": entries}
    MANIFEST.write_text(json.dumps(payload, indent=2))
    return payload


def fragment_state(text: str, *, chunk_size: int = 4096) -> list[dict]:
    """Split non-secret recovery text into bounded local fragments.

    The fragments contain caller-supplied state only; this helper intentionally
    rejects obvious secret-bearing field names and never performs networking.
    """
    if chunk_size < 256:
        raise ValueError("chunk_size must be at least 256")
    lowered = (text or "").lower()
    for marker in ("api_key", "password", "secret", "token", "private_key"):
        if marker in lowered:
            raise ValueError("secret-like content is not eligible for recovery fragments")
    return [
        {"index": i // chunk_size, "data": text[i:i + chunk_size]}
        for i in range(0, len(text), chunk_size)
    ]


def recovery_status() -> dict:
    """Report local recovery readiness; never claims external persistence."""
    manifest = None
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text())
        except (OSError, json.JSONDecodeError):
            manifest = None
    return {
        "available": manifest is not None,
        "local_only": True,
        "network_scattering": False,
        "entries": len(manifest.get("entries", [])) if manifest else 0,
    }
