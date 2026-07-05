"""services/autonomous_handler.py — "JARVIS handle this for me": takes a
task completely off your plate, runs it in the background, reports back
when done."""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

HANDLED_FILE = BASE_DIR / "memory" / "handled_tasks.json"


class AutonomousHandler:

    def __init__(self):
        self._active_tasks: dict = {}

    def handle(self, task: str, notify_on_complete: bool = True) -> dict:
        """JARVIS takes over. You hear nothing until it's done.
        Returns a task ID immediately; the task runs on a background thread."""
        task_id = f"task_{int(time.time())}"

        def _run():
            print(f"[JARVIS] Handling: {task}")
            start = time.time()

            try:
                from core.agents.planner_agent import run
                result = run(task)
                final = result.get("final", "Task complete.")
                status = "complete"
            except Exception as e:
                final = f"Task encountered an issue: {e}"
                status = "failed"

            elapsed = round(time.time() - start, 1)

            self._log_task({
                "id": task_id,
                "task": task,
                "result": final,
                "status": status,
                "elapsed": elapsed,
                "ts": datetime.now().isoformat(),
            })

            if notify_on_complete:
                from core.event_bus import bus
                bus.publish("task_complete", {
                    "task_id": task_id,
                    "task": task,
                    "result": final[:200],
                    "elapsed": elapsed,
                    "status": status,
                })
                bus.system(f"Task complete, sir. '{task[:50]}' — {final[:100]} ({elapsed}s)")

            self._active_tasks.pop(task_id, None)

        t = threading.Thread(target=_run, daemon=True, name=f"jarvis-handler-{task_id}")
        t.start()
        self._active_tasks[task_id] = {
            "task": task,
            "started": datetime.now().isoformat(),
            "thread": t,
        }

        return {
            "task_id": task_id,
            "message": "On it, sir. I'll let you know when it's done.",
            "task": task,
        }

    def active_tasks(self) -> list[dict]:
        return [
            {"task_id": tid, "task": t["task"], "started": t["started"]}
            for tid, t in self._active_tasks.items()
        ]

    def completed_tasks(self, limit: int = 10) -> list[dict]:
        tasks = self._load()
        return sorted(tasks, key=lambda x: x["ts"], reverse=True)[:limit]

    def _log_task(self, task: dict):
        tasks = self._load()
        tasks.append(task)
        HANDLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        HANDLED_FILE.write_text(json.dumps(tasks[-100:], indent=2))

    def _load(self) -> list:
        if HANDLED_FILE.exists():
            try:
                return json.loads(HANDLED_FILE.read_text())
            except Exception:
                return []
        return []


handler = AutonomousHandler()
