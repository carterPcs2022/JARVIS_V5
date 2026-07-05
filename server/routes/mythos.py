"""server/routes/mythos.py — Fable 5 model cascade extras: agentic loop,
persistent solver, thinking-trace transparency, and usage/cost reporting.
Agentic loop and persistence are opt-in (real cost/time per call) — not
wired into the default /stark/chat path."""
from fastapi import APIRouter, Depends

from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["mythos"], dependencies=[Depends(verify_token)])


# ── Agentic loop ──────────────────────────────────────────────────────────────

@router.post("/agentic/run")
def agentic_run(body: dict):
    from core.agentic_loop import agentic
    return agentic.run(
        body.get("task", ""), body.get("context", ""),
        body.get("max_iterations", 8),
        body.get("step_tier", "reasoning"), body.get("final_tier", "opus"),
    )


@router.post("/agentic/should-use")
def agentic_should_use(body: dict):
    from core.agentic_loop import agentic
    query = body.get("query", "")
    return {"should_use_agentic": agentic.should_use_agentic(query)}


# ── Persistent solver ──────────────────────────────────────────────────────────

@router.post("/persistence/solve")
def persistence_solve(body: dict):
    from core.persistence import persistent
    return persistent.solve(body.get("problem", ""), body.get("context", ""),
                            body.get("max_attempts", 3))


# ── Thinking transparency ──────────────────────────────────────────────────────

@router.get("/thinking/last")
def thinking_last():
    from core.memory import get_last_thinking
    return get_last_thinking() or {"error": "No thinking trace recorded yet"}


@router.get("/thinking/log")
def thinking_log(n: int = 10):
    from core.memory import get_thinking_log
    return get_thinking_log(n)


# ── Usage / cost reporting ──────────────────────────────────────────────────────

@router.get("/fable/usage")
def fable_usage():
    from core.evolution import fable_usage_report
    return fable_usage_report()


@router.get("/model/usage")
def model_usage():
    """Today's Sonnet/Opus/Fable call counts against their daily caps."""
    from core.llm.router import _get_usage, ANTHROPIC_REGISTRY
    usage = _get_usage()
    return {
        tier: {"used": usage.get(tier, 0), "limit": cfg["daily_limit"], "enabled": cfg["enabled"]}
        for tier, cfg in ANTHROPIC_REGISTRY.items()
    }
