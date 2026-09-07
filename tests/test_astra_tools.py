"""Tests for the permission-gated Astra tool bridge."""

import asyncio

from core.interfaces.tool import Tool
from core.interfaces.verification import async_with_retry, verify_tool_result
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
    # The existing schema is not strict-compatible, so the bridge must not
    # advertise strict mode and risk an API schema rejection.
    assert schema["strict"] is False


def test_strict_compatible_schema_keeps_strict_mode():
    tool = Tool(
        name="strict_lookup",
        description="Read a value.",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
        handler=lambda args: args["key"],
    )
    schema = build_tool_schemas({tool.name: tool})[0]
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


def test_verification_catches_handler_reported_failure():
    verdict = verify_tool_result({"error": "Timed out"}, reversible=True)
    assert verdict.success is False
    assert verdict.recommended_action == "retry"


def test_async_verification_retries_transient_failure():
    calls = []

    async def invoke():
        calls.append(1)
        if len(calls) == 1:
            return {"error": "connection reset"}
        return {"value": "ok"}

    async def run():
        return await async_with_retry(
            invoke,
            verify=lambda result: verify_tool_result(result, reversible=True),
            max_attempts=2,
            backoff_base=0,
        )

    result, verdict = asyncio.run(run())
    assert result == {"value": "ok"}
    assert verdict.success is True
    assert len(calls) == 2
