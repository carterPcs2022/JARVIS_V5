"""
JARVIS V5 - Productivity Intelligence Service
Focus sessions, tasks, notes, habits, and daily review.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FOCUS_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/focus.json")
TASKS_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/tasks.json")
NOTES_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/notes.json")
HABITS_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/habits.json")
CALENDAR_CACHE_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/calendar_cache.json")
SHORT_TERM_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/short_term.json")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load {path}: {e}")
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


class ProductivityIntelligence:
    """Manages focus sessions, tasks, notes, habits, and daily reviews."""

    def __init__(self):
        self._focus_timer: Optional[threading.Timer] = None
        self._current_session: Optional[dict] = None

    # ─── FOCUS SESSIONS ────────────────────────────────────────────────────────

    def start_focus_session(self, duration_minutes: int = 25, task: str = "") -> dict:
        """
        Start a Pomodoro-style focus session.
        Returns session dict with start_time, duration, task, status.
        """
        # Cancel any existing timer
        if self._focus_timer and self._focus_timer.is_alive():
            self._focus_timer.cancel()

        session = {
            "id": str(uuid.uuid4()),
            "task": task or "Focus Session",
            "duration_minutes": duration_minutes,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "actual_duration_minutes": None,
            "status": "active",
            "completed": False,
        }

        _save_json(FOCUS_FILE, session)
        self._current_session = session

        # Start timer
        self._focus_timer = threading.Timer(
            duration_minutes * 60,
            self._focus_complete
        )
        self._focus_timer.daemon = True
        self._focus_timer.start()

        logger.info(f"Focus session started: {task} ({duration_minutes}m)")
        return session

    def stop_focus_session(self) -> dict:
        """
        Cancel the current focus session early.
        Returns session summary with actual duration.
        """
        if self._focus_timer and self._focus_timer.is_alive():
            self._focus_timer.cancel()
            self._focus_timer = None

        session = _load_json(FOCUS_FILE, {})
        if not session or session.get("status") != "active":
            return {"status": "no_active_session", "message": "No active focus session to stop."}

        now = datetime.now()
        start = datetime.fromisoformat(session["start_time"])
        actual_minutes = round((now - start).total_seconds() / 60, 1)

        session["end_time"] = now.isoformat()
        session["actual_duration_minutes"] = actual_minutes
        session["status"] = "stopped_early"
        session["completed"] = False

        _save_json(FOCUS_FILE, session)
        self._current_session = None

        return {
            "status": "stopped",
            "task": session.get("task"),
            "planned_minutes": session.get("duration_minutes"),
            "actual_minutes": actual_minutes,
            "session_id": session.get("id"),
        }

    def get_focus_status(self) -> dict:
        """Return current session info, or {"active": False} if none."""
        session = _load_json(FOCUS_FILE, {})
        if not session or session.get("status") != "active":
            return {"active": False}

        start = datetime.fromisoformat(session["start_time"])
        elapsed = (datetime.now() - start).total_seconds() / 60
        remaining = max(0.0, session["duration_minutes"] - elapsed)

        return {
            "active": True,
            "task": session.get("task"),
            "duration_minutes": session.get("duration_minutes"),
            "elapsed_minutes": round(elapsed, 1),
            "remaining_minutes": round(remaining, 1),
            "start_time": session.get("start_time"),
            "session_id": session.get("id"),
        }

    def _focus_complete(self) -> None:
        """Called by timer when focus session completes."""
        from services.notifications import notify, Priority

        session = _load_json(FOCUS_FILE, {})
        if session:
            now = datetime.now()
            session["end_time"] = now.isoformat()
            session["actual_duration_minutes"] = session.get("duration_minutes")
            session["status"] = "completed"
            session["completed"] = True
            _save_json(FOCUS_FILE, session)

        task = session.get("task", "Focus Session") if session else "Focus Session"
        duration = session.get("duration_minutes", 25) if session else 25

        try:
            notify(
                title="Focus Session Complete",
                message=f"Well done, sir. {duration} minute session on '{task}' is complete. Time for a break.",
                priority=Priority.HIGH,
            )
        except Exception as e:
            logger.error(f"Focus complete notify failed: {e}")

        self._current_session = None
        self._focus_timer = None
        logger.info(f"Focus session completed: {task}")

    # ─── TASKS ─────────────────────────────────────────────────────────────────

    def add_task(
        self,
        title: str,
        priority: str = "medium",
        due: Optional[str] = None,
        tags: list = None,
    ) -> dict:
        """
        Add a new task to memory/tasks.json.
        Returns task dict with uuid4 id.
        """
        if tags is None:
            tags = []

        tasks = _load_json(TASKS_FILE, [])
        task = {
            "id": str(uuid.uuid4()),
            "title": title,
            "priority": priority,
            "due": due,
            "tags": tags,
            "status": "active",
            "created": datetime.now().isoformat(),
            "completed_at": None,
        }
        tasks.append(task)
        _save_json(TASKS_FILE, tasks)
        return task

    def complete_task(self, task_id: str) -> dict:
        """Mark a task as completed by its ID."""
        tasks = _load_json(TASKS_FILE, [])
        for task in tasks:
            if task.get("id") == task_id:
                task["status"] = "completed"
                task["completed_at"] = datetime.now().isoformat()
                _save_json(TASKS_FILE, tasks)
                return {"status": "ok", "task": task}
        return {"status": "not_found", "message": f"No task found with id '{task_id}'."}

    def task_list(self, filter: str = "active") -> list:
        """Return tasks filtered by status: 'active', 'completed', or 'all'."""
        tasks = _load_json(TASKS_FILE, [])
        if filter == "all":
            return tasks
        return [t for t in tasks if t.get("status") == filter]

    def prioritize_today(self) -> str:
        """
        LLM reviews active tasks and calendar data, suggests top 3 for today.
        Returns prioritization string.
        """
        from core.llm.router import think

        active_tasks = self.task_list("active")
        calendar = _load_json(CALENDAR_CACHE_FILE, {})

        context = {
            "today": date.today().isoformat(),
            "active_tasks": active_tasks[:20],  # Limit context
            "calendar_events_today": calendar.get("today", []) if isinstance(calendar, dict) else [],
        }

        prompt = (
            f"You are JARVIS, an AI assistant. Review the following tasks and calendar data. "
            f"Recommend the top 3 most important tasks to focus on today, with brief reasoning. "
            f"Consider priority, due dates, and calendar commitments. "
            f"Keep it under 150 words.\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
        )
        return think(prompt)

    # ─── NOTES ─────────────────────────────────────────────────────────────────

    def save_note(self, content: str, tags: list = None) -> dict:
        """Save a note to memory/notes.json. Returns note dict."""
        if tags is None:
            tags = []

        notes = _load_json(NOTES_FILE, [])
        note = {
            "id": str(uuid.uuid4()),
            "content": content,
            "tags": tags,
            "timestamp": datetime.now().isoformat(),
        }
        notes.append(note)
        _save_json(NOTES_FILE, notes)
        return note

    def find_note(self, query: str) -> list:
        """Case-insensitive keyword search across all notes. Returns matching list."""
        notes = _load_json(NOTES_FILE, [])
        query_lower = query.lower()
        return [
            note for note in notes
            if query_lower in note.get("content", "").lower()
            or any(query_lower in tag.lower() for tag in note.get("tags", []))
        ]

    # ─── HABITS ────────────────────────────────────────────────────────────────

    def habit_tracker(self) -> dict:
        """
        Read memory/habits.json and return habit state with streaks.
        Returns {"habits": [...], "today_completed": [...], "streaks": {...}}
        """
        data = _load_json(HABITS_FILE, {"habits": [], "log": {}})
        habits = data.get("habits", [])
        log = data.get("log", {})
        today_str = date.today().isoformat()
        today_completed = log.get(today_str, [])

        # Compute streaks
        streaks = {}
        for habit in habits:
            name = habit if isinstance(habit, str) else habit.get("name", "")
            streak = 0
            current = date.today()
            while True:
                day_str = current.isoformat()
                completed_today = log.get(day_str, [])
                if name in completed_today:
                    streak += 1
                    from datetime import timedelta
                    current -= timedelta(days=1)
                else:
                    break
            streaks[name] = streak

        return {
            "habits": habits,
            "today_completed": today_completed,
            "streaks": streaks,
            "today": today_str,
        }

    def log_habit(self, habit_name: str) -> dict:
        """
        Log a habit completion for today.
        Returns updated habit info.
        """
        data = _load_json(HABITS_FILE, {"habits": [], "log": {}})
        habits = data.get("habits", [])
        log = data.get("log", {})
        today_str = date.today().isoformat()

        # Auto-register habit if not present
        habit_names = [h if isinstance(h, str) else h.get("name", "") for h in habits]
        if habit_name not in habit_names:
            habits.append(habit_name)
            data["habits"] = habits

        # Append to today's log (avoid duplicates)
        today_log = log.get(today_str, [])
        if habit_name not in today_log:
            today_log.append(habit_name)
        log[today_str] = today_log
        data["log"] = log

        _save_json(HABITS_FILE, data)
        return self.habit_tracker()

    # ─── REVIEW & TRACKING ─────────────────────────────────────────────────────

    def daily_review(self) -> str:
        """
        LLM generates end-of-day summary from tasks completed + focus sessions + notes.
        Returns review string.
        """
        from core.llm.router import think

        today_str = date.today().isoformat()
        completed_tasks = [
            t for t in self.task_list("completed")
            if (t.get("completed_at") or "").startswith(today_str)
        ]

        focus_session = _load_json(FOCUS_FILE, {})
        today_notes = [
            n for n in _load_json(NOTES_FILE, [])
            if n.get("timestamp", "").startswith(today_str)
        ]

        habits = self.habit_tracker()

        context = {
            "date": today_str,
            "tasks_completed_today": completed_tasks,
            "focus_session": focus_session if focus_session.get("start_time", "").startswith(today_str) else None,
            "notes_taken": len(today_notes),
            "habits_completed": habits.get("today_completed", []),
        }

        prompt = (
            f"You are JARVIS, an AI assistant. Generate an end-of-day review in JARVIS's style. "
            f"Be encouraging, note achievements, and suggest improvements for tomorrow. "
            f"Keep it under 200 words.\n\nDay summary:\n{json.dumps(context, indent=2, default=str)}"
        )
        return think(prompt)

    def time_tracking(self) -> dict:
        """
        Analyze short-term memory to determine what topics were discussed today.
        Returns dict with topic analysis.
        """
        short_term = _load_json(SHORT_TERM_FILE, [])
        today_str = date.today().isoformat()

        today_entries = []
        if isinstance(short_term, list):
            today_entries = [
                e for e in short_term
                if (e.get("timestamp") or e.get("time") or "").startswith(today_str)
            ]
        elif isinstance(short_term, dict):
            # Some implementations store as {date: [entries]}
            today_entries = short_term.get(today_str, [])

        # Count topics/keywords
        topic_counts: dict = {}
        keywords = ["code", "email", "meeting", "research", "health", "finance", "travel",
                    "task", "note", "reminder", "project", "question", "search", "weather"]

        for entry in today_entries:
            text = ""
            if isinstance(entry, dict):
                text = entry.get("content", "") or entry.get("message", "") or str(entry)
            else:
                text = str(entry)

            text_lower = text.lower()
            for kw in keywords:
                if kw in text_lower:
                    topic_counts[kw] = topic_counts.get(kw, 0) + 1

        return {
            "date": today_str,
            "total_interactions_today": len(today_entries),
            "topic_mentions": topic_counts,
            "most_discussed": sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        }


productivity = ProductivityIntelligence()
