"""Tests for truth metadata and durable bounded task state."""
from __future__ import annotations

from core.task_state import TaskState
from core.truth_engine import TruthEngine


def test_truth_engine_marks_verified_tool_result():
    result = TruthEngine().attach({
        "response": "Repository read complete.",
        "provider": "astra",
        "agent": {"executed": [{"tool": "github_repos", "ok": True}]},
    })
    assert result["truth"]["status"] == "verified"
    assert result["truth"]["confidence"] >= 0.9


def test_truth_engine_does_not_call_model_only_verified():
    result = TruthEngine().attach({"response": "I think this is correct.", "provider": "astra"})
    assert result["truth"]["status"] == "model_only"


def test_task_state_is_bounded_and_serializable(tmp_path, monkeypatch):
    import core.task_state as module
    monkeypatch.setattr(module, "_STATE_FILE", tmp_path / "active_task.json")
    monkeypatch.setattr(module, "_KEY", "test/active_task.json")
    task = TaskState()
    started = task.start("Review the code")
    assert started["status"] == "running"
    task.step("github_review_pr", True, "verified")
    finished = task.finish("complete", "Done")
    assert finished["status"] == "complete"
    assert finished["steps"][0]["ok"] is True
    assert (tmp_path / "active_task.json").exists()


def test_task_state_rejects_invalid_status():
    task = TaskState()
    task.start("x")
    try:
        task.finish("exploded")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status should be rejected")
