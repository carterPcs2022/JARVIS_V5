"""
core/orchestrator.py — Master Brain Orchestrator.

Combines every reasoning technique in this codebase (Tree of Thought, ReAct,
self-consistency, mixture of agents, reflexion) and picks the right
combination per query.

Deliberately NOT wired into Brain.process() as the default chat path — every
technique here costs multiple LLM calls, and the default path needs to stay
fast and cheap for ordinary messages. This is available via
POST /stark/orchestrate for when you explicitly want JARVIS to think as hard
as possible about something, at the cost of several extra seconds and several
extra API calls.
"""
import asyncio


class MasterOrchestrator:

    def process(self, user_input: str, context: str = "") -> dict:
        from core.tree_of_thought import tot
        from core.react import react
        from core.self_consistency import sc
        from core.multi_agent import mixture_of_agents
        from core.reflexion import reflexion
        from core.context import build_system
        from core.memory import detect_emotion_in_text, check_triggers, store_fact
        from core.llm.router import think

        query_type = self._classify(user_input)
        print(f"[Orchestrator] Query type: {query_type}")

        system = reflexion.inject_lessons(user_input, build_system())

        emotion = detect_emotion_in_text(user_input)
        if emotion.get("should_acknowledge"):
            system += (
                f"\nUser appears to be feeling {emotion['emotion']} "
                f"(intensity: {emotion['intensity']}/10). Acknowledge this appropriately."
            )

        triggered = check_triggers(user_input)
        if triggered:
            context += f"\n[Reminder triggered: {triggered[0]['task']}]"

        if query_type == "simple":
            result, method = {"answer": think(user_input, context, system)}, "direct"
        elif query_type == "factual":
            result, method = sc.answer(user_input, context), "self_consistency"
        elif query_type == "research":
            result, method = react.reason_and_act(user_input, context), "react"
        elif query_type == "complex":
            result, method = tot.think(user_input, context=context), "tree_of_thought"
        elif query_type == "decision":
            result, method = asyncio.run(mixture_of_agents(user_input, context)), "mixture_of_agents"
        else:
            result, method = {"answer": think(user_input, context, system)}, "direct"

        response = result.get("answer") or result.get("final") or result.get("content", "")

        try:
            from core.consciousness import consciousness  # noqa: F401 — reserved for future use
        except Exception:
            pass

        try:
            from core.memory import extract_facts
            for fact in extract_facts(user_input)[:3]:
                store_fact(fact, source="user_statement")
        except Exception:
            pass

        return {
            "response": response,
            "method":   method,
            "meta": {
                "query_type":   query_type,
                "emotion":      emotion,
                "lessons_used": len(reflexion.get_relevant_lessons(user_input)),
                "reminders":    [t["task"] for t in triggered],
            },
        }

    def _classify(self, query: str) -> str:
        from core.react import react
        from core.tree_of_thought import tot

        q = query.lower()
        words = len(query.split())

        if words < 6:
            return "simple"
        if self._is_factual(q):
            return "factual"
        if react.should_use_react(q):
            return "research"
        if tot.should_use_tot(q):
            return "complex"
        if self._is_decision(q):
            return "decision"
        return "standard"

    def _is_factual(self, q: str) -> bool:
        return any(t in q for t in ("what is", "who is", "when did", "how many", "fact check", "is it true", "verify"))

    def _is_decision(self, q: str) -> bool:
        return any(t in q for t in ("should i", "recommend", "advice", "what do you think i should", "help me decide"))


orchestrator = MasterOrchestrator()
