"""core/mental_models.py — Charlie Munger's mental models library.
JARVIS automatically selects and applies the right model to a query."""
from core.llm.router import think

MENTAL_MODELS = {
    "occams_razor":     "Simplest explanation is usually correct",
    "first_principles": "Break to fundamental truths and rebuild",
    "inversion":        "What would guarantee failure?",
    "second_order":     "What are the consequences of consequences?",
    "margin_of_safety": "Build in buffer for being wrong",
    "opportunity_cost": "What are you giving up?",
    "map_territory":    "Your model is not the reality",
}

_PROMPTS = {
    "occams_razor":     "Apply Occam's Razor. What is the simplest explanation?",
    "first_principles": "Apply First Principles. What are the fundamental truths?",
    "inversion":        "Apply Inversion. What would guarantee failure? Avoid those.",
    "second_order":     "Apply Second-Order Thinking. And then what? And then what?",
    "margin_of_safety": "Apply Margin of Safety. Plan for the worst realistic case.",
    "opportunity_cost": "Apply Opportunity Cost. What is truly being given up?",
    "map_territory":    "Apply Map/Territory. What assumptions are baked in?",
}


class MentalModelsEngine:

    MODEL_TRIGGERS = {
        "occams_razor":     ["explain why", "what caused", "why did"],
        "first_principles": ["from scratch", "fundamentally", "best way to build"],
        "inversion":        ["how do i succeed", "best strategy", "achieve"],
        "second_order":     ["what happens if", "consequences", "should i"],
        "margin_of_safety": ["plan", "estimate", "timeline", "budget"],
        "opportunity_cost": ["choose between", "option a or b", "pick"],
        "map_territory":    ["i think", "i believe", "my model"],
    }

    def select(self, query: str) -> str | None:
        q = query.lower()
        for model, triggers in self.MODEL_TRIGGERS.items():
            if any(t in q for t in triggers):
                return model
        return None

    def apply(self, query: str, context: str = "") -> dict:
        model = self.select(query)
        if not model:
            return {"used_model": None, "response": think(query, context)}
        response = think(
            f"{_PROMPTS[model]}\n\nQuestion: {query}\nContext: {context}",
            force_model="reasoning",
        )
        return {"used_model": model, "description": MENTAL_MODELS[model], "response": response}

    def should_use(self, query: str) -> bool:
        return self.select(query) is not None


mental_models = MentalModelsEngine()


# ── ReasoningStrategy adapter (core/interfaces/reasoning.py) ──────────────────

import asyncio
from core.interfaces.reasoning import ReasoningStrategy, ReasoningResult


class MentalModelsStrategy(ReasoningStrategy):
    name = "mental_models"

    def should_use(self, query: str) -> bool:
        return mental_models.should_use(query)

    async def solve(self, query: str, context: str = "") -> ReasoningResult:
        data = await asyncio.to_thread(mental_models.apply, query, context)
        # core/brain_v2.py's Executor._reasoning_engine() builds its
        # "provider" string as f"mental_model_{used_model}" — the used_model
        # value is preserved in metadata so that redirect can still do that.
        return ReasoningResult(
            answer=data["response"], strategy=self.name,
            metadata={"used_model": data.get("used_model"),
                     "description": data.get("description", "")},
        )
