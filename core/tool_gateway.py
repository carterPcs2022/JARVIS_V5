"""Central, policy-aware facade over JARVIS capabilities.

This is the trust boundary for model-selected tools: allowlist, argument
validation, confirmation, bounded execution rate, and non-sensitive audit
metadata all happen here before a handler is reached.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from core.interfaces.tool import Tool, ToolResult, registry, validate_tool_args

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_MINUTE = 30
MAX_TOTAL_TOOL_CALLS_PER_MINUTE = 60


@dataclass(frozen=True)
class GatewayDecision:
    allowed: bool
    reason: str = ""


class ToolGateway:
    """Discover and execute explicitly registered JARVIS capabilities."""

    def __init__(self, tools: dict[str, Tool] | None = None):
        self._tools = tools if tools is not None else self._build_tools()
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._total_calls: deque[float] = deque()
        self._rate_lock = threading.Lock()

    @staticmethod
    def _build_tools() -> dict[str, Tool]:
        tools = dict(registry())
        from services.github_intel import github

        tools.update({
            "github_repos": Tool(
                name="github_repos",
                description="List repositories available to the configured GitHub account.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=lambda args: github.get_repos(),
                risk_level="low", permissions=["read", "network"],
            ),
            "github_recent_commits": Tool(
                name="github_recent_commits",
                description="Read recent commits from one configured GitHub repository.",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "maxLength": 200},
                        "days": {"type": "integer", "minimum": 1, "maximum": 30},
                    },
                    "required": ["repo"], "additionalProperties": False,
                },
                handler=lambda args: github.get_recent_commits(args["repo"], int(args.get("days", 7))),
                risk_level="low", permissions=["read", "network"],
            ),
            "github_review_pr": Tool(
                name="github_review_pr",
                description="Fetch and review a pull request from the configured GitHub account.",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "maxLength": 200},
                        "pr_number": {"type": "integer", "minimum": 1, "maximum": 1000000000},
                    },
                    "required": ["repo", "pr_number"], "additionalProperties": False,
                },
                handler=lambda args: github.review_pr(args["repo"], int(args["pr_number"])),
                risk_level="low", permissions=["read", "network"],
            ),
            "github_code_summary": Tool(
                name="github_code_summary",
                description="Read a repository README and summarize its purpose.",
                parameters={
                    "type": "object",
                    "properties": {"repo": {"type": "string", "maxLength": 200}},
                    "required": ["repo"], "additionalProperties": False,
                },
                handler=lambda args: github.code_summary(args["repo"]),
                risk_level="low", permissions=["read", "network"],
            ),
        })
        return tools

    def list_tools(self) -> list[dict[str, Any]]:
        """Return model-facing metadata without exposing handler internals."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "risk_level": tool.risk_level,
                "requires_confirmation": tool.requires_confirmation,
                "reversible": tool.reversible,
                "permissions": list(tool.permissions),
            }
            for tool in self._tools.values()
        ]

    def tool_map(self) -> dict[str, Tool]:
        """Return a shallow copy for trusted adapters that build tool schemas."""
        return dict(self._tools)

    def _rate_allowed(self, name: str) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            total = self._total_calls
            while total and now - total[0] >= 60:
                total.popleft()
            per_tool = self._calls[name]
            while per_tool and now - per_tool[0] >= 60:
                per_tool.popleft()
            if len(total) >= MAX_TOTAL_TOOL_CALLS_PER_MINUTE or len(per_tool) >= MAX_TOOL_CALLS_PER_MINUTE:
                return False
            total.append(now)
            per_tool.append(now)
            # Bound the dictionary so attacker-controlled tool names can never
            # turn this limiter into an unbounded memory sink.
            if len(self._calls) > 128:
                stale = [key for key, values in self._calls.items() if not values]
                for key in stale[:64]:
                    self._calls.pop(key, None)
            return True

    def authorize(self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False) -> GatewayDecision:
        tool = self._tools.get(name)
        if tool is None:
            return GatewayDecision(False, "unknown_tool")
        args = args or {}
        validation_error = validate_tool_args(tool, args)
        if validation_error:
            return GatewayDecision(False, f"invalid_arguments: {validation_error}")
        if "network" in tool.permissions and name.startswith("github_") and tool.risk_level != "low":
            return GatewayDecision(False, "github_mutation_not_exposed")
        if not self._rate_allowed(name):
            return GatewayDecision(False, "tool_rate_limited")
        if tool.requires_confirmation and not confirmed:
            return GatewayDecision(False, "confirmation_required")
        return GatewayDecision(True, "authorized")

    def execute(self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False) -> ToolResult:
        args = args or {}
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error="unknown_tool")
        decision = self.authorize(name, args, confirmed=confirmed)
        if not decision.allowed:
            if decision.reason == "confirmation_required":
                return tool.execute(args, confirmed=False)
            return ToolResult(ok=False, error=decision.reason)
        try:
            result = tool.execute(args, confirmed=confirmed)
            logger.info("tool_execution name=%s ok=%s risk=%s", name, result.ok, tool.risk_level)
            return result
        except Exception as exc:
            logger.exception("tool_execution_unhandled name=%s", name)
            return ToolResult(ok=False, error=f"tool_execution_failed: {type(exc).__name__}")


gateway = ToolGateway()
