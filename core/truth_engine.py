"""Deterministic evidence gate for JARVIS responses.

The TruthEngine never proves a model's prose is true. It prevents JARVIS from
presenting an action or system-state claim as verified unless the response has
actual evidence from a real tool/provider path. This is a guardrail, not a
second LLM and never exposes hidden reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TruthAssessment:
    status: str
    confidence: float
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "confidence": self.confidence, "evidence": list(self.evidence)}


class TruthEngine:
    VERIFIED_STATUSES = {"verified", "confirmed"}

    def assess(self, *, response: str, provider: str = "", executed: list[dict] | None = None,
               evidence: list[str] | None = None, error: str = "") -> TruthAssessment:
        executed = executed or []
        evidence = evidence or []
        if error:
            return TruthAssessment("unsupported", 0.0, (error,))
        if executed:
            successful = [item for item in executed if item.get("ok")]
            if successful:
                return TruthAssessment("verified", 0.9, tuple(f"tool:{item.get('tool','unknown')}" for item in successful))
        if evidence:
            return TruthAssessment("supported", 0.8, tuple(str(x)[:160] for x in evidence[:5]))
        if provider in {"astra", "router", "router_fallback"}:
            return TruthAssessment("model_only", 0.6, ())
        return TruthAssessment("unknown", 0.4, ())

    def attach(self, result: dict[str, Any], *, executed: list[dict] | None = None,
               evidence: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        result = dict(result)
        assessment = self.assess(
            response=str(result.get("response", "")),
            provider=str(result.get("provider", "")),
            executed=executed if executed is not None else result.get("agent", {}).get("executed", []),
            evidence=evidence,
            error=str(result.get("error", "")),
        )
        result["truth"] = assessment.as_dict()
        return result


truth_engine = TruthEngine()
