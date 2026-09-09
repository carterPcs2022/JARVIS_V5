"""Bounded JARVIS agent loop for model-selected tool use.

The model proposes tools; ToolGateway decides whether they may execute. This
module adds the orchestration layer without making the model an execution
authority. Confirmation gates, verification, and hard round limits remain
inside the gateway/tool contract and the model adapter.
"""
from __future__ import annotations

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
        """Execute one model proposal through the policy boundary."""
        result = self.tool_gateway.execute(name, arguments, confirmed=confirmed)
        return {
            "ok": bool(result.ok),
            "tool": name,
            "output": result.output if result.ok else None,
            "error": result.error or "",
            "confirmation_required": result.error == "confirmation_required",
        }

    async def run_astra(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        effort: str = "high",
        system: str = "",
    ) -> dict[str, Any]:
        """Connect the real Astra response loop to this AgentLoop's gateway."""
        from core.llm.astra_tools import run_with_tools

        result = await run_with_tools(
            messages,
            tool_gateway=self.tool_gateway,
            max_tokens=max_tokens,
            effort=effort,
            system=system,
        )
        return result


agent_loop = AgentLoop()
