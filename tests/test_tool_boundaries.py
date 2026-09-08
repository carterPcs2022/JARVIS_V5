import asyncio

from core.interfaces.permissions import _PENDING, discard
from core.interfaces.tool import Tool
from core.llm.astra_tools import _execute_verified


def _clear_pending():
    for pending_id in list(_PENDING):
        discard(pending_id)


def test_confirmation_required_tool_never_runs_handler():
    _clear_pending()
    calls = []
    tool = Tool(
        name="dangerous_demo",
        description="test",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=lambda args: calls.append(args) or "executed",
        risk_level="destructive",
        requires_confirmation=True,
        reversible=False,
        permissions=["destructive"],
    )

    result = tool.execute({"x": 1})

    assert not result.ok
    assert result.error == "confirmation_required"
    assert result.output["tool"] == "dangerous_demo"
    assert calls == []
    discard(result.output["id"])


def test_mac_registry_repairs_choice_and_gmail_send_boundaries():
    from core.interfaces.tool import mac_registry

    registry = mac_registry()
    assert "ask_user_choice" in registry
    assert registry["ask_user_choice"].parameters["type"] == "object"
    # Gmail already has its own draft-then-confirm flow, so the generic
    # dispatcher gate must not double-gate the final send action.
    assert registry["gmail_confirm_send"].requires_confirmation is False
    assert registry["gmail_confirm_send"].risk_level == "high"
    assert registry["gmail_confirm_send"].reversible is False


def test_astra_does_not_retry_confirmation_gate():
    _clear_pending()
    calls = []
    tool = Tool(
        name="approval_demo",
        description="test",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=lambda args: calls.append(args) or "executed",
        risk_level="destructive",
        requires_confirmation=True,
        reversible=False,
        permissions=["destructive"],
    )

    result, verdict = asyncio.run(_execute_verified(tool, {}))

    assert result.error == "confirmation_required"
    assert not verdict.success
    assert calls == []
    # Exactly one pending action proves the approval gate was not retried.
    assert len(_PENDING) == 1
    pending_id = next(iter(_PENDING))
    discard(pending_id)
