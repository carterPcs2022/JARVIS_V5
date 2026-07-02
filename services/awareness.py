"""
services/awareness.py — JARVIS Situational Awareness Loop.

Monitors system resources, calendar events, and goals in a background thread.
Generates JARVIS-style narrations for anomalies and upcoming events.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
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

_MEMORY_DIR       = Path(__file__).parent.parent / "memory"
_CALENDAR_FILE    = _MEMORY_DIR / "calendar_cache.json"
_GOALS_FILE       = _MEMORY_DIR / "goals.json"
_SETTINGS_FILE    = _MEMORY_DIR / "awareness_settings.json"

# Track CPU history for >2-minute spike detection
_cpu_high_since: float | None = None


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as exc:
        log.error("Failed to save %s: %s", path, exc)


class SituationalAwareness:
    """Background awareness loop that monitors system, calendar, and goals."""

    def __init__(self) -> None:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._pending_narrations: list[str] = []
        self._lock = threading.Lock()
        self._running = False
        self._cpu_high_since: float | None = None

    # ── Narration ─────────────────────────────────────────────────────────────

    def narrate(self, event_type: str, data: dict) -> str:
        """
        Generate a JARVIS-style narration for an event.
        Format: "Sir, [observation]. [context]. [recommendation if any]."
        Falls back to a templated string if LLM is unavailable.
        """
        context_str = json.dumps(data, default=str)
        prompt = (
            f"You are JARVIS. Generate a brief situational narration for the following event. "
            f"Format: 'Sir, [observation]. [context]. [recommendation if applicable].' "
            f"Keep it under 60 words. Be precise and in character.\n\n"
            f"Event type: {event_type}\nData: {context_str}"
        )
        try:
            narration = think(prompt, use_cache=True)
        except Exception as exc:
            log.warning("LLM unavailable for narration: %s", exc)
            narration = self._fallback_narration(event_type, data)

        with self._lock:
            self._pending_narrations.append(narration)

        bus.publish("awareness_narration", {"event_type": event_type, "narration": narration}, severity="info")
        log.info("[awareness] %s: %s", event_type, narration[:100])
        return narration

    def _fallback_narration(self, event_type: str, data: dict) -> str:
        """Rotates between multiple phrasings per event type so JARVIS doesn't
        sound repetitive when the LLM is unavailable and this fallback carries
        the narration load."""
        import random

        templates: dict[str, list[str]] = {
            "high_cpu": [
                "CPU has been above {cpu_pct}% for a couple of minutes now. "
                "Worth identifying what's driving it.",
                "Something is working your processor hard — {cpu_pct}% and climbing. "
                "I'd recommend a look.",
            ],
            "high_ram": [
                "Memory pressure is critical — {ram_pct}% utilization. "
                "Closing a few applications would help.",
                "RAM is at {ram_pct}%. Might be worth freeing some up before it slows things down.",
            ],
            "high_disk": [
                "Disk usage has reached {disk_pct}%. You'll want to address that "
                "before it becomes a problem.",
                "{disk_pct}% disk usage. I can find the largest files if that would help.",
            ],
            "calendar_event": [
                "You have '{title}' in {minutes_away} minutes.",
                "'{title}' starts in {minutes_away} minutes.",
            ],
            "goal_deadline": [
                "The deadline for '{goal}' is approaching: {deadline}.",
                "Worth noting — '{goal}' is due {deadline}.",
            ],
            "new_device": [
                "Unknown device joined your network — IP {ip}, manufacturer reads as {vendor}. "
                "Shall I investigate?",
                "There's a new face on the network. {ip} — {vendor} hardware. Not in my records.",
            ],
            "no_interaction": [
                "You've been quiet for {hours} hours. Everything alright?",
            ],
            "goal_stalled": [
                "The {goal} goal hasn't moved in {days} days.",
                "Worth noting — {goal} has been stalled for {days} days now.",
            ],
            "groq_restored": [
                "Primary systems back online.",
            ],
            "groq_down": [
                "Groq is unreachable. Switching to local systems. Some capabilities will be limited.",
            ],
        }

        options = templates.get(event_type)
        if not options:
            return f"Sir, awareness event: {event_type}. Data: {data}"

        template = random.choice(options)
        try:
            return "Sir, " + template.format(**data)
        except KeyError:
            # Data didn't have every placeholder this variant needed — fall
            # back to the first template, which is the most conservative.
            try:
                return "Sir, " + options[0].format(**data)
            except KeyError:
                return f"Sir, awareness event: {event_type}. Data: {data}"

    # ── Awareness loop ────────────────────────────────────────────────────────

    def start_awareness_loop(self) -> threading.Thread:
        """Start the background awareness loop. Returns the thread."""
        if self._running:
            log.info("Awareness loop already running.")
            return threading.current_thread()  # type: ignore

        def _loop():
            self._running = True
            log.info("Situational awareness loop started.")
            while self._running:
                try:
                    self._check_all()
                except Exception as exc:
                    log.error("Awareness loop error: %s", exc)
                time.sleep(60)

        t = threading.Thread(target=_loop, daemon=True, name="awareness-loop")
        t.start()
        return t

    def stop_awareness_loop(self) -> None:
        self._running = False

    def _check_all(self) -> None:
        self.check_system()
        self.check_time()
        self.check_goals()

    # ── System checks ─────────────────────────────────────────────────────────

    def check_system(self) -> dict:
        """
        Check CPU, RAM, disk using psutil.
        Alerts if CPU > 85% for > 2 minutes, RAM > 90%, or disk > 90%.
        Returns current metrics dict.
        """
        if not psutil:
            return {"error": "psutil not installed"}

        try:
            cpu  = psutil.cpu_percent(interval=1)
            ram  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
        except Exception as exc:
            log.warning("psutil error in check_system: %s", exc)
            return {"error": str(exc)}

        metrics = {
            "cpu_pct":  cpu,
            "ram_pct":  ram.percent,
            "disk_pct": disk.percent,
        }

        # CPU sustained high
        if cpu > 85:
            if self._cpu_high_since is None:
                self._cpu_high_since = time.time()
            elif time.time() - self._cpu_high_since > 120:
                self.narrate("high_cpu", {"cpu_pct": round(cpu, 1)})
                notify("CPU Warning", f"CPU at {cpu:.0f}% for >2 min", Priority.WARNING)
                self._cpu_high_since = None  # reset to avoid spam
        else:
            self._cpu_high_since = None

        # RAM critical
        if ram.percent > 90:
            self.narrate("high_ram", {"ram_pct": round(ram.percent, 1)})
            notify("RAM Critical", f"Memory at {ram.percent:.0f}%", Priority.HIGH)

        # Disk critical
        if disk.percent > 90:
            self.narrate("high_disk", {"disk_pct": round(disk.percent, 1)})
            notify("Disk Critical", f"Disk at {disk.percent:.0f}%", Priority.HIGH)

        return metrics

    # ── Calendar checks ───────────────────────────────────────────────────────

    def check_time(self) -> list[dict]:
        """
        Check for calendar events in the next 30 minutes.
        Reads memory/calendar_cache.json if it exists.
        Returns list of upcoming events found.
        """
        events = _load_json(_CALENDAR_FILE, default=[])
        if not isinstance(events, list):
            events = []

        now = datetime.now(timezone.utc)
        upcoming = []

        for event in events:
            try:
                start_str = event.get("start") or event.get("start_time") or ""
                if not start_str:
                    continue
                start = datetime.fromisoformat(start_str)
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                delta = (start - now).total_seconds()
                if 0 < delta <= 1800:  # within 30 minutes
                    minutes_away = int(delta // 60)
                    title = event.get("title") or event.get("summary") or "Event"
                    narration_data = {
                        "title": title,
                        "minutes_away": minutes_away,
                        "location": event.get("location", ""),
                    }
                    self.narrate("calendar_event", narration_data)
                    notify(
                        f"Upcoming: {title}",
                        f"Starts in {minutes_away} min",
                        Priority.INFO,
                    )
                    upcoming.append(narration_data)
            except (ValueError, KeyError) as exc:
                log.debug("Skipping malformed calendar event: %s", exc)

        return upcoming

    # ── Goal checks ───────────────────────────────────────────────────────────

    def check_goals(self) -> list[dict]:
        """
        Read memory/goals.json and alert on approaching deadlines (within 48h).
        Returns list of goal alerts.
        """
        goals_data = _load_json(_GOALS_FILE, default=[])
        if isinstance(goals_data, dict):
            goals = goals_data.get("goals", [])
        elif isinstance(goals_data, list):
            goals = goals_data
        else:
            return []

        now = datetime.now(timezone.utc)
        alerts = []

        for goal in goals:
            deadline_str = goal.get("deadline") or goal.get("due") or ""
            if not deadline_str:
                continue
            try:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                delta = (deadline - now).total_seconds()
                if 0 < delta <= 172800:  # within 48 hours
                    hours_away = int(delta // 3600)
                    goal_name = goal.get("title") or goal.get("name") or "Goal"
                    data = {
                        "goal":     goal_name,
                        "deadline": deadline.strftime("%Y-%m-%d %H:%M UTC"),
                        "hours":    hours_away,
                    }
                    self.narrate("goal_deadline", data)
                    notify(
                        f"Goal deadline: {goal_name}",
                        f"Due in {hours_away}h",
                        Priority.WARNING,
                    )
                    alerts.append(data)
            except (ValueError, KeyError) as exc:
                log.debug("Skipping malformed goal: %s", exc)

        return alerts

    # ── Settings ──────────────────────────────────────────────────────────────

    def set_awareness_level(self, level: str) -> None:
        """Set awareness level. Accepts 'low', 'medium', or 'high'."""
        level = level.lower()
        if level not in ("low", "medium", "high"):
            raise ValueError(f"Invalid awareness level '{level}'. Must be low/medium/high.")
        settings = _load_json(_SETTINGS_FILE, default={})
        settings["level"] = level
        _save_json(_SETTINGS_FILE, settings)
        bus.publish("awareness_level_changed", {"level": level}, severity="info")
        log.info("Awareness level set to: %s", level)

    def get_awareness_level(self) -> str:
        """Return current awareness level (default: 'medium')."""
        settings = _load_json(_SETTINGS_FILE, default={})
        return settings.get("level", "medium")

    # ── Narration queue ───────────────────────────────────────────────────────

    def get_pending_narrations(self) -> list[str]:
        """Return and clear the list of pending narrations."""
        with self._lock:
            pending = list(self._pending_narrations)
            self._pending_narrations.clear()
        return pending


# ── Module-level singleton & shorthand ───────────────────────────────────────
awareness = SituationalAwareness()
start_awareness_loop = awareness.start_awareness_loop
