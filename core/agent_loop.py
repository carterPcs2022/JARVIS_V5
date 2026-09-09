"""Bounded JARVIS agent loop for model-selected tool use."""
from __future__ import annotations

import asyncio
from typing import Any

from core.tool_gateway import ToolGateway, gateway

MAX_ROUNDS = 6


class AgentLoop:
    """Model-agnostic bounded tool orchestration contract."""

    def __init__(self, tool_gateway: ToolGateway | None = None, max_rounds: int = MAX_ROUNDS):
        if max_rounds < 1 or max_rounds > 10:
            raise ValueError("max_rounds must be between 1 and 10")
        self.tool_gateway = tool_gateway or gateway
        self.max_rounds = max_rounds

    def tool_schemas(self) -> list[dict[str, Any]]:
        return self.tool_gateway.list_tools()

    def execute_proposal(self, name: str, arguments: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        result = self.tool_gateway.execute(name, arguments, confirmed=confirmed)
        return {
            "ok": bool(result.ok), "tool": name,
            "output": result.output if result.ok else None,
            "error": result.error or "",
            "confirmation_required": result.error == "confirmation_required",
        }

    async def run_astra(self, messages: list[dict[str, Any]], *, max_tokens: int = 4096,
                        effort: str = "high", system: str = "", goal: str = "") -> dict[str, Any]:
        """Run Astra with bounded tools and durable task progress.

        Astra failure is a normal degraded mode: fall back to the existing
        router rather than turning a provider outage into an HTTP 500.
        """
        from core.llm.astra_tools import run_with_tools
        from core.truth_engine import truth_engine
        from core.task_state import task_state

        task_started = False
        if goal:
            task_state.start(goal)
            task_started = True
        try:
            result = await run_with_tools(
                messages, tool_gateway=self.tool_gateway,
                max_tokens=max_tokens, effort=effort, system=system,
            )
            for item in result.get("executed", []):
                task_state.step(item.get("tool", "tool"), item.get("ok", False),
                                "verified tool result" if item.get("ok") else "tool failed")
            if result.get("confirmation_required"):
                if task_started:
                    task_state.finish("waiting_confirmation", "Awaiting explicit confirmation.")
            elif result.get("error"):
                if task_started:
                    task_state.finish("failed", result["error"])
            elif task_started:
                task_state.finish("complete", "Agent task completed.")
            return truth_engine.attach(result)
        except Exception as exc:
            # Do not fabricate an Astra answer. Use the existing provider
            # router and label the result accurately.
            fallback = await asyncio.to_thread(
                __import__("core.llm.router", fromlist=["think"]).think,
                str(messages[-1].get("content", "")),
                context="",
                system=system or None,
                max_tokens=max_tokens,
            )
            result = {
                "content": fallback,
                "model": "",
                "provider": "agent_fallback",
                "executed": [],
                "rounds": 0,
                "error": "astra_unavailable",
            }
            if task_started:
                task_state.finish("failed", "Astra unavailable; served provider fallback.")
            return truth_engine.attach(result)


agent_loop = AgentLoop()
