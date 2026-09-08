"""Bounded JARVIS coding workflow.

Provides the orchestration contract for code-aware work: inspect -> propose ->
validate -> smoke-test -> report. It deliberately stops before deployment;
real file changes remain behind the existing human-approved sandbox path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodeTask:
    filepath: str
    objective: str
    reason: str = ""


class CodingEngine:
    """Coordinate bounded code changes without silently deploying them."""

    def __init__(self, max_iterations: int = 3):
        if max_iterations < 1 or max_iterations > 5:
            raise ValueError("max_iterations must be between 1 and 5")
        self.max_iterations = max_iterations

    def inspect(self, task: CodeTask) -> dict[str, Any]:
        """Read the target through the existing sandbox-safe file boundary."""
        from config.settings import BASE_DIR
        from core.self_analysis import ALLOWED_FILES, LOCKED_FILES

        if task.filepath not in ALLOWED_FILES or task.filepath in LOCKED_FILES:
            return {"ok": False, "error": "file_not_editable"}
        path = BASE_DIR / task.filepath
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": "file_not_found"}
        return {"ok": True, "filepath": task.filepath, "content": path.read_text()[:100_000]}

    def propose(self, task: CodeTask) -> dict[str, Any]:
        """Ask the existing sandbox writer for a candidate, without deploying it."""
        inspection = self.inspect(task)
        if not inspection["ok"]:
            return inspection
        from core.sandbox import JarvisSandbox

        candidate = JarvisSandbox().write_improvement(
            task.filepath,
            {"description": task.objective, "reason": task.reason, "lines": "targeted change"},
        )
        validation = JarvisSandbox().validate_code(candidate["new_code"], task.filepath)
        return {"ok": validation["valid"], "candidate": candidate, "validation": validation}

    def verify_candidate(self, task: CodeTask, candidate: str) -> dict[str, Any]:
        """Run static validation and the existing bounded sandbox smoke test."""
        from core.sandbox import JarvisSandbox

        sandbox = JarvisSandbox()
        validation = sandbox.validate_code(candidate, task.filepath)
        if not validation["valid"]:
            return {"ok": False, "validation": validation}
        smoke = sandbox.run_in_sandbox(candidate, task.filepath)
        return {"ok": bool(smoke.get("success")), "validation": validation, "smoke_test": smoke}

    def run(self, task: CodeTask) -> dict[str, Any]:
        """Produce a verified candidate and stop at the approval boundary."""
        for iteration in range(1, self.max_iterations + 1):
            proposal = self.propose(task)
            if not proposal.get("ok"):
                return {"ok": False, "iteration": iteration, "proposal": proposal}
            candidate = proposal["candidate"]["new_code"]
            verification = self.verify_candidate(task, candidate)
            if verification["ok"]:
                return {
                    "ok": True,
                    "iteration": iteration,
                    "filepath": task.filepath,
                    "candidate": candidate,
                    "verification": verification,
                    "approval_required": True,
                    "deployed": False,
                }
        return {"ok": False, "error": "verification_exhausted", "approval_required": True, "deployed": False}


coding_engine = CodingEngine()
