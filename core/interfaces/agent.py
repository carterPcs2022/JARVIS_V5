"""core/interfaces/agent.py — the Agent protocol each agent in
core/agents/ (coder.py, researcher.py, planner_agent.py, deep_research.py)
and core/agentic_loop.py now implements, plus a lazy registry over them.

Each module's original functions stay exactly as they were and existing
callers (core/tool_calling.py's _handle_run_task, server/routes/*.py, ...)
keep working unchanged. Agent.run() is a uniform surface alongside them —
useful once something (Phase 2's router, or a future orchestration layer)
wants to invoke "an agent" without knowing whether that means
coder.generate(), researcher.research(), planner_agent.run(),
deep_research.research()'s fire-and-forget/poll pattern, or
agentic_loop's iterative try/observe/adjust loop.

Confirmed (Phase 6) that no agent here calls another agent directly —
only external orchestrators (core/brain_v2.py, core/tool_calling.py,
core/protocols.py) call into individual agents — so the "agents should not
randomly call each other" rule already held without needing a fix.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    output: Any
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    name: str = "base"

    @abstractmethod
    async def run(self, task: str, context: dict[str, Any] | None = None) -> AgentResult:
        ...


_AGENTS: dict[str, Agent] | None = None


def _build_registry() -> dict[str, Agent]:
    from core.agents.coder import CoderAgent
    from core.agents.researcher import ResearcherAgent
    from core.agents.planner_agent import PlannerAgentAdapter
    from core.agents.deep_research import DeepResearchTaskAgent
    from core.agentic_loop import AgenticLoopAgent

    agents: list[Agent] = [
        CoderAgent(), ResearcherAgent(), PlannerAgentAdapter(), DeepResearchTaskAgent(),
        AgenticLoopAgent(),
    ]
    return {a.name: a for a in agents}


def registry() -> dict[str, Agent]:
    global _AGENTS
    if _AGENTS is None:
        _AGENTS = _build_registry()
    return _AGENTS


def get_agent(name: str) -> Agent | None:
    return registry().get(name)
