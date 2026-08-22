"""
services/playbook.py — JARVIS Threat Playbook Engine.

Defines, loads, and executes response playbooks for security threats
and system anomalies. Each playbook is a trigger → list of action strings.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.event_bus import bus
from services.notifications import notify, Priority

log = logging.getLogger(__name__)

_MEMORY_DIR   = Path(__file__).parent.parent / "memory"
_LOGS_DIR     = Path(__file__).parent.parent / "logs"
_PLAYBOOK_FILE  = _MEMORY_DIR / "playbooks.json"
_HISTORY_FILE   = _LOGS_DIR  / "playbook_history.json"
_INCIDENT_FILE  = _LOGS_DIR  / "incidents.json"
_BLOCKED_IP_FILE = _MEMORY_DIR / "blocked_ips.json"

# ── Default playbooks ─────────────────────────────────────────────────────────

DEFAULT_PLAYBOOKS: dict[str, dict] = {
    "brute_force": {
        "actions": [
            "notify_critical:Brute force detected on {ip}",
            "log_incident",
            "block_ip:{ip}",
            "rotate_api_token",
        ],
        "conditions": {"threshold": 5},
    },
    "file_tampered": {
        "actions": [
            "notify_critical:File tampering detected: {file}",
            "log_incident",
            "backup_immediately",
            "integrity_check_all",
        ],
        "conditions": {},
    },
    "new_unknown_device": {
        "actions": [
            "notify_warning:Unknown device on network: {ip}",
            "log_incident",
        ],
        "conditions": {},
    },
    "disk_critical": {
        "actions": [
            "notify_high:Disk space critical",
            "find_large_files",
            "log_incident",
        ],
        "conditions": {"threshold_pct": 90},
    },
    "all_llms_down": {
        "actions": [
            "notify_critical:All LLMs offline",
            "activate_friday_protocol",
            "switch_to_ollama",
        ],
        "conditions": {},
    },
    "internet_down": {
        "actions": [
            "notify_high:Internet connectivity lost",
            "log_incident",
        ],
        "conditions": {},
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as exc:
        log.error("Failed to save %s: %s", path, exc)


def _append_json_list(path: Path, entry: dict) -> None:
    """Append an entry to a JSON file that stores a list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _load_json(path, default=[])
    if not isinstance(entries, list):
        entries = []
    entries.append(entry)
    _save_json(path, entries)


def _format_arg(arg: str, context: dict) -> str:
    """Substitute {key} placeholders from context into arg string."""
    try:
        return arg.format(**context)
    except KeyError:
        return arg


