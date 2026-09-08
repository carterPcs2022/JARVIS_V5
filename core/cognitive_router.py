"""core/cognitive_router.py — designated JARVIS cognitive entry point.

Existing production callers still use core.brain_v2 directly because its
ordering is safety-critical. New integrations should use this facade.

Astra is an optional reasoning engine, never an authority. Deterministic
JARVIS handlers and the decision-quality guard always win over model choice.
The simulated conscience adds structured self-state and deliberation metadata;
it does not execute tools or override hard safety boundaries.
"""
from __future__ import annotations


def _with_conscience(result: dict, assessment) -> dict:
    """Attach bounded conscience metadata without changing the response."""
    if not isinstance(result, dict):
        return result
    result = dict(result)
    result.setdefault("conscience", assessment.as_dict())
    return result


class CognitiveRouter:
    def route(self, user_input: str) -> dict:
        """Route through JARVIS's safest available cognitive path.

        Safety-critical early exits and high-pressure irreversible requests stay
        on the canonical Brain path. This prevents an intelligence preference
        from overriding action/approval semantics or turning a risky request
        into ordinary model output.
        """
        from core.brain_v2 import brain, has_early_exit_trigger
        from core.conscience import conscience
        from core.decision_guard import assess_decision, pushback_message
        from core.llm.astra_gateway import should_use_astra, think as astra_think

        if has_early_exit_trigger(user_input):
            result = brain.process_dict(user_input)
            return _with_conscience(result, conscience.deliberate(user_input, risk_score=0))

        decision = assess_decision(user_input)
        conscience_assessment = conscience.deliberate(
            user_input,
            risk_score=decision.risk_score,
            concerns=decision.reasons if decision.should_push_back else (),
        )
        if decision.should_push_back:
            return {
                "response": pushback_message(decision),
                "ok": False,
                "requires_review": True,
                "risk_score": decision.risk_score,
                "provider": "decision_guard",
                "conscience": conscience_assessment.as_dict(),
            }

        if should_use_astra(user_input):
            result = astra_think(user_input)
            return _with_conscience({
                "response": result["content"],
                "ok": True,
                "model": result.get("model", ""),
                "provider": result.get("provider", "astra"),
            }, conscience_assessment)

        return _with_conscience(brain.process_dict(user_input), conscience_assessment)


router = CognitiveRouter()
