"""
services/mark_system.py — JARVIS Mark System (Iron Man-style suit versioning).

Tracks the current Mark (version) of JARVIS, upgrade history, capabilities,
and performs live damage-report diagnostics using psutil + import probing.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

from core.llm.router import think
from core.event_bus import bus
from services.notifications import notify, Priority

log = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).parent.parent / "memory" / "mark_system.json"

# Modules that are part of the JARVIS V5 suit
_SUIT_MODULES: dict[str, str] = {
    "repulsor_left":        "core.llm.router",
    "repulsor_right":       "core.llm.openai",
    "arc_reactor":          "core.event_bus",
    "friday_protocol":      "core.friday_fallback",
    "neural_core":          "core.brain_v2",
    "memory_banks":         "core.memory",
    "tactical_display":     "core.context",
    "voice_module":         "services.voice",
    "vision_system":        "services.vision",
    "sentinel_shield":      "services.sentinel",
    "notification_array":   "services.notifications",
    "automation_bay":       "services.automation",
    "backup_systems":       "services.backup",
    "scheduler_unit":       "services.scheduler",
    "document_processor":   "services.documents",
    "evolution_engine":     "core.evolution",
    "protocol_manager":     "core.protocols",
    "reasoning_core":       "core.reasoning",
    "planner_unit":         "core.planner",
    "executor_array":       "core.executor",
}

_MARK_CODENAMES: dict[int, str] = {
    1:  "GENESIS",
    2:  "SENTINEL",
    3:  "ORACLE",
    4:  "PHANTOM",
    5:  "INVICTUS",
    6:  "NEXUS",
    7:  "ASCENDANT",
    8:  "SOVEREIGN",
    9:  "OMEGA",
    10: "TRANSCENDENT",
}

_DEFAULT_CAPABILITIES = [
    "Multi-LLM routing (Groq + Ollama)",
    "Long-term memory & context sharding",
    "Real-time event bus",
    "Voice synthesis & recognition",
    "Mac OS automation",
    "Autonomous task planning",
    "Evolution & self-improvement",
    "Sentinel threat monitoring",
    "Multi-agent scatter/gather",
    "Situational awareness loop",
]


def count_capabilities(app) -> int:
    """Real endpoint count, not the ~10-item static _DEFAULT_CAPABILITIES
    list — JARVIS V5 has hundreds of registered /stark/ routes across all
    the feature batches built this project; the static list badly
    undercounted actual capability. Pass in the live FastAPI app (from
    server/api.py) — kept out of MarkSystem itself to avoid a circular
    import between services.mark_system and server.api.

    Recurses into sub-routers: this FastAPI version wraps every
    app.include_router() call as an opaque _IncludedRouter with no direct
    .path, so a flat scan of app.routes only sees the handful of routes
    declared directly on `app` (e.g. /hud/*) and badly undercounts —
    verified live: a flat scan found 13, the real total (via
    app.openapi()) is 364+. Walking .routes recursively finds the actual
    leaf routes wherever they're nested."""
    seen_paths = set()

    def _walk(routes):
        for route in routes:
            path = getattr(route, "path", None)
            if path and path.startswith("/stark/"):
                seen_paths.add(path)
            # This FastAPI version's _IncludedRouter exposes the actual
            # APIRouter as .original_router (not .routes directly) —
            # verified live, since a naive getattr(route, "routes", None)
            # silently found nothing and undercounted just like the flat
            # scan this function replaced.
            nested = getattr(route, "original_router", None) or route
            sub_routes = getattr(nested, "routes", None)
            if sub_routes and sub_routes is not routes:
                _walk(sub_routes)

    try:
        _walk(app.routes)
    except Exception:
        pass

    # Fallback (and cross-check) if the route-tree walk above ever badly
    # undercounts again on some future FastAPI internals change —
    # app.openapi() is the public, stable API for "what's actually
    # registered," just more expensive to call than a route-tree walk.
    if len(seen_paths) < 20:
        try:
            seen_paths = {p for p in app.openapi().get("paths", {}) if p.startswith("/stark/")}
        except Exception:
            pass

    return len(seen_paths)


def _to_roman(n: int) -> str:
    """Convert integer to Roman numeral string."""
    if n < 1:
        return "N"
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syms = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    result = ""
    for i, v in enumerate(val):
        while n >= v:
            result += syms[i]
            n -= v
    return result


class MarkSystem:
    """Iron Man-style versioning and diagnostic system for JARVIS."""

    def __init__(self) -> None:
        _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._start_time = time.time()
        self._data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if _MEMORY_FILE.exists():
            try:
                with open(_MEMORY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("mark_system.json corrupted, reinitialising: %s", exc)
        return self._default_data()

    def _save(self) -> None:
        try:
            with open(_MEMORY_FILE, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
        except OSError as exc:
            log.error("Failed to save mark_system.json: %s", exc)

    def _default_data(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "current_mark": 5,
            "total_interactions": 0,
            "modules_loaded": len(_SUIT_MODULES),
            "rewrites": 0,
            "history": [
                {
                    "mark": 5,
                    "roman": "V",
                    "codename": _MARK_CODENAMES.get(5, "UNKNOWN"),
                    "capabilities": _DEFAULT_CAPABILITIES,
                    "activated": now,
                    "notes": "Initial deployment of JARVIS V5.",
                }
            ],
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def current_mark(self, real_capability_count: int | None = None) -> dict:
        """Return a status snapshot of the current Mark. Pass
        real_capability_count (from count_capabilities(app), computed by
        the caller in server/api.py) to report the actual live endpoint
        count instead of just the length of the illustrative
        _DEFAULT_CAPABILITIES list."""
        m = self._data["current_mark"]
        history = self._data.get("history", [])
        latest = history[-1] if history else {}
        uptime_hours = round((time.time() - self._start_time) / 3600, 2)
        capabilities = latest.get("capabilities", _DEFAULT_CAPABILITIES)
        return {
            "mark":               _to_roman(m),
            "version":            m,
            "codename":           _MARK_CODENAMES.get(m, "CLASSIFIED"),
            "capabilities":       capabilities,
            "capability_count":   real_capability_count if real_capability_count is not None else len(capabilities),
            "activated":          latest.get("activated", datetime.now(timezone.utc).isoformat()),
            "total_interactions": self._data.get("total_interactions", 0),
            "modules_loaded":     self._data.get("modules_loaded", len(_SUIT_MODULES)),
            "rewrites":           self._data.get("rewrites", 0),
            "uptime_hours":       uptime_hours,
        }

    def upgrade_mark(self, new_capabilities: list[str], notes: str = "") -> dict:
        """Increment the Mark integer, record history, and notify."""
        old_mark = self._data["current_mark"]
        new_mark = old_mark + 1
        self._data["current_mark"] = new_mark
        self._data["rewrites"] = self._data.get("rewrites", 0) + 1

        entry = {
            "mark":         new_mark,
            "roman":        _to_roman(new_mark),
            "codename":     _MARK_CODENAMES.get(new_mark, f"MARK_{new_mark}"),
            "capabilities": new_capabilities,
            "activated":    datetime.now(timezone.utc).isoformat(),
            "notes":        notes,
        }
        self._data.setdefault("history", []).append(entry)
        self._save()

        bus.publish(
            "mark_upgrade",
            {"old": old_mark, "new": new_mark, "codename": entry["codename"]},
            severity="info",
        )
        notify(
            f"JARVIS Mark {_to_roman(new_mark)} Online",
            f"{entry['codename']} — {notes or 'Upgrade complete.'}",
            Priority.HIGH,
        )
        log.info("Upgraded from Mark %s to Mark %s (%s)", old_mark, new_mark, entry["codename"])
        return entry

    def mark_history(self) -> list[dict]:
        """Return the full Mark upgrade history."""
        return self._data.get("history", [])

    def mark_changelog(self) -> str:
        """Generate a changelog in JARVIS voice using the LLM."""
        history = self.mark_history()
        if not history:
            return "No upgrade history on record, sir."
        summary_lines = []
        for h in history:
            caps = ", ".join(h.get("capabilities", [])[:4])
            summary_lines.append(
                f"Mark {h['roman']} ({h['codename']}), activated {h['activated'][:10]}: {caps}."
            )
        summary = "\n".join(summary_lines)
        prompt = (
            "You are JARVIS, Tony Stark's AI. Write a concise, witty changelog "
            "for the following Mark upgrades in first-person JARVIS voice. "
            "Be informative but keep it under 200 words.\n\n"
            f"Upgrade history:\n{summary}"
        )
        try:
            return think(prompt)
        except Exception as exc:
            log.warning("LLM unavailable for mark_changelog: %s", exc)
            return f"Changelog unavailable at this time, sir. History:\n{summary}"

    def damage_report(self) -> dict[str, str]:
        """
        Check system health (CPU/RAM via psutil) and probe each suit module
        by attempting to import it. Returns a dict of component → status.
        """
        report: dict[str, str] = {}

        # System metrics
        if psutil:
            try:
                cpu = psutil.cpu_percent(interval=0.5)
                ram = psutil.virtual_memory()
                disk = psutil.disk_usage("/")

                report["arc_reactor_output"] = (
                    f"{100 - cpu:.0f}%" if cpu < 85 else f"STRAINED ({cpu:.0f}% CPU)"
                )
                report["neural_memory_banks"] = (
                    f"{ram.percent:.0f}% utilised"
                    if ram.percent < 90
                    else f"CRITICAL ({ram.percent:.0f}% RAM)"
                )
                report["storage_integrity"] = (
                    "nominal"
                    if disk.percent < 85
                    else f"LOW ({disk.percent:.0f}% used)"
                )
                report["structural_integrity"] = (
                    "nominal" if cpu < 85 and ram.percent < 90 else "degraded"
                )
            except Exception as exc:
                log.warning("psutil error in damage_report: %s", exc)
                report["system_metrics"] = f"unavailable ({exc})"
        else:
            report["system_metrics"] = "psutil not installed"

        # Module import probes
        for component, module_path in _SUIT_MODULES.items():
            try:
                __import__(module_path)
                report[component] = "online"
            except ImportError as exc:
                report[component] = f"OFFLINE ({exc})"
            except Exception as exc:
                report[component] = f"ERROR ({type(exc).__name__})"

        return report

    # ── Interaction counter (called by brain/router) ──────────────────────────

    def increment_interactions(self) -> None:
        self._data["total_interactions"] = self._data.get("total_interactions", 0) + 1
        # Auto-save every 25 interactions to avoid hammering disk
        if self._data["total_interactions"] % 25 == 0:
            self._save()


# ── Module-level singleton ────────────────────────────────────────────────────
mark_system = MarkSystem()
