"""Safe Responses-API tool bridge for GPT-6 Astra."""
from __future__ import annotations

import json
from typing import Any

import httpx

from core.interfaces.tool import Tool, ToolResult
from core.interfaces.verification import async_with_retry, verify_tool_result
from core.llm.astra import API_URL, TIMEOUT, _config
from core.tool_gateway import ToolGateway, gateway

MAX_ROUNDS = 4
MAX_TOOL_ATTEMPTS = 3


def _strict_compatible(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            return False
        return set(schema.get("required", [])) == set(properties) and all(_strict_compatible(v) for v in properties.values())
    if schema.get("type") == "array":
        return _strict_compatible(schema.get("items", {}))
    return True


def build_tool_schemas(registry: dict[str, Tool]) -> list[dict[str, Any]]:
    return [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters, "strict": _strict_compatible(t.parameters)} for t in registry.values()]


def _text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks).strip()


def _function_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in data.get("output", []) or [] if isinstance(item, dict) and item.get("type") == "function_call"]


def _verification_input(result: ToolResult) -> Any:
    return result.output if result.ok else {"error": result.error or "tool_execution_failed"}


async def _execute_verified(tool: Tool, args: dict[str, Any], tool_gateway: ToolGateway | None = None) -> tuple[ToolResult, Any]:
    # When called with a standalone Tool (for example by a unit test or a
    # trusted adapter), construct a gateway containing exactly that tool. The
    # production Astra path passes the shared gateway explicitly.
    active_gateway = tool_gateway or ToolGateway({tool.name: tool})
    if tool.requires_confirmation:
        result = active_gateway.execute(tool.name, args, confirmed=False)
        return result, verify_tool_result(_verification_input(result), reversible=False)

    async def invoke() -> ToolResult:
        return active_gateway.execute(tool.name, args, confirmed=False)

    def verify(result_value: ToolResult):
        return verify_tool_result(_verification_input(result_value), reversible=tool.reversible)

    return await async_with_retry(invoke, verify=verify, max_attempts=MAX_TOOL_ATTEMPTS if tool.reversible else 1)


async def run_with_tools(messages: list[dict[str, Any]], registry: dict[str, Tool] | None = None, *, tool_gateway: ToolGateway | None = None, max_tokens: int = 4096, effort: str = "high", system: str = "") -> dict[str, Any]:
    api_key, model = _config()
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    effort = effort.lower()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        effort = "high"
    active_gateway = tool_gateway or gateway
    active_registry = registry if registry is not None else active_gateway.tool_map()
    tools = build_tool_schemas(active_registry)
    input_items: list[dict[str, Any]] = list(messages)
    if system:
        input_items.insert(0, {"role": "system", "content": system})
    previous_response_id: str | None = None
    executed: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for round_index in range(MAX_ROUNDS):
            payload: dict[str, Any] = {"model": model, "input": input_items, "tools": tools, "tool_choice": "auto", "parallel_tool_calls": False, "max_output_tokens": max(1, max_tokens), "reasoning": {"effort": effort}}
            if previous_response_id:
                payload["previous_response_id"] = previous_response_id
            response = await client.post(API_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
            response.raise_for_status()
            data = response.json()
            previous_response_id = data.get("id")
            calls = _function_calls(data)
            if not calls:
                return {"content": _text(data), "model": data.get("model", model), "provider": "astra", "executed": executed, "rounds": round_index + 1}

            outputs: list[dict[str, Any]] = []
            for call in calls:
                name = str(call.get("name", ""))
                tool = active_registry.get(name)
                if tool is None:
                    result = {"ok": False, "error": "unknown_tool"}
                else:
                    try:
                        args = json.loads(call.get("arguments") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        args = {}
                        result = {"ok": False, "error": "invalid_arguments"}
                    else:
                        tool_result, verdict = await _execute_verified(tool, args, active_gateway)
                        if tool_result.error == "confirmation_required":
                            return {"content": "", "model": data.get("model", model), "provider": "astra", "executed": executed, "confirmation_required": tool_result.output, "tool": name, "rounds": round_index + 1}
                        raw_output = _verification_input(tool_result)
                        result = {"ok": verdict.success, "output": raw_output if verdict.success else None, "error": verdict.errors[0] if verdict.errors else ""}
                        executed.append({"tool": name, "ok": verdict.success, "attempts": getattr(verdict, "attempts", None) or 1})
                outputs.append({"type": "function_call_output", "call_id": call.get("call_id"), "output": json.dumps(result, default=str)})
            input_items = outputs

    return {"content": "", "model": model, "provider": "astra", "executed": executed, "error": "max_tool_rounds_exceeded", "rounds": MAX_ROUNDS}
