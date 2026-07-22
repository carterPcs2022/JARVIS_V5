"""server/routes/chat.py — Chat route using Brain V2 pipeline."""
import concurrent.futures
from fastapi import APIRouter, Depends, Request
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

# Combat-mode threat classification runs concurrently with the main brain
# call in the same executor, capped at its own short timeout so a slow/down
# Groq call never adds latency to the actual response — on timeout or error
# it's treated as "no threat detected" for this message only.
THREAT_CLASSIFY_TIMEOUT_SECONDS = 2


@router.post("/chat", dependencies=[Depends(verify_token), Depends(rate_limit)])
def chat(body: dict, request: Request):
    msg = body.get("message", "").strip()
    if not msg:
        return {"error": "No message provided"}

    ip = request.client.host if request.client else ""
    try:
        from services.ai_firewall import ai_firewall
        screen = ai_firewall.screen(msg, ip)
        if not screen["allowed"]:
            return {"error": "Request blocked by security system",
                    "threat_type": screen["threat_type"]}
    except Exception:
        pass  # firewall unavailable — fail open rather than block all chat

    # Combat-mode Phase 2 fast path — checked before classification/brain
    # even start, since a hit means skipping both entirely. Cheap in-memory
    # check (dict lookup + substring match), never worth its own executor
    # hop. See services/combat_staging.py.
    from services.combat_mode import combat_mode
    if combat_mode.is_engaged():
        from services.combat_staging import try_fast_path
        staged = try_fast_path(msg)
        if staged:
            return staged

    from services.threat_detector import classify as classify_threat
    threat_future = _executor.submit(classify_threat, msg)

    future = _executor.submit(brain.process_dict, msg)
    try:
        result = future.result(timeout=TASK_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        # Python threads can't be forcibly killed — the abandoned task keeps
        # running to completion in the background and its result is simply
        # discarded. This still unblocks the caller immediately.
        from core.llm.router import chat as llm_chat
        r = llm_chat([{"role": "user", "content": msg}], temperature=0.6, query=msg)
        result = {
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

    try:
        classification = threat_future.result(timeout=THREAT_CLASSIFY_TIMEOUT_SECONDS)
    except Exception as e:
        # Used to set classification=None here, which skipped
        # combat_mode.handle_classification() entirely below — a real
        # emergency message that happened to hit a slow/failed
        # classification got silently treated as "no threat," identically
        # to a genuinely safe message, with zero trace anywhere. This is a
        # personal safety/emergency-detection feature; defaulting an
        # unknown to "safe" is the wrong direction to fail in. Now
        # constructs the same classifier_failed marker classify() itself
        # uses on an internal failure, so combat_mode's check-in logic
        # still runs instead of being skipped a third, silent way.
        from services.threat_detector import classifier_failed_result
        print(f"[Chat] Threat classification unavailable ({e}) — asking a check-in question instead of assuming safe.")
        classification = classifier_failed_result(f"threat_future exception: {e}")

    from services.combat_mode import combat_mode
    outcome = combat_mode.handle_classification(msg, classification)
    if outcome.get("soft_confirm_prompt") and isinstance(result.get("response"), str):
        result["response"] = f"{result['response']}\n\n{outcome['soft_confirm_prompt']}"

    return result
