"""Tests for the permission-gated Astra tool bridge."""
from core.interfaces.tool import Tool
from core.llm.astra_tools import build_tool_schemas


def test_tool_schema_preserves_existing_contract():
    tool = Tool(
        name="safe_lookup",
        description="Read a value.",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        handler=lambda args: args["key"],
    )
    schema = build_tool_schemas({tool.name: tool})[0]
    assert schema["type"] == "function"
    assert schema["name"] == "safe_lookup"
    assert schema["parameters"] == tool.parameters
    assert schema["strict"] is True


def test_confirmation_required_tool_does_not_execute():
    calls = []
    tool = Tool(
        name="send_message",
        description="Send a message.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: calls.append(args),
        risk_level="high",
        requires_confirmation=True,
        reversible=False,
    )
    result = tool.execute({}, confirmed=False)
    assert result.ok is False
    assert result.error == "confirmation_required"
    assert calls == []
