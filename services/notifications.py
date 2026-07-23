"""Notification service — Pushover, macOS, HUD event bus, email."""
from __future__ import annotations
import os, logging, urllib.request, urllib.parse, json
from enum import IntEnum

log = logging.getLogger(__name__)


class Priority(IntEnum):
    INFO     = 0
    WARNING  = 1
    HIGH     = 2
    CRITICAL = 3


def _pushover(title: str, message: str, priority: Priority):
    user  = os.getenv("PUSHOVER_USER_KEY", "")
    token = os.getenv("PUSHOVER_API_TOKEN", "")
    if not user or not token:
        # Previously a silent no-op — a HIGH/CRITICAL notification (e.g. a
        # Stark Protocol 2FA request) could vanish with zero trace anywhere
        # if these env vars were ever unset, which is exactly what happened
        # once during this session. Now at least visible in logs.
        log.warning("Pushover not configured (PUSHOVER_USER_KEY/PUSHOVER_API_TOKEN "
                    "missing) — skipped notification: %s", title)
        return
    prio_map = {Priority.INFO: -1, Priority.WARNING: 0, Priority.HIGH: 1, Priority.CRITICAL: 2}
    data = urllib.parse.urlencode({
        "token":    token,
        "user":     user,
        "title":    title,
        "message":  message,
        "priority": prio_map[priority],
        "retry":    30 if priority == Priority.CRITICAL else "",
        "expire":   300 if priority == Priority.CRITICAL else "",
    }).encode()
    try:
        req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
        urllib.request.urlopen(req, timeout=5)
        log.debug("Pushover sent: %s", title)
    except Exception as e:
        log.warning("Pushover failed: %s", e)


def _macos_notify(title: str, message: str):
    import subprocess
    script = f'display notification "{message}" with title "JARVIS" subtitle "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception as e:
        log.warning("macOS notify failed: %s", e)


def _hud_notify(title: str, message: str, priority: Priority):
    try:
        from core.event_bus import bus
        bus.publish("alert", {"title": title, "message": message, "priority": priority.name})
    except Exception:
        pass


def notify(title: str, message: str, priority: Priority = Priority.INFO, channels: list[str] | None = None):
    """Send a notification to all configured channels.

    channels: subset of ["pushover", "macos", "hud"] — defaults to all
    """
    if channels is None:
        channels = ["pushover", "macos", "hud"]

    log.info("[NOTIFY][%s] %s — %s", priority.name, title, message)

    if "hud" in channels:
        _hud_notify(title, message, priority)

    if priority >= Priority.WARNING and "macos" in channels:
        _macos_notify(title, message)

    if priority >= Priority.HIGH and "pushover" in channels:
        _pushover(title, message, priority)


# Convenience wrappers
def info(title: str, msg: str):     notify(title, msg, Priority.INFO)
def warning(title: str, msg: str):  notify(title, msg, Priority.WARNING)
def alert(title: str, msg: str):    notify(title, msg, Priority.HIGH)
def critical(title: str, msg: str): notify(title, msg, Priority.CRITICAL)


# ── Smart Notification Router ─────────────────────────────────────────────────

import time as _time
from datetime import datetime as _dt

_MODE_STATE = {"mode": "default", "until": 0.0}

_DND_RULES = {
    "sleep":   {"hours": set(range(23, 24)) | set(range(0, 7)), "allow": {"critical"}},
    "focus":   {"hours": None, "allow": {"critical", "high"}},
    "default": {"hours": None, "allow": {"info", "warning", "high", "critical"}},
}

# Flatten sleep hours
_SLEEP_HOURS = set(range(23, 24)) | set(range(0, 7))


class SmartRouter:
    @staticmethod
    def set_mode(mode: str, duration_minutes: int | None = None):
        _MODE_STATE["mode"] = mode
        if duration_minutes:
            _MODE_STATE["until"] = _time.time() + duration_minutes * 60
        else:
            _MODE_STATE["until"] = 0.0
        log.info("Notification mode: %s (duration=%s min)", mode, duration_minutes)

    @staticmethod
    def get_mode() -> str:
        if _MODE_STATE["until"] and _time.time() > _MODE_STATE["until"]:
            _MODE_STATE["mode"] = "default"
            _MODE_STATE["until"] = 0.0
        return _MODE_STATE["mode"]

    @staticmethod
    def should_notify(priority: str) -> bool:
        mode = SmartRouter.get_mode()
        hour = _dt.now().hour

        # Auto-sleep during sleep hours
        if mode == "default" and hour in _SLEEP_HOURS:
            return priority == "critical"

        allowed = _DND_RULES.get(mode, _DND_RULES["default"])["allow"]
        return priority.lower() in allowed

    @staticmethod
    def route(message: str, priority: str = "info", title: str = "JARVIS",
              channels: list | None = None):
        if not SmartRouter.should_notify(priority):
            log.debug("Notification suppressed by mode '%s': %s", SmartRouter.get_mode(), message)
            return

        try:
            from services.location import location_affects_notifications
            if not location_affects_notifications(priority):
                return
        except Exception:
            pass

        prio_map = {"info": Priority.INFO, "warning": Priority.WARNING,
                    "high": Priority.HIGH, "critical": Priority.CRITICAL}
        p = prio_map.get(priority.lower(), Priority.INFO)
        notify(title, message, p, channels)


smart_router = SmartRouter()


# ── Digest queue ───────────────────────────────────────────────────────────
# For signal that's real but not acute — multi-day health trends, and
# anything else non-urgent added later — firing bus.alert() the moment
# each one's detected trains you to ignore notifications, which is exactly
# the fatigue problem from this week's incident review. queue_digest()
# holds items in memory; flush_digest() (called once/day by the scheduler,
# services/scheduler.py's notification_digest_flush job) sends everything
# queued as one batched notification and clears the queue. In-memory only,
# same as behavioral_security's anomaly log — a restart between queue and
# flush drops pending items, which is an acceptable trade for a personal
# assistant (nothing here is safety-critical enough to need durability).
_digest_queue: list[dict] = []


def queue_digest(category: str, message: str):
    _digest_queue.append({"category": category, "message": message, "ts": _dt.now().isoformat()})
    log.info("Queued digest notification [%s]: %s", category, message)


def flush_digest(title: str = "JARVIS Daily Digest"):
    """Send everything queued via queue_digest() as one notification, then
    clear the queue. No-op if empty — no 'nothing happened' pings.
    Routed through SmartRouter at 'high' priority (reaches Pushover) since
    a digest is already batched to once/day; there's no fatigue risk left
    to guard against by also demoting it to a channel-limited priority."""
    global _digest_queue
    if not _digest_queue:
        return
    lines = [f"- [{item['category']}] {item['message']}" for item in _digest_queue]
    body = "\n".join(lines)
    count = len(_digest_queue)
    _digest_queue = []
    SmartRouter.route(body, priority="high", title=f"{title} ({count} item{'s' if count != 1 else ''})")
