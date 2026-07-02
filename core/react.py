"""
core/react.py — ReAct: Reasoning + Acting interleaved.
JARVIS thinks, acts, observes, thinks again — up to MAX_STEPS times.

Opt-in: up to 8 LLM calls per invocation. Not wired into the default chat
path — call directly or via POST /stark/reasoning/react for queries that
genuinely need iterative real-world lookups.
"""


class ReActEngine:

    MAX_STEPS = 8

    # Maps ReAct's action vocabulary onto core/executor.py's real tool names.
    _ACTION_MAP = {
        "web_search":    "web_search",
        "get_weather":   "get_weather",
        "system_status": "system_info",
        "memory_recall": "memory_recall",
        "calculate":     "think",
    }

    def reason_and_act(self, query: str, context: str = "") -> dict:
        from core.llm.router import think
        from core.executor import execute_step

        steps = []
        scratch_pad = f"Question: {query}\nContext: {context}\n\n"

        for step_num in range(self.MAX_STEPS):
            think_prompt = (
                f"{scratch_pad}"
                f"Step {step_num + 1}. Think about what to do next.\n"
                f"If you have enough information to answer, write "
                f"'FINAL ANSWER: [your answer]'\n"
                f"Otherwise write 'THOUGHT: [reasoning]' then "
                f"'ACTION: [tool_name] | [argument]'\n\n"
                f"Available actions: web_search, get_weather, system_status, "
                f"memory_recall, calculate\n"
            )
            raw = think(think_prompt, force_model="standard")

            if "FINAL ANSWER:" in raw:
                answer = raw.split("FINAL ANSWER:")[-1].strip()
                return {"answer": answer, "steps": steps, "iterations": step_num + 1, "method": "react"}

            thought, action = "", ""
            if "THOUGHT:" in raw:
                thought = raw.split("THOUGHT:")[-1].split("ACTION:")[0].strip()
            if "ACTION:" in raw:
                action = raw.split("ACTION:")[-1].strip()

            observation = ""
            if action:
                tool_raw, _, arg = action.partition("|")
                tool_raw = tool_raw.strip().lower().replace(" ", "_")
                arg = arg.strip()
                tool = self._ACTION_MAP.get(tool_raw, "think")
                try:
                    if tool == "memory_recall":
                        from core.memory import recall_as_context
                        observation = recall_as_context(arg) or "No relevant memories found."
                    else:
                        result = execute_step({"tool": tool, "args": {
                            "query": arg, "city": arg, "prompt": arg,
                        }})
                        observation = str(result)[:500]
                except Exception as e:
                    observation = f"Action failed: {e}"

            steps.append({"step": step_num + 1, "thought": thought, "action": action, "observation": observation})
            scratch_pad += f"Thought: {thought}\nAction: {action}\nObservation: {observation}\n\n"

        final = think(
            f"{scratch_pad}\nBased on all observations, answer the original question: {query}",
            force_model="standard",
        )
        return {"answer": final, "steps": steps, "iterations": self.MAX_STEPS, "method": "react_max_steps"}

    def should_use_react(self, query: str) -> bool:
        triggers = [
            "current", "today", "right now", "latest", "what is the",
            "how much is", "price of", "weather", "news", "check",
            "find out", "look up", "search for",
        ]
        return any(t in query.lower() for t in triggers)


react = ReActEngine()
