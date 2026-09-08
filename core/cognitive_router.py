"""core/cognitive_router.py — designated JARVIS cognitive entry point.

Existing production callers still use core.brain_v2 directly because its
ordering is safety-critical. New integrations should use this facade.

Astra is an optional reasoning engine, never an authority. Deterministic
JARVIS handlers and the decision-quality guard always win over model choice.
"""
from __future__ import annotations


class CognitiveRouter:
    def route(self, user_input: str) -> dict:
        """Route through JARVIS's safest available cognitive path.

        Safety-critical early exits and high-pressure irreversible requests stay
        on the canonical Brain path. This prevents an intelligence preference
        from overriding action/approval semantics or turning a risky request
        into ordinary model output.
        """
        from core.brain_v2 import brain, has_early_exit_trigger
        from core.decision_guard import assess_decision, pushback_message
        from core.llm.astra_gateway import should_use_astra, think as astra_think

        if has_early_exit_trigger(user_input):
            return brain.process_dict(user_input)

        assessment = assess_decision(user_input)
        if assessment.should_push_back:
            return {
                "response": pushback_message(assessment),
                "ok": False,
                "requires_review": True,
                "risk_score": assessment.risk_score,
                "provider": "decision_guard",
            }

        if should_use_astra(user_input):
            result = astra_think(user_input)
            return {
                "response": result["content"],
                "ok": True,
                "model": result.get("model", ""),
                "provider": result.get("provider", "astra"),
            }

        return brain.process_dict(user_input)


router = CognitiveRouter()
