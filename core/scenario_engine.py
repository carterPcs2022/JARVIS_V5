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

    def analyze_futures(self, situation: str, n_scenarios: int = 10) -> dict:
        """Actual parallel ensemble sampling: N independent instant-tier
        calls each project one distinct outcome, tallied into a real
        success rate — unlike run_simulation()'s single call asking the
        LLM to describe a distribution from one shot. Infinity War's "14
        million futures" framing, scaled down to something worth the
        Groq calls it costs."""
        import concurrent.futures
        from core.llm.router import think

        def run_one(i: int) -> dict:
            text = think(
                f"Future scenario {i + 1}/{n_scenarios}:\n"
                f"Situation: {situation}\n\n"
                f"Model one possible future outcome. What happens? Does it "
                f"succeed or fail? Key decision point that determines outcome.\n"
                f"Reply as: OUTCOME: [success/failure] | PATH: [key decision] | "
                f"RESULT: [what happens]",
                force_model="instant",
            )
            outcome = "success" if "SUCCESS" in text.upper() else "failure"
            return {"scenario": i + 1, "text": text, "outcome": outcome}

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_one, i) for i in range(n_scenarios)]
            for f in concurrent.futures.as_completed(futures, timeout=30):
                try:
                    results.append(f.result())
                except Exception:
                    pass

        successes = [s for s in results if s["outcome"] == "success"]
        failures = [s for s in results if s["outcome"] == "failure"]

        if successes:
            winning_path = think(
                f"From {len(successes)} successful scenarios:\n"
                + "\n".join(s["text"][:100] for s in successes[:3])
                + "\n\nWhat is the single path to success? One clear recommendation.",
                force_model="standard",
            )
        else:
            winning_path = "No clear path to success found."

        return {
            "situation": situation, "scenarios": n_scenarios,
            "successes": len(successes), "failures": len(failures),
            "success_rate": f"{len(successes) / max(n_scenarios, 1) * 100:.0f}%",
            "winning_path": winning_path,
        }


scenario_engine = ScenarioEngine()
