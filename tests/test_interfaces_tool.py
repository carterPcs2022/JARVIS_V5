"""tests/test_interfaces_tool.py — core/interfaces/tool.py."""
from core.interfaces.tool import registry, mac_registry, tool_calling_registry, get_tool, Tool


def test_three_separate_registries_not_merged():
    """The three dispatcher registries remain deliberately separate."""
    executor_tools = registry()
    mac_tools = mac_registry()
    tc_tools = tool_calling_registry()

    assert len(executor_tools) == 9
    assert len(mac_tools) == 33
    assert len(tc_tools) == 7

    assert "web_search" in executor_tools
    assert "web_search_raw" in tc_tools
    assert "web_search" not in tc_tools
    assert get_tool("web_search") is executor_tools["web_search"]


def test_every_tool_isinstance_and_self_named():
    for reg in (registry(), mac_registry(), tool_calling_registry()):
        for name, tool in reg.items():
            assert isinstance(tool, Tool), name
            assert tool.name == name
            assert tool.risk_level in ("low", "medium", "high", "destructive")


def test_exactly_three_tools_require_confirmation():
    """Only irreversible generic tools are confirmation-gated.

    Gmail's draft/send flow is intentionally separate from this generic gate.
    """
    gated = {
        name for reg in (registry(), mac_registry(), tool_calling_registry())
        for name, tool in reg.items() if tool.requires_confirmation
    }
    assert gated == {"run_shell", "write_file", "empty_trash"}


def test_tool_execute_runs_real_handler():
    tool = registry()["system_info"]
    result = tool.execute({})
    assert result.ok is True
    assert result.output


def test_tool_execute_gates_on_requires_confirmation():
    tool = registry()["run_shell"]
    result = tool.execute({"command": "ls"})
    assert result.ok is False
    assert result.error == "confirmation_required"
    assert result.output["tool"] == "run_shell"

    result2 = tool.execute({"command": "ls"}, confirmed=True)
    assert result2.error != "confirmation_required"
