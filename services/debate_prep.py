"""services/debate_prep.py — JARVIS prepares you for any conversation,
negotiation, or debate: researches all sides, anticipates arguments."""


class DebatePrep:

    def prepare(self, topic: str, your_position: str = "", opponent_type: str = "general") -> dict:
        """Full debate preparation package."""
        from core.llm.router import think
        from core.tools.web import search

        research = search(topic, max_results=5)
        research_context = "\n".join(
            f"• {r.get('snippet','')}" for r in research if r.get("snippet")
        )

        your_args = think(
            f"Topic: {topic}\n"
            f"Position: {your_position or 'pro'}\n"
            f"Research: {research_context[:1000]}\n\n"
            f"Generate the 5 strongest arguments for this position. "
            f"Be specific and compelling.",
            force_model="reasoning",
        )

        opp_args = think(
            f"Topic: {topic}\n"
            f"Research: {research_context[:1000]}\n\n"
            f"Generate the 5 strongest arguments AGAINST the position "
            f"'{your_position or 'pro'}'. Be genuinely challenging.",
            force_model="reasoning",
        )

        counters = think(
            f"Topic: {topic}\n"
            f"Opposition arguments: {opp_args[:500]}\n\n"
            f"For each opposition argument, provide the strongest counter-argument.",
            force_model="reasoning",
        )

        questions = think(
            f"Topic: {topic}\n"
            f"Position: {your_position}\n\n"
            f"What are the 5 hardest questions you'll face? "
            f"Provide suggested answers for each.",
            force_model="standard",
        )

        opening = think(
            f"Write a compelling 3-sentence opening statement "
            f"for this position on {topic}: {your_position}",
            force_model="standard",
        )

        return {
            "topic": topic,
            "your_position": your_position,
            "your_arguments": your_args,
            "opposition": opp_args,
            "counters": counters,
            "hard_questions": questions,
            "opening": opening,
            "research": research[:3],
        }

    def practice_debate(self, topic: str, your_statement: str) -> str:
        """JARVIS takes the opposing side and debates you."""
        from core.llm.router import think
        return think(
            f"You are taking the opposing position in a debate.\n"
            f"Topic: {topic}\n"
            f"The person just said: '{your_statement}'\n\n"
            f"Respond with the strongest possible counter-argument. "
            f"Be rigorous and challenging. Don't hold back.",
            force_model="reasoning",
        )


debate = DebatePrep()
