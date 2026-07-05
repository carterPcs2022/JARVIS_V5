"""core/scenario_engine.py — probability analysis on any scenario.
"What are my chances of finishing by Friday?" style forecasting."""
import json
import re


class ScenarioEngine:

    def calculate_probability(self, scenario: str, context: dict | None = None) -> dict:
        """Returns: {probability, confidence, positive_factors,
        negative_factors, best_case, worst_case, recommendation, jarvis_summary}"""
        from core.llm.router import think
        from core.memory import universal_recall

        context = context or {}
        memory_context = universal_recall(scenario)

        prompt = (
            f"You are running a probability analysis.\n\n"
            f"Scenario: {scenario}\n"
            f"Context: {memory_context[:500]}\n"
            f"Additional data: {context}\n\n"
            f"Provide a rigorous probability analysis:\n"
            f"1. Probability (0-100%)\n"
            f"2. Confidence in this estimate (low/medium/high)\n"
            f"3. Key factors that increase probability\n"
            f"4. Key factors that decrease probability\n"
            f"5. Best case scenario\n"
            f"6. Worst case scenario\n"
            f"7. What would most improve the odds\n\n"
            f"Reply as JSON with keys: probability, confidence, "
            f"positive_factors, negative_factors, "
            f"best_case, worst_case, recommendation"
        )

        result = think(prompt, force_model="reasoning")

        try:
            clean = re.sub(r"```json|```", "", result).strip()
            data = json.loads(clean)
        except Exception:
            data = {"probability": 50, "confidence": "low", "recommendation": result}

        prob = data.get("probability", 50)
        conf = data.get("confidence", "medium")
        data["jarvis_summary"] = (
            f"Probability assessment: {prob}%. Confidence: {conf}. "
            f"{data.get('recommendation', '')}"
        )
        return data

    def run_simulation(self, scenario: str, variables: dict | None = None, iterations: int = 100) -> dict:
        """Monte-Carlo-style narrative simulation (LLM-estimated, not a
        literal numeric simulation)."""
        from core.llm.router import think

        result = think(
            f"Run a simulation analysis for:\n"
            f"Scenario: {scenario}\n"
            f"Variables: {variables or {}}\n"
            f"Simulate {iterations} iterations mentally.\n\n"
            f"Provide: expected outcome, variance, "
            f"probability distribution description, "
            f"key tipping points, sensitivity analysis.\n"
            f"Be specific with numbers.",
            force_model="reasoning",
        )
        return {"scenario": scenario, "analysis": result, "iterations": iterations}

    def compare_scenarios(self, scenarios: list[str]) -> dict:
        from core.llm.router import think

        formatted = "\n".join(f"{i+1}. {s}" for i, s in enumerate(scenarios))
        result = think(
            f"Compare these scenarios and rank by probability of success:\n{formatted}\n\n"
            f"For each: probability, key advantage, key risk.\n"
            f"Final recommendation: which to pursue and why.",
            force_model="reasoning",
        )
        return {"scenarios": scenarios, "comparison": result}


scenario_engine = ScenarioEngine()
