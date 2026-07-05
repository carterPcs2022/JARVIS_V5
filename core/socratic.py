"""core/socratic.py — sometimes JARVIS asks questions instead of giving
answers, to help you think it through yourself."""


class SocraticEngine:

    SOCRATIC_TRIGGERS = [
        "i don't know", "help me think", "what should i",
        "i'm confused about", "how do i figure out", "i can't decide",
    ]

    def should_use_socratic(self, query: str) -> bool:
        # Strip apostrophes so "i dont know" matches the same as "i don't
        # know" — contractions get typed both ways constantly.
        q = query.lower().replace("'", "")
        triggers = [t.replace("'", "") for t in self.SOCRATIC_TRIGGERS]
        return any(t in q for t in triggers)

    def guide(self, query: str, context: str = "") -> str:
        from core.llm.router import think
        return think(
            f"Instead of answering directly, guide the person to discover "
            f"the answer themselves using Socratic questioning. Ask 1-2 "
            f"thoughtful questions that help them think through the problem.\n\n"
            f"Their question: {query}\n"
            f"Context: {context}",
            force_model="standard",
        )


socratic = SocraticEngine()
