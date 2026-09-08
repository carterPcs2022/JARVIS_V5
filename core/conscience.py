"""JARVIS simulated conscience and self-model.

This module models deliberation, values, uncertainty, and capability awareness.
It does not claim consciousness, infer a person's mental state, or execute tools.
It is an advisory layer that can sit above deterministic permission boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_VALUES = (
    "safety",
    "user_intent",
    "accuracy",
    "privacy",
    "reversibility",
    "efficiency",
)


@dataclass
class SelfModel:
    """Bounded state representing what JARVIS currently knows about itself."""

    identity: str = "JARVIS V5"
    capabilities: set[str] = field(default_factory=set)
    beliefs: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    active_goal: str = ""
    recent_actions: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "capabilities": sorted(self.capabilities),
            "beliefs": list(self.beliefs[-20:]),
            "uncertainties": list(self.uncertainties[-20:]),
            "active_goal": self.active_goal,
            "recent_actions": list(self.recent_actions[-20:]),
        }


@dataclass(frozen=True)
class ConscienceAssessment:
    """A structured advisory result; it never executes an action."""

    intent: str
    risk_score: int
    uncertainty: int
    values_checked: tuple[str, ...]
    concerns: tuple[str, ...]
    recommendation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "risk_score": self.risk_score,
            "uncertainty": self.uncertainty,
            "values_checked": list(self.values_checked),
            "concerns": list(self.concerns),
            "recommendation": self.recommendation,
        }


class Conscience:
    """Deterministic pre-action deliberation facade."""

    def __init__(self, values: tuple[str, ...] = DEFAULT_VALUES, self_model: SelfModel | None = None):
        if not values:
            raise ValueError("conscience requires at least one value")
        self.values = tuple(values)
        self.self_model = self_model or SelfModel()

    def register_capability(self, name: str) -> None:
        if name:
            self.self_model.capabilities.add(name.strip())

    def deliberate(
        self,
        intent: str,
        *,
        risk_score: int = 0,
        uncertainty: int = 0,
        concerns: tuple[str, ...] = (),
    ) -> ConscienceAssessment:
        risk = max(0, min(100, int(risk_score)))
        unknown = max(0, min(100, int(uncertainty)))
        normalized_concerns = tuple(str(c) for c in concerns if str(c).strip())
        if unknown >= 70 or risk >= 70 or normalized_concerns:
            recommendation = "pause_and_review"
        else:
            recommendation = "proceed_if_authorized"
        self.self_model.active_goal = intent.strip()
        if unknown:
            self.self_model.uncertainties.append(f"uncertainty={unknown}")
        return ConscienceAssessment(
            intent=intent.strip(),
            risk_score=risk,
            uncertainty=unknown,
            values_checked=self.values,
            concerns=normalized_concerns,
            recommendation=recommendation,
        )


conscience = Conscience()
