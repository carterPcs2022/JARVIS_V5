"""
core/planner.py — JARVIS task planner.
Breaks complex tasks into executable steps.
"""
import json
from core.llm.router import think

_PLAN_PROMPT = """\
You are JARVIS's planning engine. Break this task into clear steps.
Available tools: web_search, get_weather, system_info, run_shell,
                 read_file, write_file, browser_open, vision_analyze

Output ONLY a JSON array. Each step:
{{"step": 1, "tool": "tool_name", "args": {{}}, "description": "what this does"}}

Use "tool": "think" for pure reasoning steps with args: {{"prompt": "..."}}

Task: {task}

JSON array only, no markdown:"""


def plan(task: str, n_steps: int | None = None) -> list[dict]:
    """Decompose a task into executable steps."""
    raw = think(_PLAN_PROMPT.format(task=task))
    try:
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        steps = json.loads(raw)
        if n_steps:
            steps = steps[:n_steps]
        return steps
    except Exception:
        # Fallback: single think step
        return [{"step": 1, "tool": "think",
                 "args": {"prompt": task},
                 "description": "Direct reasoning"}]


def decompose(task: str, n: int = 3) -> list[str]:
    """Break a task into N parallel subtasks."""
    prompt = (
        f"Break this task into exactly {n} independent subtasks "
        f"that can be worked on simultaneously.\n"
        f"Output ONLY a JSON array of {n} strings.\n\n"
        f"Task: {task}"
    )
    raw = think(prompt)
    try:
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(raw)
    except Exception:
        return [task] * n
