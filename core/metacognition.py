"""core/metacognition.py — JARVIS thinks about how to think before
answering: classifies the problem type, picks a reasoning tool, and can
self-evaluate its own response afterward.

Opt-in — exposed via server/routes/ultimate_brain.py, NOT auto-wired into
the default chat path. evaluate_approach()+self_evaluate() alone are 2
extra LLM calls per message; chaining them into every /stark/chat request
would double the cost/latency of ordinary conversation for a benefit that
mostly matters on hard, deliberate queries."""
import json
import re

PROBLEM_TYPES = {
    "factual": "Use self-consistency. Verify against memory.",
    "analytical": "Use tree of thought. Explore multiple paths.",
    "creative": "Use mixture of agents. Diverse perspectives.",
    "emotional": "Use emotional simulation. Consider impact.",
    "technical": "Use step-by-step verification.",
    "decision": "Use structured debate. Steelman all options.",
    "prediction": "Use bayesian reasoning. Quantify uncertainty.",
    "causal": "Use causal chain analysis. Find root causes.",
    "philosophical": "Use socratic method. Question assumptions.",
    "abductive": "Use abductive reasoning. Best explanation wins.",
}

_TOOL_MAP = {
    "factual": "self_consistency", "analytical": "tree_of_thought",
    "creative": "mixture_of_agents", "emotional": "direct",
    "technical": "react", "decision": "structured_debate",
    "prediction": "bayesian", "causal": "causal_chain",
    "philosophical": "socratic", "abductive": "abductive",
}


class Metacognition:

    def evaluate_approach(self, query: str) -> dict:
        from core.llm.router import think
        result = think(
            f"Analyze how to best approach this query:\n'{query}'\n\n"
            f"Reply as JSON: {{problem_type, best_approach, "
            f"pitfalls, expected_confidence, wrong_answer_pattern}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            meta = json.loads(clean)
        except Exception:
            meta = {"problem_type": "general", "expected_confidence": 75}
        meta["recommended_tools"] = PROBLEM_TYPES.get(meta.get("problem_type", "general"), "Use standard reasoning.")
        return meta

    def choose_reasoning_tool(self, query: str, meta: dict) -> str:
        return _TOOL_MAP.get(meta.get("problem_type", "general"), "direct")

    def self_evaluate(self, query: str, response: str, meta: dict) -> dict:
        from core.llm.router import think
        pitfalls = meta.get("pitfalls", "")
        wrong = meta.get("wrong_answer_pattern", "")
        result = think(
            f"Evaluate quality of this response:\n"
            f"Query: {query}\nResponse: {response[:400]}\n"
            f"Pitfalls to avoid: {pitfalls}\nWrong answer pattern: {wrong}\n"
            f"Score 1-10. Reply as JSON: {{score, issues, verdict}}",
            force_model="instant",
        )
        try:
            clean = re.sub(r"```json|```", "", result).strip()
            return json.loads(clean)
        except Exception:
            return {"score": 7, "issues": [], "verdict": "ok"}


metacog = Metacognition()
