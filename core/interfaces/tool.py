"""core/interfaces/tool.py — the Tool protocol: every callable JARVIS can
invoke declares its own risk level and confirmation/permission
requirements, instead of each call site deciding safety ad hoc.

Phase 1 scope: define the interface and populate it for core/executor.py's
nine dispatch-table tools (core/executor.py::TOOLS, added alongside its
existing execute_step() dispatch — that function is untouched, still the
live code path). This module's TOOL_REGISTRY is inert: nothing calls
Tool.execute() instead of execute_step() yet, and no permission check is
enforced anywhere yet. Two real, separate gaps this does NOT yet close:

  1. core/tools/{mac,gmail,google_calendar,spotify,...}.py are not
     registered here yet — only executor.py's nine.
  2. Declaring `risk_level`/`requires_confirmation` here doesn't gate
     anything by itself.

Both are real Phase 3 work ("Tool Registry + permissions" in
docs/AUDIT.md's plan) — the actual enforcement layer (checking
requires_confirmation before running a tool, checking permissions against
a caller's grant) belongs there, once every tool is registered, not
half-wired against nine of ~40.
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
    parameters: dict[str, Any]          # JSON-schema-shaped, same convention
                                         # as core/tool_calling.py's TOOLS_SCHEMA
    handler: Callable[[dict], Any]
    risk_level: str = "low"             # one of RISK_LEVELS
    requires_confirmation: bool = False
    reversible: bool = True
    permissions: list[str] = field(default_factory=list)   # e.g. ["read"], ["execute"]

    def execute(self, args: dict) -> ToolResult:
        """Runs the handler directly — no permission/confirmation check
        (see module docstring: enforcement is Phase 3, not here)."""
        try:
            return ToolResult(ok=True, output=self.handler(args))
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


_TOOLS: dict[str, Tool] | None = None


def registry() -> dict[str, Tool]:
    global _TOOLS
    if _TOOLS is None:
        from core.executor import TOOLS
        _TOOLS = TOOLS
    return _TOOLS


def get_tool(name: str) -> Tool | None:
    return registry().get(name)
