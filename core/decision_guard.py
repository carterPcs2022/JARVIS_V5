"""Decision-quality guard for high-stakes JARVIS requests.

This is a deterministic advisory layer, not a mind-reader. It detects
message-level urgency/emotional pressure plus potentially irreversible action
language and recommends a pause/review. It never diagnoses a user's mental
state and never executes, cancels, or modifies an action.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionAssessment:
    """Small, serializable assessment suitable for routing/UI telemetry."""
    risk_score: int
    should_push_back: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "should_push_back": self.should_push_back,
            "reasons": list(self.reasons),
        }


_ACTIONS = (
    "delete", "remove", "wipe", "erase", "destroy", "overwrite",
    "shutdown", "disable", "revoke", "publish", "send", "deploy",
    "release", "reset", "format", "terminate",
)
_URGENCY = (
    "right now", "do it now", "immediately", "asap", "no time",
    "don't think", "dont think", "just do it", "before i change my mind",
)
_PRESSURE = (
    "furious", "angry", "rage", "pissed", "panicking", "panic",
    "desperate", "upset", "reckless", "impulsive", "i don't care",
    "i dont care", "whatever happens", "screw it",
)


def assess_decision(text: str) -> DecisionAssessment:
    """Assess whether an action request deserves a deliberate pause.

    The score is intentionally conservative: action language alone is not
    enough to trigger pushback, and emotional language alone is not enough.
    The combination of potentially irreversible action + urgency/pressure is
    what raises the advisory flag.
    """
    low = (text or "").lower()
    reasons: list[str] = []
    action_hit = any(re.search(rf"\b{re.escape(word)}\b", low) for word in _ACTIONS)
    urgency_hit = any(phrase in low for phrase in _URGENCY)
    pressure_hit = any(phrase in low for phrase in _PRESSURE)

    score = 0
    if action_hit:
        score += 45
        reasons.append("potentially irreversible action language")
    if urgency_hit:
        score += 25
        reasons.append("time-pressure language")
    if pressure_hit:
        score += 30
        reasons.append("emotionally pressured language")

    push_back = action_hit and (urgency_hit or pressure_hit) and score >= 70
    return DecisionAssessment(min(score, 100), push_back, tuple(reasons))


def pushback_message(assessment: DecisionAssessment) -> str:
    """Return a concise JARVIS-style pause message for a flagged request."""
    if not assessment.should_push_back:
        return ""
    return (
        "I'm going to pause before that one. The request combines a potentially "
        "irreversible action with high-pressure language. Let's verify the target "
        "and consequence before anything executes."
    )
