"""core.interfaces.tool — shared tool contracts and dispatcher registries.

Every callable JARVIS tool declares its risk level and confirmation boundary.
Model-selected tools are expected to enter through ToolGateway, while this
contract also validates arguments when a registry tool is called directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

RISK_LEVELS = ("low", "medium", "high", "destructive")
MAX_STRING_ARG = 65536
MAX_ARRAY_ITEMS = 64
MAX_OBJECT_KEYS = 64


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str = ""


def _validate_value(value: Any, schema: dict[str, Any], path: str = "args") -> str | None:
    """Small dependency-free JSON-schema subset for tool boundaries.

    This is deliberately strict for object shape and basic types. It is not a
    replacement for full JSON Schema, but it closes the most important model
    boundary failures without adding a runtime dependency.
    """
    if not isinstance(schema, dict):
        return None
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        if len(value) > MAX_OBJECT_KEYS:
            return f"{path} has too many keys"
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        missing = sorted(required - set(value))
        if missing:
            return f"missing required argument(s): {', '.join(missing)}"
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                return f"unknown argument(s): {', '.join(unknown)}"
        for key, item in value.items():
            if key in properties:
                error = _validate_value(item, properties[key], f"{path}.{key}")
                if error:
                    return error
        return None
    if schema_type == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        if len(value) > int(schema.get("maxLength", MAX_STRING_ARG)):
            return f"{path} is too long"
    elif schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} must be an integer"
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} is below the minimum"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} is above the maximum"
    elif schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{path} must be a number"
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            return f"{path} must be a boolean"
    elif schema_type == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        if len(value) > int(schema.get("maxItems", MAX_ARRAY_ITEMS)):
            return f"{path} has too many items"
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                error = _validate_value(item, item_schema, f"{path}[{index}]")
                if error:
                    return error
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} has an invalid value"
    return None


def validate_tool_args(tool: "Tool", args: dict[str, Any]) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be an object"
    return _validate_value(args, tool.parameters or {"type": "object"})


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
        """Validate, gate, and execute a tool without exposing exceptions."""
        validation_error = validate_tool_args(self, args)
        if validation_error:
            return ToolResult(ok=False, error=f"invalid_arguments: {validation_error}")
        if self.requires_confirmation and not confirmed:
            from core.interfaces.permissions import propose
            pending = propose(self.name, args)
            return ToolResult(ok=False, output=pending, error="confirmation_required")
        try:
            return ToolResult(ok=True, output=self.handler(args))
        except Exception as e:
            return ToolResult(ok=False, error=f"tool_execution_failed: {type(e).__name__}")


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
    """Return the live Mac dispatcher registry with safety compatibility fixes."""
    global _MAC_TOOLS
    if _MAC_TOOLS is None:
        from core.mac_dispatcher import TOOL_REGISTRY, TOOLS, _execute_tool
        if "ask_user_choice" not in TOOL_REGISTRY and "ask_user_choice" in TOOLS:
            meta = TOOLS["ask_user_choice"]
            TOOL_REGISTRY["ask_user_choice"] = Tool(
                name="ask_user_choice",
                description=meta["desc"],
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "maxLength": 2000},
                        "options": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 4},
                        "allow_multiple": {"type": "boolean"},
                    },
                    "required": ["question", "options", "allow_multiple"],
                    "additionalProperties": False,
                },
                handler=lambda args: _execute_tool("ask_user_choice", args),
                risk_level="low", permissions=["read"],
            )
        send_tool = TOOL_REGISTRY.get("gmail_confirm_send")
        if send_tool is not None:
            send_tool.requires_confirmation = False
            send_tool.risk_level = "high"
            send_tool.reversible = False
            send_tool.permissions = [p for p in send_tool.permissions if p != "destructive"]
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
