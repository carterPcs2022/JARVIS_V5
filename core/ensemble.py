"""core/ensemble.py — multi-sample ensemble reasoning with confidence weighting."""
from core.llm.router import think


class EnsembleReasoner:

    def reason(self, query: str, context: str = "", n: int = 3) -> dict:
        chains = []
        for i in range(n):
            resp = think(query, context, force_model="standard",
                        temperature=0.3 + i * 0.2)
            score_raw = think(
                f"Score 0.0-1.0 this reasoning:\nQ: {query}\nA: {resp[:200]}\nNumber only.",
                force_model="instant",
            )
            try:
                score = float("".join(c for c in score_raw if c.isdigit() or c == "."))
                score = min(1.0, max(0.0, score))
            except Exception:
                score = 0.5
            chains.append({"chain": resp, "confidence": score})

        synthesis = think(
            f"Query: {query}\n\nWeighted reasoning:\n"
            + "\n".join(f"[w={c['confidence']:.2f}]: {c['chain'][:150]}" for c in chains)
            + "\n\nSynthesize with weights. Higher weight = more influence.",
            force_model="opus",
        )
        return {"chains": chains, "synthesis": synthesis}


ensemble = EnsembleReasoner()
