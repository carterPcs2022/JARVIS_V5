"""core/cognitive_router.py — designated JARVIS cognitive entry point.

Existing production callers still use core.brain_v2 directly because its
ordering is safety-critical. New integrations should use this facade.

When ASTRA_ENABLED=true, explicit high-value requests are sent through the
Astra gateway first. The gateway falls back to the normal JARVIS brain/router
path if Astra is unavailable. Astra never bypasses JARVIS authorization,
executor, or verification layers.
"""
from __future__ import annotations


class CognitiveRouter:
    def route(self, user_input: str) -> dict:
        """Route a new integration request through the safest available path.

        Safety-critical early-exit requests stay on the canonical Brain path.
        This prevents an "use Astra"/"need your best" phrase from accidentally
        turning an actionable JARVIS command into an Astra-only chat response.
        """
        from core.brain_v2 import brain, has_early_exit_trigger
        from core.llm.astra_gateway import should_use_astra, think as astra_think

        # Brain owns the real executor, protocol guards, confirmations, and
        # other deterministic handlers. Never let the intelligence preference
        # override those boundaries.
        if has_early_exit_trigger(user_input):
            return brain.process_dict(user_input)

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
