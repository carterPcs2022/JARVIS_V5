"""tests/test_interfaces_tool.py — core/interfaces/tool.py."""
from core.interfaces.tool import registry, mac_registry, tool_calling_registry, get_tool, Tool


def test_three_separate_registries_not_merged():
    """executor.py's "web_search" (core.deep_search -- synthesized answer,
    page-fetching) and tool_calling.py's "web_search_raw"
    (core.tools.search.SearchCascade -- raw multi-provider results) are
    genuinely different capabilities that used to collide on the same
    name; tool_calling.py's was renamed to reconcile that. registry() must
    still stay scoped to executor.py's only, never silently merged with
    the other two."""
    executor_tools = registry()
    mac_tools = mac_registry()
    tc_tools = tool_calling_registry()

    assert len(executor_tools) == 9
    assert len(mac_tools) == 32
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
    """run_shell/write_file (executor.py) and empty_trash (mac_dispatcher.py)
    -- everything else stays ungated so routine use doesn't slow down.
    gmail_send/gmail_confirm_send are deliberately NOT here even though
    sending mail is high-risk -- they have their own complete draft-then-
    confirm flow (core/tools/gmail_send.py) and gating them again here
    would mean confirming a confirmation."""
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

    # confirmed=True bypasses the gate
    result2 = tool.execute({"command": "ls"}, confirmed=True)
    assert result2.error != "confirmation_required"
