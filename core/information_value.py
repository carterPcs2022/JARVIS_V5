"""core/information_value.py — value-of-information analysis before deciding."""
from core.llm.router import think


class InformationValueEngine:

    def most_valuable(self, question: str, known: str = "") -> dict:
        result = think(
            f"Question: {question}\nKnown: {known}\n\n"
            f"What single piece of information would most reduce uncertainty?\n"
            f"How to get it? What would you do differently with it?",
            force_model="reasoning",
        )
        return {"question": question, "analysis": result}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "what should i research", "most important information",
            "before i decide", "what to investigate",
        ])


info_value = InformationValueEngine()
