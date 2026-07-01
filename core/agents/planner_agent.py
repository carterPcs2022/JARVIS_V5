"""core/agents/planner_agent.py — Autonomous multi-step task agent."""
import json, time
from datetime import datetime
from core.planner import plan, decompose
from core.executor import execute_step
from core.llm.router import think
from config.settings import JARVIS_PERSONALITY, TASK_LOG

def run(task: str) -> dict:
    print(f"[JARVIS Agent] Starting: {task}")
    start   = time.time()
    steps   = plan(task)
    history = []
    for step in steps[:10]:
        print(f"  Step {step.get('step')}: {step.get('description')}")
        result = execute_step(step)
        history.append({"step": step, "result": str(result)[:500]})
        done_check = think(
            f"Task: {task}\nCompleted steps: {json.dumps(history[-3:])}\n"
            f"Is this task complete? Reply only: YES or NO"
        )
        if "YES" in done_check.upper():
            break
    final = think(
        f"{JARVIS_PERSONALITY}\nTask: {task}\n"
        f"Execution log:\n{json.dumps(history, indent=2)}\n"
        f"Summarize what was accomplished."
    )
    elapsed = round(time.time() - start, 2)
    entry = {"task": task, "final": final, "steps": len(history),
             "history": history, "elapsed_s": elapsed, "ts": datetime.now().isoformat()}
    _log(entry)
    return entry

def run_parallel(task: str, n_agents: int = 3) -> dict:
    import asyncio
    subtasks = decompose(task, n_agents)
    async def _agent(i, subtask):
        result = think(f"{JARVIS_PERSONALITY}\nSubtask {i}: {subtask}")
        return {"agent": i, "subtask": subtask, "result": result}
    async def _gather():
        return await asyncio.gather(*[_agent(i+1, st) for i, st in enumerate(subtasks)])
    results  = asyncio.run(_gather())
    combined = "\n\n".join(f"[Agent {r['agent']}]:\n{r['result']}" for r in results)
    final    = think(f"Synthesize these agent outputs for: {task}\n\n{combined}")
    return {"final": final, "subtasks": subtasks, "agent_results": list(results)}

def _log(entry: dict):
    TASK_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if TASK_LOG.exists():
        with open(TASK_LOG) as f:
            try: log = json.load(f)
            except: log = []
    log.append(entry)
    with open(TASK_LOG, "w") as f:
        json.dump(log[-200:], f, indent=2)
