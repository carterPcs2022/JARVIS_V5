"""tests/test_executor_enforcement.py — core/executor.py's execute_step():
Phase 3's confirmation gate + Phase 4's verification/retry, together, since
they run in that order in the same function."""
import json
from unittest import mock
from core.executor import execute_step


def test_confirmation_gate_fails_closed_for_run_shell():
    result = json.loads(execute_step({"tool": "run_shell", "args": {"command": "ls"}}))
    assert result["confirmation_required"] is True


def test_confirmation_gate_fails_closed_for_write_file():
    result = json.loads(execute_step({"tool": "write_file", "args": {"path": "/tmp/x", "content": "hi"}}))
    assert result["confirmation_required"] is True


def test_confirmed_true_bypasses_the_gate():
    with mock.patch("core.tools.system.run_shell", return_value={"stdout": "ok"}):
        result = json.loads(execute_step({
            "tool": "run_shell", "args": {"command": "ls"}, "confirmed": True,
        }))
        assert "confirmation_required" not in result


def test_routine_tool_unaffected_by_confirmation_gate():
    with mock.patch("core.tools.system.snapshot", return_value={"os": "Linux"}) as m:
        result = json.loads(execute_step({"tool": "system_info", "args": {}}))
        assert m.call_count == 1
        assert result["os"] == "Linux"


def test_transient_error_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return {"error": "Connection refused"} if calls["n"] < 2 else {"os": "Linux"}

    with mock.patch("core.tools.system.snapshot", side_effect=flaky):
        result = json.loads(execute_step({"tool": "system_info", "args": {}}))
        assert calls["n"] == 2
        assert result["os"] == "Linux"


def test_permanent_error_never_retries():
    with mock.patch("core.tools.system.run_shell") as mock_shell:
        mock_shell.return_value = {"error": "Command not in allowlist: rm -rf /"}
        execute_step({"tool": "run_shell", "args": {"command": "rm -rf /"}, "confirmed": True})
        assert mock_shell.call_count == 1


def test_executor_rejects_malformed_tool_arguments_before_handler():
    with mock.patch("core.tools.system.snapshot") as snapshot:
        result = json.loads(execute_step({"tool": "system_info", "args": {"unexpected": True}}))
        assert result["tool"] == "system_info"
        assert result["error"].startswith("invalid_arguments:")
        snapshot.assert_not_called()
