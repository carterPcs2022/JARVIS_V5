"""
core/state.py — JARVIS global state manager.
Single source of truth for runtime state across all modules.
"""
import threading
from datetime import datetime
from typing import Any


class JarvisState:
    _lock = threading.Lock()

    def __init__(self):
        self._data: dict[str, Any] = {
            "status":           "initializing",   # initializing / online / degraded / offline
            "active_model":     None,
            "active_provider":  None,
            "active_tier":      None,
            "groq_available":   False,
            "ollama_available": False,
            "voice_active":     False,
            "monitoring":       False,
            "healing":          False,
            "sentinel":         False,
            "current_task":     None,
            "agents_running":   0,
            "boot_time":        datetime.now().isoformat(),
            "last_interaction": None,
            "warnings":         [],
        }

    def get(self, key: str, default=None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any):
        with self._lock:
            self._data[key] = value

    def update(self, updates: dict):
        with self._lock:
            self._data.update(updates)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def set_model_status(self, provider: str, model: str, available: bool):
        """Per-model live availability, tracked separately from a
        provider's blanket flag (e.g. "groq_available") — that flag is
        fed exclusively by real health-check probes (e.g. check_groq()),
        so per-request results from actual chat calls (which only know
        about the one model that specific request used) don't clobber it
        based on whichever model happened to be tried last. Groq has 5
        distinct tiers/models sharing call volume; a single flat flag
        for "is Groq available" flickered based on whichever model's
        request most recently succeeded or failed, regardless of whether
        that reflects any other model's real status."""
        with self._lock:
            self._data.setdefault("model_status", {})[f"{provider}:{model}"] = available

    def any_model_available(self, provider: str) -> bool:
        """True if at least one tracked model for this provider succeeded
        on its most recent attempt. False (not True) if no model has been
        attempted yet — matches this class's existing cold-boot precedent
        of defaulting availability flags to False until a real check
        completes, rather than assuming optimistically."""
        with self._lock:
            statuses = self._data.get("model_status", {})
            prefix = f"{provider}:"
            return any(v for k, v in statuses.items() if k.startswith(prefix))

    def add_warning(self, msg: str):
        with self._lock:
            self._data["warnings"].append({
                "msg": msg,
                "ts":  datetime.now().isoformat()
            })
            self._data["warnings"] = self._data["warnings"][-20:]

    def clear_warnings(self):
        with self._lock:
            self._data["warnings"] = []


# Singleton
state = JarvisState()
