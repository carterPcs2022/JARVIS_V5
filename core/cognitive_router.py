"""core/cognitive_router.py — designated JARVIS cognitive entry point."""
from __future__ import annotations


def _with_conscience(result: dict, assessment) -> dict:
    """Attach bounded conscience metadata without changing the response."""
    if not isinstance(result, dict):
        return result
    result = dict(result)
    result.setdefault("conscience", assessment.as_dict())
    return result


def should_use_agent_loop(user_input: str) -> bool:
    """Return whether a request should enter the real model-selected tool loop."""
    from core.llm.astra_gateway import should_use_astra
    q = (user_input or "").lower()
    tool_intent = any(term in q for term in (
        "github", "repository", "repo", "pull request", "pull requests",
        "recent commits", "review this pr", "review my pr", "codebase",
    ))
    return should_use_astra(user_input) or tool_intent


class CognitiveRouter:
    def route(self, user_input: str) -> dict:
        """Route through JARVIS's safest synchronous cognitive path."""
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

    async def route_async(self, user_input: str) -> dict:
        """Async agentic path: real Astra responses can select JARVIS tools."""
        from core.brain_v2 import brain, has_early_exit_trigger
        from core.conscience import conscience
        from core.decision_guard import assess_decision, pushback_message

        if has_early_exit_trigger(user_input):
            result = brain.process_dict(user_input)
            return _with_conscience(result, conscience.deliberate(user_input, risk_score=0))

        decision = assess_decision(user_input)
        assessment = conscience.deliberate(
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
                "conscience": assessment.as_dict(),
            }

        if should_use_agent_loop(user_input):
            from core.agent_loop import agent_loop
            result = await agent_loop.run_astra(
                [{"role": "user", "content": user_input}],
                system=(
                    "You are JARVIS. Use available tools when they materially "
                    "improve the answer. Never claim a tool action succeeded "
                    "unless its verified result says so. Respect confirmation gates."
                ),
            )
            response = {
                "response": result.get("content", ""),
                "ok": not bool(result.get("error")),
                "model": result.get("model", ""),
                "provider": result.get("provider", "astra"),
                "agent": {
                    "executed": result.get("executed", []),
                    "rounds": result.get("rounds", 0),
                    "confirmation_required": result.get("confirmation_required"),
                    "tool": result.get("tool"),
                    "error": result.get("error", ""),
                },
            }
            return _with_conscience(response, assessment)

        return _with_conscience(brain.process_dict(user_input), assessment)


router = CognitiveRouter()
