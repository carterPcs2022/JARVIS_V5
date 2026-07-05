"""core/synthesis.py — finds non-obvious connections across memory,
projects, and goals instead of just answering isolated questions."""


class SynthesisEngine:

    def cross_domain_synthesis(self, topic: str) -> dict:
        """Find unexpected connections between this topic and the user's
        life/data/goals."""
        from core.memory import universal_recall
        from core.llm.router import think

        memory = universal_recall(topic)

        result = think(
            f"Topic: {topic}\n"
            f"Relevant context from memory:\n{memory}\n\n"
            f"Find non-obvious connections between this topic and the "
            f"user's life, goals, and projects. What patterns emerge? "
            f"What insights connect seemingly unrelated things? "
            f"Be specific and surprising.",
            force_model="reasoning",
        )
        return {"topic": topic, "synthesis": result}

    def weekly_synthesis(self) -> str:
        """Every Sunday: synthesize the week's themes and patterns."""
        from core.memory import get_context_string
        from core.llm.router import think

        context = get_context_string(50)
        return think(
            f"Synthesize this week's conversations and activity into "
            f"meaningful insights. What themes emerged? What is the "
            f"person really working on or thinking about? What "
            f"connections exist between their different activities? "
            f"What should they pay attention to?\n\n"
            f"Week's activity:\n{context}",
            force_model="reasoning",
        )


synthesis = SynthesisEngine()
