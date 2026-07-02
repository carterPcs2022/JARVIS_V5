"""
JARVIS V5 - Workshop Project Management Service
Tracks personal projects with history, Git integration, and LLM-powered briefings.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

WORKSHOP_FILE = Path("/Users/kisha/Downloads/JARVIS_V5/memory/workshop.json")

# Optional gitpython
try:
    import git as gitpython
    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False

try:
    import subprocess as _subprocess
    SUBPROCESS_AVAILABLE = True
except ImportError:
    SUBPROCESS_AVAILABLE = False


class Workshop:
    """Manages personal workshop projects with history, Git integration, and LLM briefings."""

    def _load(self) -> dict:
        """Load workshop data from JSON file."""
        if not WORKSHOP_FILE.exists():
            return {"projects": {}}
        try:
            with open(WORKSHOP_FILE, "r") as f:
                data = json.load(f)
            if "projects" not in data:
                data["projects"] = {}
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load workshop data: {e}")
            return {"projects": {}}

    def _save(self, data: dict) -> None:
        """Save workshop data to JSON file."""
        WORKSHOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WORKSHOP_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def add_project(
        self,
        name: str,
        description: str,
        path: Optional[str] = None,
        status: str = "active",
    ) -> dict:
        """
        Create a new project entry.
        Returns project dict with id, name, description, path, status, created, updated, history.
        """
        data = self._load()
        now = datetime.now().isoformat()

        if name in data["projects"]:
            return {
                "status": "already_exists",
                "message": f"Project '{name}' already exists. Use update_project_status() to add updates.",
                "project": data["projects"][name],
            }

        project = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "path": path,
            "status": status,
            "created": now,
            "updated": now,
            "history": [],
            "git_repo": None,
        }

        data["projects"][name] = project
        self._save(data)

        logger.info(f"Workshop: added project '{name}'")
        return project

    def update_project_status(self, project_name: str, update: str) -> dict:
        """
        Append a timestamped update to the project's history list.
        Also updates the 'updated' field.
        """
        data = self._load()

        if project_name not in data["projects"]:
            return {
                "status": "not_found",
                "message": f"Project '{project_name}' not found. Use add_project() to create it.",
            }

        now = datetime.now().isoformat()
        entry = {"timestamp": now, "update": update}

        data["projects"][project_name]["history"].append(entry)
        data["projects"][project_name]["updated"] = now
        self._save(data)

        return {
            "status": "ok",
            "project": project_name,
            "update_logged": entry,
            "total_history_entries": len(data["projects"][project_name]["history"]),
        }

    def get_project(self, name: str) -> Optional[dict]:
        """Return project dict by name, or None if not found."""
        data = self._load()
        return data["projects"].get(name)

    def project_brief(self) -> str:
        """LLM generates briefing for all active projects."""
        from core.llm.router import think

        data = self._load()
        active = {
            name: proj
            for name, proj in data["projects"].items()
            if proj.get("status") == "active"
        }

        if not active:
            return "No active projects in the workshop at the moment, sir."

        # Summarize for LLM (trim history to last 5 entries each)
        summary = {}
        for name, proj in active.items():
            summary[name] = {
                "description": proj["description"],
                "created": proj["created"],
                "updated": proj["updated"],
                "recent_history": proj["history"][-5:] if proj["history"] else [],
            }

        context = json.dumps(summary, indent=2, default=str)
        prompt = (
            f"You are JARVIS, an AI assistant. Generate a concise workshop briefing for all "
            f"active projects in JARVIS's professional style. Highlight progress, stale projects, "
            f"and what needs attention. Keep it under 200 words.\n\nActive projects:\n{context}"
        )
        return think(prompt, use_cache=True)

    def suggest_next_step(self, project_name: str) -> str:
        """LLM suggests the next action based on project history."""
        from core.llm.router import think

        project = self.get_project(project_name)
        if not project:
            return f"Project '{project_name}' not found in the workshop."

        context = json.dumps(project, indent=2, default=str)
        prompt = (
            f"You are JARVIS, an AI assistant. Based on the following project data, "
            f"suggest the single most impactful next step. Be specific and actionable. "
            f"Keep it under 100 words.\n\nProject:\n{context}"
        )
        return think(prompt, use_cache=True)

    def list_projects(self, status: Optional[str] = None) -> list:
        """
        Return list of project dicts, optionally filtered by status.
        status options: "active", "completed", "paused", None (all)
        """
        data = self._load()
        projects = list(data["projects"].values())
        if status:
            projects = [p for p in projects if p.get("status") == status]
        return sorted(projects, key=lambda x: x.get("updated", ""), reverse=True)

    def link_to_git(self, project_name: str, repo_path: str) -> dict:
        """
        Store repo path in project and attempt to retrieve commit summary.
        Returns git info dict.
        """
        data = self._load()
        if project_name not in data["projects"]:
            return {
                "status": "not_found",
                "message": f"Project '{project_name}' not found.",
            }

        repo_path_obj = Path(repo_path)
        git_info = {
            "status": "linked",
            "repo_path": str(repo_path),
            "project": project_name,
            "branch": None,
            "recent_commits": [],
            "uncommitted_changes": None,
            "remote_url": None,
        }

        # Try gitpython first
        if GITPYTHON_AVAILABLE and repo_path_obj.exists():
            try:
                repo = gitpython.Repo(repo_path)
                git_info["branch"] = repo.active_branch.name
                git_info["remote_url"] = (
                    repo.remotes[0].url if repo.remotes else None
                )
                git_info["uncommitted_changes"] = len(repo.index.diff(None)) + len(repo.untracked_files)
                commits = list(repo.iter_commits(max_count=10))
                git_info["recent_commits"] = [
                    {
                        "hash": c.hexsha[:8],
                        "message": c.message.strip().split("\n")[0],
                        "author": str(c.author),
                        "date": datetime.fromtimestamp(c.committed_date).isoformat(),
                    }
                    for c in commits
                ]
                git_info["status"] = "ok"
            except Exception as e:
                logger.warning(f"gitpython failed for {repo_path}: {e}")
                git_info["gitpython_error"] = str(e)

        # Fallback: subprocess git commands
        if git_info["branch"] is None and SUBPROCESS_AVAILABLE and repo_path_obj.exists():
            try:
                import subprocess
                branch = subprocess.check_output(
                    ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                git_info["branch"] = branch

                log_out = subprocess.check_output(
                    ["git", "-C", repo_path, "log", "--oneline", "-10"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                git_info["recent_commits"] = [
                    {"hash": line[:7], "message": line[8:]}
                    for line in log_out.splitlines() if line
                ]

                remote_out = subprocess.check_output(
                    ["git", "-C", repo_path, "remote", "get-url", "origin"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                git_info["remote_url"] = remote_out
                git_info["status"] = "ok"
            except Exception as e:
                logger.warning(f"subprocess git failed for {repo_path}: {e}")
                git_info["subprocess_error"] = str(e)
                git_info["status"] = "linked_no_git_info"

        # Save link to project
        data["projects"][project_name]["git_repo"] = repo_path
        data["projects"][project_name]["updated"] = datetime.now().isoformat()
        self._save(data)

        return git_info

    def project_summary(self) -> dict:
        """Return summary statistics for all projects."""
        data = self._load()
        projects = data["projects"]

        total = len(projects)
        active = sum(1 for p in projects.values() if p.get("status") == "active")
        completed = sum(1 for p in projects.values() if p.get("status") == "completed")
        paused = sum(1 for p in projects.values() if p.get("status") == "paused")
        other = total - active - completed - paused

        return {
            "total": total,
            "active": active,
            "completed": completed,
            "paused": paused,
            "other": other,
            "projects": sorted(projects.keys()),
        }


workshop = Workshop()
