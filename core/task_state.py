"""Durable, bounded state for multi-step JARVIS tasks.

Task state is intentionally small and serializable. It is persisted through
Turso when configured and mirrored locally, matching JARVIS memory semantics.
No credentials, raw tool arguments, or model chain-of-thought are stored.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config.settings import BASE_DIR

_STATE_FILE = BASE_DIR / "memory" / "active_task.json"
_KEY = "memory/active_task.json"
_MAX_STEPS = 20


class TaskState:
    def __init__(self):
        self._lock = threading.Lock()
        self._task: dict[str, Any] | None = None

    def start(self, goal: str) -> dict[str, Any]:
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("task goal is required")
        with self._lock:
            self._task = {
                "id": uuid.uuid4().hex[:12],
                "goal": goal[:1000],
                "status": "running",
                "steps": [],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._persist()
            return self.snapshot()

    def step(self, name: str, ok: bool, summary: str = "") -> dict[str, Any]:
        with self._lock:
            if not self._task:
                raise RuntimeError("no_active_task")
            if len(self._task["steps"]) >= _MAX_STEPS:
                self._task["status"] = "failed"
                self._task["error"] = "step_limit_exceeded"
            else:
                self._task["steps"].append({
                    "name": str(name)[:100],
                    "ok": bool(ok),
                    "summary": str(summary)[:300],
                    "at": datetime.now(timezone.utc).isoformat(),
                })
            self._task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist()
            return self.snapshot()

    def finish(self, status: str = "complete", summary: str = "") -> dict[str, Any]:
        if status not in {"complete", "failed", "cancelled", "waiting_confirmation"}:
            raise ValueError("invalid task status")
        with self._lock:
            if not self._task:
                return {"status": "idle"}
            self._task["status"] = status
            if summary:
                self._task["summary"] = str(summary)[:500]
            self._task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist()
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._task is None:
                return {"status": "idle"}
            return json.loads(json.dumps(self._task))

    def restore(self) -> dict[str, Any]:
        with self._lock:
            data = None
            try:
                from core.turso_store import get
                data = get(_KEY)
            except Exception:
                pass
            if data is None and _STATE_FILE.exists():
                try:
                    data = json.loads(_STATE_FILE.read_text())
                except Exception:
                    data = None
            self._task = data if isinstance(data, dict) and data.get("id") else None
            return self.snapshot()

    def clear(self) -> None:
        with self._lock:
            self._task = None
            self._persist()

    def _persist(self) -> None:
        data = self._task or {"status": "idle"}
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
        try:
            from core.turso_store import put
            put(_KEY, data)
        except Exception:
            pass


task_state = TaskState()
