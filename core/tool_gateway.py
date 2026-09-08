"""Central, policy-aware facade over JARVIS capabilities.

The gateway is intentionally a facade rather than a replacement for existing
execution paths. It exposes safe discovery and execution through the typed Tool
contract while preserving the legacy registries until their callers can be
migrated and regression-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.interfaces.tool import Tool, ToolResult, registry


@dataclass(frozen=True)
class GatewayDecision:
    allowed: bool
    reason: str = ""


class ToolGateway:
    """Discover and execute explicitly registered JARVIS capabilities."""

    def __init__(self, tools: dict[str, Tool] | None = None):
        self._tools = tools if tools is not None else self._build_tools()

    @staticmethod
    def _build_tools() -> dict[str, Tool]:
        tools = dict(registry())

        # GitHub capabilities already have a dedicated, token-authenticated
        # service. Expose only bounded read/review operations here; mutations
        # remain outside this first gateway slice.
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
                    "properties": {"repo": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 30}},
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
                    "properties": {"repo": {"type": "string"}, "pr_number": {"type": "integer", "minimum": 1}},
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
                    "properties": {"repo": {"type": "string"}},
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

    def authorize(self, name: str, *, confirmed: bool = False) -> GatewayDecision:
        tool = self._tools.get(name)
        if tool is None:
            return GatewayDecision(False, "unknown_tool")
        if "network" in tool.permissions and name.startswith("github_"):
            # GitHub access is read-only in this gateway slice. This check is
            # deliberately capability-based instead of relying on model text.
            if tool.risk_level != "low":
                return GatewayDecision(False, "github_mutation_not_exposed")
        if tool.requires_confirmation and not confirmed:
            return GatewayDecision(False, "confirmation_required")
        return GatewayDecision(True, "authorized")

    def execute(self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False) -> ToolResult:
        args = args or {}
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error="unknown_tool")
        decision = self.authorize(name, confirmed=confirmed)
        if not decision.allowed:
            if decision.reason == "confirmation_required":
                return tool.execute(args, confirmed=False)
            return ToolResult(ok=False, error=decision.reason)
        return tool.execute(args, confirmed=confirmed)


gateway = ToolGateway()
