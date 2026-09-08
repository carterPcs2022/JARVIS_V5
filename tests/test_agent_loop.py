"""Regression tests for the model-to-tool policy boundary."""

from core.agent_loop import AgentLoop
from core.interfaces.tool import Tool
from core.tool_gateway import ToolGateway


def test_agent_loop_exposes_only_model_safe_metadata():
    tool = Tool(
        name="read", description="Read something", parameters={"type": "object"},
        handler=lambda args: "ok", permissions=["read"],
    )
    loop = AgentLoop(ToolGateway({"read": tool}))
    schema = loop.tool_schemas()[0]
    assert schema["name"] == "read"
    assert "handler" not in schema


def test_agent_loop_never_bypasses_confirmation():
    calls = []
    tool = Tool(
        name="write", description="Write", parameters={"type": "object"},
        handler=lambda args: calls.append(args) or "done",
        requires_confirmation=True, reversible=False, risk_level="high",
    )
    loop = AgentLoop(ToolGateway({"write": tool}))
    result = loop.execute_proposal("write", {"path": "x"})
    assert result["confirmation_required"] is True
    assert calls == []
