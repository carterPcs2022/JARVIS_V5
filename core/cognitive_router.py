"""core/cognitive_router.py — the formal Cognitive Router entry point for
JARVIS V6.

Phase 2 scope (see docs/AUDIT.md §9/§11): this is currently a thin facade
over core/brain_v2.py's Brain.process_dict() — zero logic change. Reading
core/brain_v2.py in full during Phase 2 design made clear that its
Brain.process() is not dead-weight duplicating core/orchestrator.py; it's
~520 lines of dense, safety-critical, incident-hardened logic (Mayday
handling, security-protocol activation refusal, egress filtering for
secrets/PII, the real Protocol Engine check, ...) with 16+ existing call
sites across 10 files. Rewriting or mass-migrating callers to "retire" it
in one phase would be exactly the flag-day cutover the migration rules
warn against, for a rename with no behavioral benefit.

So instead: this module is the new, single designated entry point for any
*new* integration going forward. Existing call sites (server/api.py,
server/websocket.py, server/routes/{chat,voice,glasses,final_upgrade}.py,
services/{phone,webhooks,messaging,predictor,mcp_server}.py) are
deliberately left calling core.brain_v2.brain directly rather than being
migrated in this phase — see the note above. The one real behavior change
Phase 2 makes is inside brain_v2.py itself: Executor._reasoning_engine()
now dispatches through core.interfaces.reasoning's shared registry instead
of a local if/elif (see that method's docstring) — a verified,
answer-text-preserving refactor, not a new code path.

Future phases can extract named pipeline stages out of Brain.process() and
grow this router into something with real structure of its own (per the
master directive's PERCEPTION -> UNDERSTANDING -> ROUTER -> STRATEGY ->
PLANNING -> PERMISSION -> EXECUTION -> OBSERVATION -> VERIFICATION
lifecycle) — deliberately not attempted here, given how much of
Brain.process()'s ordering is load-bearing for specific, documented
production incidents it already fixed.
"""
from __future__ import annotations


class CognitiveRouter:
    def route(self, user_input: str) -> dict:
        """Same contract as core.brain_v2.brain.process_dict(): takes raw
        user input, returns the same response dict every existing caller
        already gets."""
        from core.brain_v2 import brain
        return brain.process_dict(user_input)


router = CognitiveRouter()
