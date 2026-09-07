"""Safe Responses-API tool bridge for GPT-6 Astra.

Astra may propose function calls, but JARVIS remains the execution authority.
Only tools explicitly supplied by a JARVIS Tool registry are exposed. Each
Tool's existing confirmation/risk rules are enforced before its handler runs.

This deliberately does NOT expose OpenAI's computer-use tool or arbitrary
shell access. Those capabilities can be integrated later through the same
permission/verification boundary after a dedicated security review.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from core.interfaces.tool import Tool
from core.llm.astra import API_URL, TIMEOUT, _config


MAX_ROUNDS = 4


def build_tool_schemas(registry: dict[str, Tool]) -> list[dict[str, Any]]:
    """Convert JARVIS Tool definitions to Responses function-tool schemas."""
    schemas: list[dict[str, Any]] = []
    for tool in registry.values():
        schemas.append({
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": True,
        })
    return schemas


def _text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                value = part.get("text")
                if isinstance(value, str) and value:
                    chunks.append(value)
    return "\n".join(chunks).strip()


def _function_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in (data.get("output", []) or [])
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]


async def run_with_tools(
    messages: list[dict[str, Any]],
    registry: dict[str, Tool],
    *,
    max_tokens: int = 4096,
    effort: str = "high",
    system: str = "",
) -> dict[str, Any]:
    """Run a bounded Astra function-calling loop through JARVIS Tool objects.

    A confirmation-required tool is never executed. The loop returns a
    ``confirmation_required`` result so the real JARVIS confirmation channel
    can handle it rather than letting the model approve its own side effect.
    """
    api_key, model = _config()
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    effort = effort.lower()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        effort = "high"

    tools = build_tool_schemas(registry)
    input_items: list[dict[str, Any]] = list(messages)
    if system:
        input_items.insert(0, {"role": "system", "content": system})

    previous_response_id: str | None = None
    executed: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for _round in range(MAX_ROUNDS):
            payload: dict[str, Any] = {
                "model": model,
                "input": input_items,
                "tools": tools,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "max_output_tokens": max(1, max_tokens),
                "reasoning": {"effort": effort},
            }
            if previous_response_id:
                payload["previous_response_id"] = previous_response_id

            response = await client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            previous_response_id = data.get("id")

            calls = _function_calls(data)
            if not calls:
                return {
                    "content": _text(data),
                    "model": data.get("model", model),
                    "provider": "astra",
                    "executed": executed,
                    "rounds": _round + 1,
                }

            outputs: list[dict[str, Any]] = []
            for call in calls:
                name = str(call.get("name", ""))
                tool = registry.get(name)
                if tool is None:
                    result = {"ok": False, "error": "unknown_tool"}
                else:
                    try:
                        args = json.loads(call.get("arguments") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        args = {}
                        result = {"ok": False, "error": "invalid_arguments"}
                    else:
                        tool_result = tool.execute(args, confirmed=False)
                        result = {
                            "ok": tool_result.ok,
                            "output": tool_result.output,
                            "error": tool_result.error,
                        }
                        if tool_result.error == "confirmation_required":
                            return {
                                "content": "",
                                "model": data.get("model", model),
                                "provider": "astra",
                                "executed": executed,
                                "confirmation_required": tool_result.output,
                                "tool": name,
                                "rounds": _round + 1,
                            }
                        executed.append({"tool": name, "ok": tool_result.ok})

                outputs.append({
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps(result, default=str),
                })

            input_items = outputs

    return {
        "content": "",
        "model": model,
        "provider": "astra",
        "executed": executed,
        "error": "max_tool_rounds_exceeded",
        "rounds": MAX_ROUNDS,
    }
