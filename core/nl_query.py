"""core/nl_query.py — natural language over your own personal data files.
"How much did I spend on food in March?" "Show conversations mentioning
Marcus." One "research"-tier LLM call per query, given only the relevant
data files as context."""
import json
from pathlib import Path

from config.settings import BASE_DIR

DATA_SOURCES = {
    "conversations": BASE_DIR / "memory" / "conversations.json",
    "goals": BASE_DIR / "memory" / "goals.json",
    "tasks": BASE_DIR / "memory" / "tasks.json",
    "people": BASE_DIR / "memory" / "people.json",
    "notes": BASE_DIR / "memory" / "second_brain",
    "habits": BASE_DIR / "memory" / "habits.json",
    "finance": BASE_DIR / "memory" / "finance_cache.json",
    "health": BASE_DIR / "memory" / "health_cache.json",
}


class NaturalLanguageQuery:

    def query(self, question: str) -> dict:
        """Figures out which data sources are relevant, loads them, and
        asks the LLM to answer using only that data."""
        from core.llm.router import think

        sources_to_query = self._identify_sources(question)
        data_context = self._load_sources(sources_to_query)

        answer = think(
            f"Answer this question using ONLY the provided data:\n"
            f"Question: {question}\n\n"
            f"Available data:\n{data_context[:3000]}\n\n"
            f"If the data doesn't contain the answer, say so clearly. "
            f"Be specific with numbers and dates when available.",
            force_model="research",
        )

        return {"question": question, "answer": answer, "sources_queried": sources_to_query}

    def _identify_sources(self, question: str) -> list[str]:
        q = question.lower()
        sources = []
        if any(w in q for w in ["spent", "cost", "money", "budget", "purchase", "transaction"]):
            sources.append("finance")
        if any(w in q for w in ["said", "talked", "conversation", "mentioned", "discussed"]):
            sources.append("conversations")
        if any(w in q for w in ["goal", "objective", "target", "progress"]):
            sources.append("goals")
        if any(w in q for w in ["sleep", "heart", "steps", "health", "workout", "calories"]):
            sources.append("health")
        if any(w in q for w in ["person", "people", "who", "contact", "friend"]):
            sources.append("people")
        if any(w in q for w in ["note", "wrote", "saved", "idea"]):
            sources.append("notes")
        if not sources:
            sources = ["conversations", "goals", "notes"]
        return sources

    def _load_sources(self, sources: list[str]) -> str:
        parts = []
        for source in sources:
            path = DATA_SOURCES.get(source)
            if not path:
                continue
            try:
                if path.is_file():
                    data = json.loads(path.read_text())
                    parts.append(f"[{source.upper()}]:\n{json.dumps(data, default=str)[:1000]}")
                elif path.is_dir():
                    for f in list(path.glob("*.json"))[:3]:
                        parts.append(f"[{source.upper()} - {f.name}]:\n{f.read_text()[:500]}")
            except Exception:
                parts.append(f"[{source}: unavailable]")
        return "\n\n".join(parts)


nl_query = NaturalLanguageQuery()
