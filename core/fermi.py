"""core/fermi.py — Fermi estimation for order-of-magnitude questions."""
from core.llm.router import think


class FermiEstimator:

    def estimate(self, question: str) -> dict:
        decomposition = think(
            f"Apply Fermi Estimation to: '{question}'\n\n"
            f"Break into estimable components.\n"
            f"Show every step. Give final estimate with range.",
            force_model="reasoning",
        )
        sanity = think(
            f"Fermi estimate for '{question}': {decomposition[:300]}\n"
            f"Sanity check: right order of magnitude? What would make it wrong?",
            force_model="instant",
        )
        return {"question": question, "decomposition": decomposition,
                "sanity_check": sanity}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "how many", "how much would it cost",
            "estimate", "approximately how", "ballpark",
        ])


fermi = FermiEstimator()
