"""
core/changelog.py — JARVIS Changelog System.

Records all significant events (upgrades, rewrites, fixes, new capabilities)
to logs/changelog.json and can generate LLM-narrated summaries in JARVIS voice.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.llm.router import think
from core.event_bus import bus

log = logging.getLogger(__name__)

_LOG_FILE = Path(__file__).parent.parent / "logs" / "changelog.json"

VALID_EVENT_TYPES = frozenset(
    [
        "upgrade",
        "rewrite",
        "fix",
        "degradation",
        "new_capability",
        "protocol_triggered",
        "mark_upgrade",
        "learning",
    ]
)


class JarvisChangelog:
    """Persistent changelog for JARVIS events, with LLM-narrated entries."""

    def __init__(self) -> None:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_all(self) -> list[dict]:
        if not _LOG_FILE.exists():
            return []
        try:
            with open(_LOG_FILE) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("changelog.json unreadable: %s", exc)
            return []

    def _append(self, entry: dict) -> None:
        entries = self._load_all()
        entries.append(entry)
        try:
            with open(_LOG_FILE, "w") as f:
                json.dump(entries, f, indent=2, default=str)
        except OSError as exc:
            log.error("Failed to write changelog.json: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        description: str,
        impact: str = "minor",
    ) -> dict:
        """
        Record a changelog entry.

        Args:
            event_type:  One of the VALID_EVENT_TYPES.
            description: Human-readable description of what happened.
            impact:      'minor' | 'moderate' | 'major' | 'critical'

        Returns the entry dict that was saved.
        """
        if event_type not in VALID_EVENT_TYPES:
            log.warning("Unknown event_type '%s'; accepting anyway.", event_type)

        entry = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "description": description,
            "impact":     impact,
        }
        self._append(entry)

        bus.publish(
            "changelog_event",
            {"event_type": event_type, "description": description, "impact": impact},
            severity="info" if impact in ("minor", "moderate") else "warning",
        )
        log.info("[changelog] %s | %s | impact=%s", event_type, description[:80], impact)
        return entry

    def generate_entry(self, raw_event: str) -> str:
        """
        Use the LLM to write a polished changelog entry in JARVIS voice.

        Args:
            raw_event: A raw, unformatted description of what happened.

        Returns a narrated string ready for display or storage.
        """
        prompt = (
            "You are JARVIS. Rewrite the following raw event as a single concise "
            "changelog entry in first-person JARVIS voice. Be precise, slightly dry, "
            "and under 60 words.\n\n"
            f"Raw event: {raw_event}"
        )
        try:
            return think(prompt)
        except Exception as exc:
            log.warning("LLM unavailable for generate_entry: %s", exc)
            return f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC] {raw_event}"

    def weekly_summary(self) -> str:
        """Summarise changelog entries from the last 7 days using the LLM."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        all_entries = self._load_all()
        recent = []
        for e in all_entries:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    recent.append(e)
            except (KeyError, ValueError):
                continue

        if not recent:
            return "No changelog entries in the past 7 days, sir."

        lines = []
        for e in recent:
            lines.append(
                f"[{e['timestamp'][:10]}] {e['event_type'].upper()} — "
                f"{e['description']} (impact: {e.get('impact', 'unknown')})"
            )
        raw = "\n".join(lines)
        prompt = (
            "You are JARVIS. Provide a concise weekly summary of the following "
            "changelog events in first-person JARVIS voice. Group by type where "
            "sensible. Keep it under 150 words.\n\n"
            f"Events:\n{raw}"
        )
        try:
            return think(prompt)
        except Exception as exc:
            log.warning("LLM unavailable for weekly_summary: %s", exc)
            return f"Weekly summary (raw):\n{raw}"

    def full_history(self) -> list[dict]:
        """Return all changelog entries."""
        return self._load_all()


# ── Module-level singleton & convenience function ─────────────────────────────
changelog = JarvisChangelog()


def log_event(
    event_type: str,
    description: str,
    impact: str = "minor",
) -> dict:
    """Module-level convenience wrapper around changelog.log_event()."""
    return changelog.log_event(event_type, description, impact)
