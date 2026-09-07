"""core.interfaces.tool — shared tool contracts and dispatcher registries.

Every callable JARVIS tool declares its risk level and confirmation boundary.
The project intentionally keeps the three dispatcher registries separate:
core.executor, core.mac_dispatcher, and core.tool_calling have different
execution contexts and should not be flattened into one global namespace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

RISK_LEVELS = ("low", "medium", "high", "destructive")


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str = ""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict], Any]
    risk_level: str = "low"
    requires_confirmation: bool = False
    reversible: bool = True
    permissions: list[str] = field(default_factory=list)

    def execute(self, args: dict, confirmed: bool = False) -> ToolResult:
        """Execute safely, registering confirmation-required actions first."""
        if self.requires_confirmation and not confirmed:
            from core.interfaces.permissions import propose
            pending = propose(self.name, args)
            return ToolResult(ok=False, output=pending, error="confirmation_required")
        try:
            return ToolResult(ok=True, output=self.handler(args))
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


_TOOLS: dict[str, Tool] | None = None
_MAC_TOOLS: dict[str, Tool] | None = None
_TOOL_CALLING_TOOLS: dict[str, Tool] | None = None


def registry() -> dict[str, Tool]:
    """Return core/executor.py's tool registry."""
    global _TOOLS
    if _TOOLS is None:
        from core.executor import TOOLS
        _TOOLS = TOOLS
    return _TOOLS


def mac_registry() -> dict[str, Tool]:
    """Return the live Mac dispatcher registry with safety compatibility fixes.

    Older mac_dispatcher versions omitted ``ask_user_choice`` from their
    metadata table even though the dispatcher implements it.  We repair that
    mismatch at the registry boundary rather than duplicating the dispatcher.
    The Gmail final-send operation is also marked confirmation-required here
    so Astra cannot turn a model-generated tool call into an immediate send.
    The normal Mac two-turn Gmail flow remains unchanged.
    """
    global _MAC_TOOLS
    if _MAC_TOOLS is None:
        from core.mac_dispatcher import TOOL_REGISTRY, TOOLS, _execute_tool

        # Compatibility: keep the dispatcher implementation as the source of
        # truth, but expose the already-supported choice tool to typed callers.
        if "ask_user_choice" not in TOOL_REGISTRY and "ask_user_choice" in TOOLS:
            meta = TOOLS["ask_user_choice"]
            TOOL_REGISTRY["ask_user_choice"] = Tool(
                name="ask_user_choice",
                description=meta["desc"],
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "allow_multiple": {"type": "boolean"},
                    },
                    "required": ["question", "options", "allow_multiple"],
                    "additionalProperties": False,
                },
                handler=lambda args: _execute_tool("ask_user_choice", args),
                risk_level="low",
                permissions=["read"],
            )

        # The dispatcher already has a user-facing draft/confirm flow.  For
        # typed model tool calls we add the generic confirmation gate so Astra
        # can propose the send but never perform the irreversible step itself.
        send_tool = TOOL_REGISTRY.get("gmail_confirm_send")
        if send_tool is not None:
            send_tool.requires_confirmation = True
            send_tool.risk_level = "destructive"
            send_tool.reversible = False
            if "destructive" not in send_tool.permissions:
                send_tool.permissions.append("destructive")

        _MAC_TOOLS = TOOL_REGISTRY
    return _MAC_TOOLS


def tool_calling_registry() -> dict[str, Tool]:
    """Return core/tool_calling.py's side-door registry."""
    global _TOOL_CALLING_TOOLS
    if _TOOL_CALLING_TOOLS is None:
        from core.tool_calling import TOOL_OBJECTS
        _TOOL_CALLING_TOOLS = TOOL_OBJECTS
    return _TOOL_CALLING_TOOLS


def get_tool(name: str) -> Tool | None:
    """Look up a tool in the original executor registry."""
    return registry().get(name)
