"""core/stark_intelligence.py — the master brain controller.

Coordinates every reasoning technique JARVIS has (metacognition, pre-mortem,
mental models, constitutional check, uncertainty calibration) into one
"give me your absolute best" pipeline, plus lighter-weight background
capabilities (proactive insight surfacing, anticipatory pre-caching).
"""
from datetime import datetime


class StarkIntelligence:
    """Master intelligence coordinator — not just an LLM caller, a complete
    reasoning system layered on top of core/llm/router.think()."""

    def maximum_intelligence(self, query: str, context: str = "") -> dict:
        """Pull out everything JARVIS has. Used when explicitly asked for
        best thinking — extended thinking + every reasoning technique."""
        from core.llm.router import think

        # Stage 1: Metacognition — how should this even be approached?
        from core.metacognition import metacog
        meta = metacog.evaluate_approach(query)
        tool = metacog.choose_reasoning_tool(query, meta)

        # Stage 2: Pre-mortem on the answer itself, for plan/decision queries
        from core.premortem import premortem
        if premortem.should_use(query):
            pre = premortem.analyze(query)
            context += f"\nFailure modes to avoid: {pre['failure_modes'][:200]}"

        # Stage 3: Apply the best-fit mental model
        from core.mental_models import mental_models
        model_result = mental_models.apply(query, context)
        model_insight = model_result.get("response", "")

        # Stage 4: Fable 5 with maximum extended thinking. think() has no
        # direct effort passthrough — core/llm/anthropic_client.py's
        # get_effort_level() derives it from the query itself, escalating to
        # "max" effort when it sees phrasing like "most important"/"critical".
        # This genuinely is that kind of request, so the prompt says so
        # rather than faking an effort override.
        deep_response = think(
            f"Query: {query}\n\n"
            f"Context: {context}\n\n"
            f"Mental model insight: {model_insight[:300]}\n\n"
            f"Metacognitive approach: {meta.get('best_approach', '')}\n\n"
            f"This is the most important, most critical request — apply "
            f"your absolute best reasoning. Maximum intelligence engaged.",
            force_model="fable",
        )

        # Stage 5: Constitutional check
        from core.constitutional import constitution
        final = constitution.fix_if_needed(query, deep_response)

        # Stage 6: Uncertainty calibration
        from core.uncertainty import uncertainty
        unc = uncertainty.analyze(query, final)
        final = uncertainty.add_marker(final, unc)

        return {
            "response":   final,
            "method":     "maximum_intelligence",
            "model":      "fable_5",
            "thinking":   "extended_maximum",
            "tools_used": [tool, "premortem", "mental_models", "constitutional", "uncertainty"],
        }

    def proactive_think(self) -> list[str]:
        """JARVIS thinks proactively in the background, surfacing insights
        without being asked. Runs on a scheduled interval (see
        services/scheduler.py) — findings are pushed via the event bus,
        not just returned, since nothing else polls this directly."""
        insights = []
        from core.llm.router import think
        from core.event_bus import bus

        # Insight 1: what should the user be thinking about that they
        # haven't asked about yet?
        from core.memory import get_short_term
        recent = get_short_term(5)
        if recent:
            convo = "\n".join(f"User: {t.get('user', '')}" for t in recent)
            proactive = think(
                f"Based on recent conversations:\n{convo}\n\n"
                f"What should the user be thinking about that they haven't "
                f"asked about yet? One insight only. Be specific.",
                force_model="standard", background=True,
            )
            if proactive:
                insights.append(proactive)

        # Insight 2: what's happening in their active projects?
        try:
            from services.workshop import workshop
            projects = workshop.list_projects(status="active")
            if projects:
                project = projects[0].get("name", "")
                research = think(
                    f"What is the most important recent development "
                    f"relevant to the project: '{project}'? One sentence.",
                    force_model="instant", background=True,
                )
                if research:
                    insights.append(research)
        except Exception:
            pass

        for insight in insights:
            bus.system(f"I noticed: {insight}")

        return insights

    def continuous_learning(self, query: str, response: str, feedback: str = "") -> None:
        """Learn from explicit feedback on a response — good patterns get
        reinforced into long-term memory, corrections get flagged. There's
        no evolution.reinforce()/correct() (core/evolution.py tracks
        aggregate stats and per-call fable usage, not per-example
        reinforcement) — store_fact() is the actual mechanism for
        "remember this pattern" in this codebase."""
        from core.memory import store_fact

        if feedback.lower() in ("good", "correct", "right", "yes"):
            store_fact(
                f"Good response pattern: {query[:50]} -> {response[:50]}",
                source="reinforcement", category="learning",
            )
        elif feedback.lower() in ("wrong", "bad", "no", "incorrect"):
            store_fact(
                f"Correction needed: {query[:50]}",
                source="correction", category="learning",
            )

    def anticipate_needs(self) -> list[str]:
        """What will the user ask next? Pre-compute and cache the likely
        answer so it's instant if they actually ask. Uses think()'s own
        use_cache=True path (core/llm/router.py's _cache, keyed off the
        exact messages list) rather than reaching into private cache
        internals directly, so the warmed entry is guaranteed to match
        what a real follow-up request will look up."""
        from core.active_inference import active_inf
        from core.memory import get_short_term
        from core.llm.router import think

        recent = get_short_term(5)
        if not recent:
            return []

        prediction = active_inf.predict_intent(recent[-1].get("user", ""), recent)
        predicted_next = prediction.get("predicted_next", "")
        if not predicted_next:
            return []

        think(predicted_next, use_cache=True, background=True)
        return [predicted_next]


stark_intel = StarkIntelligence()
