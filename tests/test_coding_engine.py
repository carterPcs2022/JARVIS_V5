"""Tests for the bounded code-agent orchestration contract."""

from core.coding_engine import CodeTask, CodingEngine


def test_coding_engine_rejects_locked_or_unknown_files():
    engine = CodingEngine()
    result = engine.inspect(CodeTask("not/a/real/file.py", "improve it"))
    assert result["ok"] is False
    assert result["error"] == "file_not_editable"


def test_coding_engine_bounds_iterations():
    assert CodingEngine(1).max_iterations == 1
    assert CodingEngine(5).max_iterations == 5


def test_coding_engine_never_reports_deployed_from_verified_candidate(monkeypatch):
    engine = CodingEngine(max_iterations=1)
    task = CodeTask("core/conscience.py", "improve documentation")

    monkeypatch.setattr(engine, "propose", lambda task: {
        "ok": True,
        "candidate": {"new_code": "x = 1\n"},
        "validation": {"valid": True},
    })
    monkeypatch.setattr(engine, "verify_candidate", lambda task, candidate: {"ok": True})

    result = engine.run(task)
    assert result["ok"] is True
    assert result["approval_required"] is True
    assert result["deployed"] is False
