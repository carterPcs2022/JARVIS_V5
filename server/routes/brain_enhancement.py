"""server/routes/brain_enhancement.py — Advanced reasoning techniques and
six-type memory system. All routes here are opt-in / on-demand — none of
this is auto-triggered by regular chat, since most of it costs multiple
LLM calls per invocation. Use these when you explicitly want JARVIS to
think harder about something specific."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["brain-enhancement"], dependencies=[Depends(verify_token)])


# ── Tool calling ───────────────────────────────────────────────────────────────

@router.post("/tools/chat")
def tools_chat(body: dict):
    from core.tool_calling import think_with_tools
    return think_with_tools(body.get("message", ""), body.get("context", ""))


# ── Master orchestrator ───────────────────────────────────────────────────────

@router.post("/orchestrate")
def orchestrate(body: dict):
    """Runs the full reasoning-technique-selection pipeline — several LLM
    calls, several seconds. Use for genuinely hard questions, not routine chat."""
    from core.orchestrator import orchestrator
    return orchestrator.process(body.get("message", ""), body.get("context", ""))


# ── Individual reasoning techniques ───────────────────────────────────────────

@router.post("/reasoning/tot")
def reasoning_tot(body: dict):
    from core.tree_of_thought import tot
    return tot.think(body.get("problem", ""), body.get("n_branches", 3),
                     body.get("depth", 2), body.get("context", ""))


@router.post("/reasoning/react")
def reasoning_react(body: dict):
    from core.react import react
    return react.reason_and_act(body.get("query", ""), body.get("context", ""))


@router.post("/reasoning/self-consistency")
def reasoning_self_consistency(body: dict):
    from core.self_consistency import sc
    return sc.answer(body.get("query", ""), body.get("context", ""), body.get("n_samples", 3))


@router.post("/reasoning/moa")
def reasoning_moa(body: dict):
    import asyncio
    from core.multi_agent import mixture_of_agents
    return asyncio.run(mixture_of_agents(body.get("query", ""), body.get("context", "")))


@router.post("/reasoning/causal")
def reasoning_causal(body: dict):
    from core.causal_reasoning import causal
    return causal.analyze_causation(body.get("situation", ""))


@router.post("/reasoning/counterfactual")
def reasoning_counterfactual(body: dict):
    from core.causal_reasoning import causal
    return causal.counterfactual(body.get("situation", ""), body.get("alternative", ""))


@router.post("/reasoning/temporal")
def reasoning_temporal(body: dict):
    from core.temporal_reasoning import temporal
    return temporal.parse_temporal_reference(body.get("text", ""))


@router.post("/reasoning/adversarial")
def reasoning_adversarial(body: dict):
    from core.reflection import adversarial_check
    return adversarial_check(body.get("query", ""), body.get("response", ""))


@router.post("/reasoning/verify")
def reasoning_verify(body: dict):
    from core.reasoning import reason_and_verify
    return reason_and_verify(body.get("question", ""), body.get("context", ""))


@router.post("/reasoning/ensemble")
def reasoning_ensemble(body: dict):
    """core/ensemble.py — was complete and importable but had no route
    anywhere, unlike its sibling reasoning techniques above. Multi-sample
    reasoning with confidence weighting; costs n+2 LLM calls (n samples,
    a score per sample, one synthesis), same "opt-in, not auto-triggered"
    convention as the rest of this file."""
    from core.ensemble import ensemble
    return ensemble.reason(body.get("query", ""), body.get("context", ""), body.get("n", 3))


@router.post("/reasoning/hierarchical-planning")
def reasoning_hierarchical_planning(body: dict):
    """core/hierarchical_planning.py — same situation as ensemble above:
    complete, never had a route. Breaks a goal down from vision through
    next physical action."""
    from core.hierarchical_planning import hierarchical
    return hierarchical.plan(body.get("goal", ""), body.get("depth", 4))


# ── Reflexion (learned lessons) ───────────────────────────────────────────────

@router.post("/reflexion/evaluate")
def reflexion_evaluate(body: dict):
    from core.reflexion import reflexion
    return reflexion.evaluate_response(body.get("query", ""), body.get("response", ""), body.get("outcome", "unknown"))


@router.get("/reflexion/lessons")
def reflexion_lessons(q: str = ""):
    from core.reflexion import reflexion
    return {"lessons": reflexion.get_relevant_lessons(q) if q else reflexion._load()}


# ── Six-type memory system ────────────────────────────────────────────────────

@router.post("/memory/episode")
def memory_store_episode(body: dict):
    from core.memory import store_episode
    return store_episode(body.get("event", ""), body.get("importance", 5),
                         body.get("emotions"), body.get("people"), body.get("tags"))


@router.get("/memory/episodes")
def memory_recall_episodes(q: str, k: int = 3):
    from core.memory import recall_episodes
    return recall_episodes(q, k)


@router.post("/memory/fact")
def memory_store_fact(body: dict):
    from core.memory import store_fact
    return store_fact(body.get("fact", ""), body.get("confidence", 0.9),
                      body.get("source", "manual"), body.get("category", "general"))


@router.get("/memory/facts/search")
def memory_recall_facts(q: str, k: int = 5):
    """Was registered at GET /memory/facts — collided with (and was
    silently shadowed by, since server/routes/memory.py's bulk-export
    /memory/facts is registered first in server/api.py) the endpoint
    FRIDAY's training sync uses to pull the full facts list. Nothing
    currently calls this exact path with a `q` param (checked), so
    renaming to disambiguate is safe rather than actually changing
    reachable behavior for anyone."""
    from core.memory import recall_facts
    return recall_facts(q, k)


@router.post("/memory/procedure")
def memory_store_procedure(body: dict):
    from core.memory import store_procedure
    return store_procedure(body.get("task", ""), body.get("steps", []), body.get("success_rate", 1.0))


@router.get("/memory/procedure")
def memory_recall_procedure(task: str):
    from core.memory import recall_procedure
    result = recall_procedure(task)
    return result or {"error": "No known procedure found"}


@router.post("/memory/emotional")
def memory_store_emotional(body: dict):
    from core.memory import store_emotional_memory
    return store_emotional_memory(body.get("topic", ""), body.get("emotion", ""),
                                  body.get("intensity", 5), body.get("context", ""))


@router.post("/memory/remember-to")
def memory_remember_to(body: dict):
    from core.memory import remember_to
    return remember_to(body.get("task", ""), body.get("when"), body.get("trigger"), body.get("priority", 5))


@router.get("/memory/reminders")
def memory_reminders():
    from core.memory import get_pending_reminders
    return get_pending_reminders()


@router.get("/memory/universal-recall")
def memory_universal_recall(q: str, k: int = 3):
    from core.memory import universal_recall
    return {"context": universal_recall(q, k)}
