"""core/causal_reasoning.py — Cause/effect analysis and counterfactuals."""


class CausalReasoning:

    def analyze_causation(self, situation: str) -> dict:
        """Why did X happen? What will happen if Y? Root causes + effects."""
        from core.llm.router import think
        prompt = (
            f"Analyze the causal chain for: {situation}\n\n"
            f"Identify:\n1. Root causes (what caused this?)\n"
            f"2. Immediate effects (what happens next?)\n"
            f"3. Second-order effects (what happens after that?)\n"
            f"4. Interventions (what could change the outcome?)\n\n"
            f"Be specific and concrete."
        )
        analysis = think(prompt, force_model="reasoning")
        return {"situation": situation, "analysis": analysis}

    def counterfactual(self, situation: str, alternative: str) -> dict:
        """What if X had happened instead of Y? Explore alternative timelines."""
        from core.llm.router import think
        prompt = (
            f"Situation: {situation}\nAlternative scenario: {alternative}\n\n"
            f"If '{alternative}' had happened instead:\n"
            f"1. What would be different immediately?\n"
            f"2. What would be different long-term?\n"
            f"3. What would remain the same?\n"
            f"4. Which outcome is better and why?"
        )
        result = think(prompt, force_model="reasoning")
        return {"situation": situation, "alternative": alternative, "analysis": result}


causal = CausalReasoning()
