"""services/legal.py — plain-English contract analysis. Educational only,
never legal advice — every response says so explicitly."""


class LegalAnalyzer:

    def analyze_contract(self, text: str) -> dict:
        from core.llm.router import think
        analysis = think(
            f"Analyze this legal document as a knowledgeable friend explaining it in plain English.\n\n"
            f"For each major section:\n1. What it means in simple terms\n"
            f"2. Any red flags or unusual clauses\n3. What you're agreeing to\n"
            f"4. Questions to ask a lawyer\n\nDocument:\n{text[:4000]}\n\n"
            f"Note: This is educational analysis, not legal advice.",
            force_model="fable",
        )
        return {"analysis": analysis, "disclaimer": "Educational analysis only. Not legal advice."}

    def find_red_flags(self, text: str) -> list[str]:
        from core.llm.router import think
        result = think(
            f"List only the red flags and concerning clauses in this document. Be specific:\n\n{text[:3000]}",
            force_model="opus",
        )
        return [line for line in result.split("\n") if line.strip()]

    def simplify_clause(self, clause: str) -> str:
        from core.llm.router import think
        return think(
            f"Explain this legal clause in one simple sentence that anyone can understand:\n\n{clause}",
            force_model="standard",
        )


legal = LegalAnalyzer()
