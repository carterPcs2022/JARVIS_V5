"""core/agentic_loop.py — true agentic execution: JARVIS tries, observes,
adjusts, and tries again until a task is complete instead of stopping at
the first attempt.

NOT wired into the default chat path — available via
POST /stark/agentic/run. A 15-iteration loop is real cost if every
iteration were a paid Fable call, so the per-step reasoning uses the free
"reasoning" tier by default; only the final synthesis (and the loop itself,
if explicitly requested) escalates to a paid tier. Tool access is
deliberately restricted to read-only/informational tools — an autonomous
loop deciding on its own to run shell commands or write files is a
different risk class than a human explicitly asking for one specific
action."""
import time
from datetime import datetime

MAX_ITERATIONS = 8
_SAFE_TOOLS = ("think", "web_search", "get_weather", "system_info", "read_file", "vision_analyze")

_AGENTIC_TRIGGERS = (
    "find out", "figure out", "investigate", "research and", "look into",
    "handle this", "take care of", "sort out", "complete this",
    "do this for me", "multiple steps", "complex task",
)


class AgenticLoop:

    def run(self, task: str, context: str = "", max_iterations: int = MAX_ITERATIONS,
           step_tier: str = "reasoning", final_tier: str = "opus") -> dict:
        """True agentic execution loop. Returns: {result, steps_taken,
        tools_used, success, iterations, final_answer, steps}."""
        from core.llm.router import think
        from core.executor import execute_step

        steps: list[dict] = []
        tools_used: list[str] = []
        scratch = f"Task: {task}\nContext: {context}\n\n"

        print(f"[AgenticLoop] Starting: {task[:60]}")

        for i in range(max_iterations):
            print(f"[AgenticLoop] Iteration {i+1}/{max_iterations}")

            thought_prompt = (
                f"{scratch}"
                f"Iteration {i+1}. What should I do next?\n\n"
                f"Available tools:\n"
                f"- web_search(query) — search the internet\n"
                f"- system_info() — check system status\n"
                f"- read_file(path) — read a file\n"
                f"- vision_analyze(path) — describe an image\n"
                f"- get_weather(city) — weather\n\n"
                f"If I have enough to complete the task, write:\n"
                f"COMPLETE: [final answer]\n\n"
                f"Otherwise write:\n"
                f"THINK: [my reasoning]\n"
                f"ACTION: [tool_name] | [argument]\n"
            )

            response = think(thought_prompt, force_model=step_tier)

            if "COMPLETE:" in response:
                final = response.split("COMPLETE:")[-1].strip()
                print(f"[AgenticLoop] Complete after {i+1} steps")
                return {
                    "result": final, "final_answer": final, "steps_taken": i + 1,
                    "tools_used": list(set(tools_used)), "success": True,
                    "iterations": i + 1, "steps": steps,
                }

            thought, action, arg = "", "", ""
            if "THINK:" in response:
                thought = response.split("THINK:")[-1].split("ACTION:")[0].strip()
            if "ACTION:" in response:
                action_raw = response.split("ACTION:")[-1].strip()
                if "|" in action_raw:
                    action, _, arg = action_raw.partition("|")
                    action = action.strip().lower()
                    arg = arg.strip()

            observation = "No action taken."
            if action and action in _SAFE_TOOLS:
                tools_used.append(action)
                try:
                    obs = execute_step({
                        "tool": action,
                        "args": {"query": arg, "path": arg, "city": arg, "prompt": arg},
                    })
                    observation = str(obs)[:800]
                    print(f"[AgenticLoop] {action}({arg[:30]}) -> {observation[:100]}")
                except Exception as e:
                    observation = f"Tool error: {e}"
            elif action:
                observation = f"Tool '{action}' is not available to the agentic loop (restricted to: {', '.join(_SAFE_TOOLS)})."

            steps.append({
                "iteration": i + 1, "thought": thought, "action": action,
                "argument": arg, "observation": observation,
            })

            scratch += (
                f"Step {i+1}:\nThought: {thought}\nAction: {action}({arg})\n"
                f"Observation: {observation}\n\n"
            )

        # Max iterations reached — synthesize the best answer from what was gathered
        final = think(
            f"Task: {task}\n\nAfter {max_iterations} steps, here's what I found:\n"
            f"{scratch[-2000:]}\n\nGive the best possible answer with this information.",
            force_model=final_tier,
        )

        return {
            "result": final, "final_answer": final, "steps_taken": max_iterations,
            "tools_used": list(set(tools_used)), "success": False,
            "iterations": max_iterations, "steps": steps,
            "note": "Max iterations reached — synthesized from partial work",
        }

    def should_use_agentic(self, query: str) -> bool:
        """Advisory only — not auto-wired into the default chat path.
        Simple questions don't need an 8-15 step loop."""
        return any(t in query.lower() for t in _AGENTIC_TRIGGERS)


agentic = AgenticLoop()
