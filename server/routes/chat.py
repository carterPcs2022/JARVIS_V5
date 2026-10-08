"""server/routes/chat.py — Chat route using Brain V2 plus bounded agentic routing."""
import asyncio
import concurrent.futures
from fastapi import APIRouter, Depends, Request
from utils.security import verify_token, rate_limit
from core.brain_v2 import brain

router = APIRouter(prefix="/stark", tags=["chat"])

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-task")
TASK_TIMEOUT_SECONDS = 15
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
        pass

    from services.combat_mode import combat_mode
    if combat_mode.is_engaged():
        from services.combat_staging import try_fast_path
        staged = try_fast_path(msg)
        if staged:
            return staged

    from services.threat_detector import classify as classify_threat
    threat_future = _executor.submit(classify_threat, msg)

    # CognitiveRouter is the single cognitive front door. It preserves
    # Brain V2 for ordinary requests while adding the decision/conscience
    # boundary and the real agent/tool path when appropriate.
    from core.cognitive_router import router as cognitive_router
    future = _executor.submit(asyncio.run, cognitive_router.route_async(msg))

    try:
        result = future.result(timeout=TASK_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        from core.llm.router import chat as llm_chat
        r = llm_chat([{"role": "user", "content": msg}], temperature=0.6, query=msg)
        result = {
            "response": r["content"],
            "model": r.get("model", ""),
            "provider": r.get("provider", ""),
            "latency_ms": TASK_TIMEOUT_SECONDS * 1000,
            "meta": {
                "action": "task",
                "complexity": "unknown",
                "mode": "autonomous_timeout_fallback",
                "was_rewritten": False,
                "issues": [f"Task exceeded {TASK_TIMEOUT_SECONDS}s timeout; served direct response instead"],
            },
        }

    try:
        classification = threat_future.result(timeout=THREAT_CLASSIFY_TIMEOUT_SECONDS)
    except Exception as e:
        from services.threat_detector import classifier_failed_result
        print(f"[Chat] Threat classification unavailable ({e}) — asking a check-in question instead of assuming safe.")
        classification = classifier_failed_result(f"threat_future exception: {e}")

    from services.combat_mode import combat_mode
    outcome = combat_mode.handle_classification(msg, classification)
    if outcome.get("soft_confirm_prompt") and isinstance(result.get("response"), str):
        result["response"] = f"{result['response']}\n\n{outcome['soft_confirm_prompt']}"

    return result
