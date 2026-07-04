"""server/routes/chat.py — Chat route using Brain V2 pipeline."""
import concurrent.futures
from fastapi import APIRouter, Depends
from utils.security import verify_token, rate_limit
from core.brain_v2 import brain

router = APIRouter(prefix="/stark", tags=["chat"])

# Autonomous mode (Planner.create -> mode="autonomous") can chain several
# agent calls sequentially (core.agents.planner_agent.run) and has no
# internal budget of its own — a diagnostic-style query can spiral into a
# 40s+ run. Bound the whole request in a worker thread; if it blows the
# budget, abandon it and answer directly instead of leaving the caller
# hanging.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-task")
TASK_TIMEOUT_SECONDS = 15


@router.post("/chat", dependencies=[Depends(verify_token), Depends(rate_limit)])
def chat(body: dict):
    msg = body.get("message", "").strip()
    if not msg:
        return {"error": "No message provided"}

    future = _executor.submit(brain.process_dict, msg)
    try:
        return future.result(timeout=TASK_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        # Python threads can't be forcibly killed — the abandoned task keeps
        # running to completion in the background and its result is simply
        # discarded. This still unblocks the caller immediately.
        from core.llm.router import chat as llm_chat
        r = llm_chat([{"role": "user", "content": msg}], temperature=0.6, query=msg)
        return {
            "response":   r["content"],
            "model":      r.get("model", ""),
            "provider":   r.get("provider", ""),
            "latency_ms": TASK_TIMEOUT_SECONDS * 1000,
            "meta": {
                "action":     "task",
                "complexity": "unknown",
                "mode":       "autonomous_timeout_fallback",
                "was_rewritten": False,
                "issues":     [f"Task exceeded {TASK_TIMEOUT_SECONDS}s timeout; served direct response instead"],
            },
        }
