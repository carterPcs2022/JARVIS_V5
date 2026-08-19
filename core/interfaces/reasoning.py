"""core/interfaces/reasoning.py — the ReasoningStrategy protocol every
reasoning-technique module in core/ (react.py, tree_of_thought.py, etc.)
now implements, plus a lazy registry over them.

This does not change how any of those modules are invoked today —
core/orchestrator.py and every server/routes/*.py endpoint that calls them
directly (tot.think(), react.reason_and_act(), sc.answer(), ...) keeps
working exactly as before. This is a parallel, additive surface: a uniform
way to call any reasoning technique without knowing its individual method
name/return shape, for Phase 2's Cognitive Router to build on.
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningResult:
    """Never surface reasoning_trace to end users directly — see the V6
    rule against exposing private chain-of-thought. It's for logging and
    debugging; `answer` is what a user-facing response is built from."""
    answer: str
    confidence: float = 0.5
    strategy: str = ""
    evidence: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    reasoning_trace: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy(cls, strategy: str, data: dict) -> "ReasoningResult":
        """Every existing engine returns its own ad hoc dict shape — e.g.
        graph_of_thought.py's key is "solution", multi_agent.py's is
        "final", self_consistency.py's "confidence" is 0-100 not 0-1.
        Normalizes them into one result type without changing what the
        underlying engines return to their existing direct callers."""
        answer = (
            data.get("answer") or data.get("final") or
            data.get("solution") or data.get("content") or ""
        )
        confidence = data.get("confidence", 0.5)
        if isinstance(confidence, (int, float)) and confidence > 1:
            confidence = confidence / 100
        elif not isinstance(confidence, (int, float)):
            confidence = 0.5
        used_keys = {"answer", "final", "solution", "content", "confidence"}
        return cls(
            answer=answer,
            confidence=confidence,
            strategy=data.get("method", strategy),
            metadata={k: v for k, v in data.items() if k not in used_keys},
        )


class ReasoningStrategy(ABC):
    """One reasoning technique, callable uniformly regardless of what the
    underlying module's own API looks like."""
    name: str = "base"

    @abstractmethod
    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        ...

    def should_use(self, query: str) -> bool:
        """Best-effort applicability check, delegating to each module's
        own heuristic where one exists. Default: always applicable."""
        return True


class DirectStrategy(ReasoningStrategy):
    """The trivial case: one plain LLM call, no extra technique. Not a
    wrapper around an existing module — this *is* core/orchestrator.py's
    "simple"/"standard" fallback, given its own name here so callers can
    request it uniformly alongside the real techniques."""
    name = "direct"

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        from core.llm.router import think
        answer = await asyncio.to_thread(think, query, context)
        return ReasoningResult(answer=answer, confidence=0.5, strategy=self.name)


_STRATEGIES: dict[str, ReasoningStrategy] | None = None


def _build_registry() -> dict[str, ReasoningStrategy]:
    from core.reasoning import ChainOfThoughtStrategy, VerifiedReasoningStrategy
    from core.react import ReActStrategy
    from core.tree_of_thought import TreeOfThoughtStrategy
    from core.graph_of_thought import GraphOfThoughtStrategy
    from core.self_consistency import SelfConsistencyStrategy
    from core.multi_agent import MixtureOfAgentsStrategy

    # These eight are the "reasoning engines" core/brain_v2.py's Planner/
    # Executor actually dispatch to in the live default chat path (see
    # Planner._REASONING_ENGINES) — a completely different set from the
    # eight above, which come from core/orchestrator.py's side-door-only
    # dispatch. Named to match brain_v2's own engine-name strings exactly
    # (e.g. "info_value" not "information_value", "constraint_solver" not
    # "constraint_satisfaction") so Phase 2's redirect of
    # Executor._reasoning_engine() can look them up by the same names.
    from core.six_hats import SixHatsStrategy
    from core.premortem import PremortemStrategy
    from core.fermi import FermiStrategy
    from core.first_principles import FirstPrinciplesStrategy
    from core.constraint_satisfaction import ConstraintSolverStrategy
    from core.game_theory import GameTheoryStrategy
    from core.information_value import InfoValueStrategy
    from core.mental_models import MentalModelsStrategy

    strategies: list[ReasoningStrategy] = [
        DirectStrategy(), ChainOfThoughtStrategy(), VerifiedReasoningStrategy(),
        ReActStrategy(), TreeOfThoughtStrategy(), GraphOfThoughtStrategy(),
        SelfConsistencyStrategy(), MixtureOfAgentsStrategy(),
        SixHatsStrategy(), PremortemStrategy(), FermiStrategy(),
        FirstPrinciplesStrategy(), ConstraintSolverStrategy(), GameTheoryStrategy(),
        InfoValueStrategy(), MentalModelsStrategy(),
    ]
    return {s.name: s for s in strategies}


def registry() -> dict[str, ReasoningStrategy]:
    """Lazily built and cached — importing this module must stay cheap
    even though building the registry pulls in every reasoning module."""
    global _STRATEGIES
    if _STRATEGIES is None:
        _STRATEGIES = _build_registry()
    return _STRATEGIES


def get_strategy(name: str) -> ReasoningStrategy | None:
    return registry().get(name)
