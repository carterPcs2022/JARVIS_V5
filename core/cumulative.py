"""core/cumulative.py — build an answer one verified fact at a time,
rather than generating everything in one shot. Opt-in, exposed via
server/routes/ultimate_brain.py. Up to 8 iterations * 2 calls each
("instant" tier) plus a final "standard" synthesis — real latency, meant
for queries that specifically ask for verified accuracy."""


class CumulativeReasoner:

    MAX_STEPS = 8

    def reason(self, query: str, context: str = "") -> dict:
        from core.llm.router import think

        facts: list[str] = []
        chain = f"Question: {query}\nContext: {context}\n\n"

        for step in range(self.MAX_STEPS):
            next_fact = think(
                f"{chain}Facts so far:\n" + "\n".join(f"✓ {f}" for f in facts) +
                f"\n\nNext key fact needed? If sufficient facts exist, write SUFFICIENT.\n"
                f"One sentence only.",
                force_model="instant",
            ).strip()

            if "SUFFICIENT" in next_fact.upper():
                break

            verified = think(
                f"Is this fact accurate?\n'{next_fact}'\nContext: {query}\n"
                f"Reply: VERIFIED, UNCERTAIN, or WRONG + why",
                force_model="instant",
            ).strip()

            if "WRONG" in verified.upper():
                corrected = think(
                    f"The fact '{next_fact}' is wrong. What is the correct fact about: {query}",
                    force_model="standard",
                ).strip()
                facts.append(f"{corrected} (corrected)")
            else:
                facts.append(next_fact)
            chain += f"Step {step+1}: {next_fact}\n"

        final = think(
            f"Question: {query}\n\nVerified facts:\n" + "\n".join(f"• {f}" for f in facts) +
            f"\n\nAnswer using ONLY these verified facts.",
            force_model="standard",
        )
        return {"answer": final, "facts": facts, "method": "cumulative_reasoning"}

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in (
            "step by step", "verify", "make sure", "accurate", "precise", "prove",
        ))


cumulative = CumulativeReasoner()
