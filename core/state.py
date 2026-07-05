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