class ThreatPlaybook:
    """Loads, stores, and executes threat response playbooks."""

    def __init__(self) -> None:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── Playbook management ───────────────────────────────────────────────────

    def load_playbooks(self) -> dict:
        """Load playbooks from memory/playbooks.json, merged with defaults."""
        saved = _load_json(_PLAYBOOK_FILE, default={})
        merged = dict(DEFAULT_PLAYBOOKS)
        merged.update(saved)
        return merged

    def add_playbook(
        self,
        trigger: str,
        actions: list[str],
        conditions: dict | None = None,
    ) -> dict:
        """Add or overwrite a playbook. Persists to memory/playbooks.json."""
        if conditions is None:
            conditions = {}
        playbooks = _load_json(_PLAYBOOK_FILE, default={})
        playbooks[trigger] = {"actions": actions, "conditions": conditions}
        _save_json(_PLAYBOOK_FILE, playbooks)
        log.info("Playbook saved: %s (%d actions)", trigger, len(actions))
        return playbooks[trigger]

    def list_playbooks(self) -> dict:
        """Return all configured playbooks (defaults + custom)."""
        return self.load_playbooks()

    def playbook_history(self) -> list[dict]:
        """Return last 50 execution history entries."""
        entries = _load_json(_HISTORY_FILE, default=[])
        if not isinstance(entries, list):
            return []
        return entries[-50:]

    # ── Execution engine ──────────────────────────────────────────────────────

    def execute_playbook(self, trigger: str, context: dict | None = None) -> dict:
        """
        Execute the playbook for the given trigger.

        Args:
            trigger: Playbook name (e.g. 'brute_force').
            context: Dict of substitution variables (e.g. {'ip': '192.168.1.50'}).

        Returns an execution report dict.
        """
        if context is None:
            context = {}

        playbooks = self.load_playbooks()
        if trigger not in playbooks:
            msg = f"No playbook found for trigger: {trigger}"
            log.warning(msg)
            return {"trigger": trigger, "status": "not_found", "error": msg}

        playbook  = playbooks[trigger]
        actions   = playbook.get("actions", [])
        results   = []
        started   = _now()

        log.info("Executing playbook: %s (%d actions)", trigger, len(actions))
        bus.publish(
            "playbook_started",
            {"trigger": trigger, "action_count": len(actions)},
            severity="warning",
        )

        for action_str in actions:
            # Parse "action_name:arg" or just "action_name"
            if ":" in action_str:
                action_name, _, raw_arg = action_str.partition(":")
                arg = _format_arg(raw_arg, context)
            else:
                action_name = action_str
                arg = ""

            action_result = self._dispatch_action(action_name.strip(), arg.strip(), context)
            results.append({
                "action": action_str,
                "result": action_result,
                "timestamp": _now(),
            })
            log.debug("Action '%s' → %s", action_str, action_result)

        report = {
            "trigger":    trigger,
            "context":    context,
            "started":    started,
            "completed":  _now(),
            "actions":    results,
            "status":     "completed",
        }
        _append_json_list(_HISTORY_FILE, report)
        bus.publish("playbook_completed", {"trigger": trigger, "status": "completed"}, severity="info")
        return report

    def _dispatch_action(self, action: str, arg: str, context: dict) -> str:
        """Route action name to the corresponding _action_* method."""
        dispatch: dict[str, Any] = {
            "notify_critical":      lambda: self._action_notify_critical(arg, context),
            "notify_high":          lambda: self._action_notify_high(arg, context),
            "notify_warning":       lambda: self._action_notify_warning(arg, context),
            "notify_info":          lambda: self._action_notify_info(arg, context),
            "log_incident":         lambda: self._action_log_incident(arg, context),
            "backup_immediately":   lambda: self._action_backup_immediately(context),
            "integrity_check_all":  lambda: self._action_integrity_check_all(context),
            "activate_friday_protocol": lambda: self._action_activate_friday_protocol(context),
            "switch_to_ollama":     lambda: self._action_switch_to_ollama(context),
            "find_large_files":     lambda: self._action_find_large_files(context),
            "rotate_api_token":     lambda: self._action_rotate_api_token(context),
            "block_ip":             lambda: self._action_block_ip(arg, context),
        }

        handler = dispatch.get(action)
        if handler is None:
            msg = f"Unknown action: {action}"
            log.warning(msg)
            return msg

        try:
            result = handler()
            return result if isinstance(result, str) else str(result)
        except Exception as exc:
            log.error("Action '%s' raised: %s", action, exc, exc_info=True)
            return f"ERROR: {exc}"

    # ── Action implementations ────────────────────────────────────────────────

    def _action_notify_critical(self, msg: str, context: dict) -> str:
        formatted = _format_arg(msg, context)
        try:
            notify("JARVIS CRITICAL", formatted, Priority.CRITICAL)
            bus.alert(formatted, severity="critical")
        except Exception as exc:
            log.error("notify_critical failed: %s", exc)
        return f"CRITICAL notification sent: {formatted}"

    def _action_notify_high(self, msg: str, context: dict) -> str:
        formatted = _format_arg(msg, context)
        try:
            notify("JARVIS HIGH ALERT", formatted, Priority.HIGH)
            bus.alert(formatted, severity="high")
        except Exception as exc:
            log.error("notify_high failed: %s", exc)
        return f"HIGH notification sent: {formatted}"

    def _action_notify_warning(self, msg: str, context: dict) -> str:
        formatted = _format_arg(msg, context)
        try:
            notify("JARVIS WARNING", formatted, Priority.WARNING)
            bus.alert(formatted, severity="warning")
        except Exception as exc:
            log.error("notify_warning failed: %s", exc)
        return f"WARNING notification sent: {formatted}"

    def _action_notify_info(self, msg: str, context: dict) -> str:
        formatted = _format_arg(msg, context)
        try:
            notify("JARVIS INFO", formatted, Priority.INFO)
        except Exception as exc:
            log.error("notify_info failed: %s", exc)
        return f"INFO notification sent: {formatted}"

    def _action_log_incident(self, data: str, context: dict) -> str:
        incident = {
            "timestamp": _now(),
            "trigger":   context.get("trigger", context.get("threat_type", "unknown")),
            "context":   context,
            "note":      data or "",
        }
        try:
            _append_json_list(_INCIDENT_FILE, incident)
        except Exception as exc:
            return f"Failed to log incident: {exc}"
        return f"Incident logged to {_INCIDENT_FILE.name}"

    def _action_backup_immediately(self, context: dict) -> str:
        """Copy the memory/ directory to backups/backup_{timestamp}/."""
        src  = _MEMORY_DIR
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = Path(__file__).parent.parent / "backups" / f"backup_{ts}"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dest))
            log.info("Emergency backup created: %s", dest)
            return f"Backup created at {dest}"
        except Exception as exc:
            log.error("Backup failed: %s", exc)
            return f"Backup FAILED: {exc}"

    def _action_integrity_check_all(self, context: dict) -> str:
        """Try sentinel module first; fall back to checking key JARVIS files exist."""
        try:
            from services.sentinel import sentinel  # type: ignore
            result = sentinel.check_integrity() if hasattr(sentinel, "check_integrity") else None
            if result is not None:
                return f"Sentinel integrity check: {result}"
        except (ImportError, Exception) as exc:
            log.debug("Sentinel unavailable for integrity check: %s", exc)

        # Fallback: check that key files are present and readable
        key_files = [
            Path(__file__).parent.parent / "core" / "event_bus.py",
            Path(__file__).parent.parent / "core" / "llm" / "router.py",
            Path(__file__).parent.parent / "services" / "notifications.py",
            Path(__file__).parent.parent / "config" / "settings.py",
            Path(__file__).parent.parent / "app.py",
        ]
        missing = [str(f) for f in key_files if not f.exists()]
        if missing:
            return f"Integrity check FAILED — missing files: {missing}"
        return f"Integrity check passed — {len(key_files)} core files present"

    def _action_activate_friday_protocol(self, context: dict) -> str:
        """Signal core.state to switch to FRIDAY fallback mode."""
        try:
            from core import state  # type: ignore
            if hasattr(state, "state"):
                state.state.friday_mode = True
                state.state.active_protocol = "FRIDAY"
            elif hasattr(state, "set"):
                state.set("friday_mode", True)
                state.set("active_protocol", "FRIDAY")
            bus.publish("protocol_activated", {"protocol": "FRIDAY"}, severity="warning")
            log.warning("FRIDAY protocol activated.")
            return "FRIDAY protocol activated"
        except Exception as exc:
            log.error("Failed to activate FRIDAY protocol: %s", exc)
            return f"FRIDAY activation failed: {exc}"

    def _action_switch_to_ollama(self, context: dict) -> str:
        """Signal core.state to prefer Ollama over Groq."""
        try:
            from core import state  # type: ignore
            if hasattr(state, "state"):
                state.state.preferred_llm = "ollama"
            elif hasattr(state, "set"):
                state.set("preferred_llm", "ollama")
            bus.publish("llm_switched", {"provider": "ollama"}, severity="warning")
            log.warning("Switched to Ollama as preferred LLM provider.")
            return "Switched to Ollama"
        except Exception as exc:
            log.error("Failed to switch to Ollama: %s", exc)
            return f"Ollama switch failed: {exc}"

    def _action_find_large_files(self, context: dict) -> str:
        """Find files larger than 100 MB using os.walk. Returns summary string."""
        threshold = 100 * 1024 * 1024  # 100 MB
        root = Path(__file__).parent.parent
        large: list[tuple[str, int]] = []

        try:
            for dirpath, _, filenames in os.walk(str(root)):
                # Skip hidden dirs and __pycache__
                if any(part.startswith(".") or part == "__pycache__"
                       for part in Path(dirpath).parts):
                    continue
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        size = os.path.getsize(fpath)
                        if size > threshold:
                            large.append((fpath, size))
                    except OSError:
                        pass
        except Exception as exc:
            return f"find_large_files error: {exc}"

        if not large:
            return "No files over 100 MB found"

        summary_lines = [
            f"{p} ({sz // (1024*1024)} MB)" for p, sz in sorted(large, key=lambda x: -x[1])[:10]
        ]
        result = f"Found {len(large)} large file(s):\n" + "\n".join(summary_lines)
        log.info("[playbook] %s", result)
        return result

    def _action_rotate_api_token(self, context: dict) -> str:
        """
        Generate a new secure token and save it to .env_token_update
        in the project root for manual inspection/application.
        """
        new_token = secrets.token_urlsafe(32)
        token_file = Path(__file__).parent.parent / ".env_token_update"
        try:
            with open(token_file, "w") as f:
                f.write(
                    f"# JARVIS auto-generated token rotation — {_now()}\n"
                    f"JARVIS_API_TOKEN={new_token}\n"
                )
            log.warning("New API token written to %s — apply manually.", token_file)
            return f"New token generated and saved to {token_file.name}"
        except OSError as exc:
            log.error("Token rotation write failed: %s", exc)
            return f"Token rotation failed: {exc}"

    def _action_block_ip(self, ip: str, context: dict) -> str:
        """Record the block in memory/blocked_ips.json (audit trail) AND
        actually add a permanent ufw rule via services.stark_security —
        this used to only do the former, meaning any trigger that ran this
        action logged an IP as "blocked" without anything ever really
        blocking it. Kept fully bracket-guarded: a broken/no-op firewall
        call here shouldn't stop the audit-trail write, which is cheap
        and always useful."""
        if not ip:
            ip = context.get("ip", "unknown")
        entry = {
            "ip":        ip,
            "blocked_at": _now(),
            "reason":    context.get("trigger", context.get("threat_type", "playbook")),
        }
        firewall_note = ""
        try:
            from services.stark_security import stark_security
            result = stark_security.block_ip(ip)
            entry["firewall_blocked"] = result.get("blocked", False)
            if not result.get("blocked"):
                firewall_note = f" (firewall block failed: {result.get('error', 'unknown')})"
        except Exception as exc:
            entry["firewall_blocked"] = False
            firewall_note = f" (firewall block failed: {exc})"
        try:
            blocked = _load_json(_BLOCKED_IP_FILE, default=[])
            if not isinstance(blocked, list):
                blocked = []
            # Avoid duplicates
            if not any(b.get("ip") == ip for b in blocked):
                blocked.append(entry)
                _save_json(_BLOCKED_IP_FILE, blocked)
                log.warning("Blocked IP: %s%s", ip, firewall_note)
                return f"IP {ip} added to block list{firewall_note}"
            return f"IP {ip} already in block list{firewall_note}"
        except Exception as exc:
            return f"block_ip failed for {ip}: {exc}"


# ── Module-level singleton ────────────────────────────────────────────────────
playbook = ThreatPlaybook()
