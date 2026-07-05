"""server/routes/ultimate_brain.py — every reasoning technique from the
"ultimate brain" batch, exposed as opt-in endpoints. None of these are
wired into the default /stark/chat path: several chain 4-8 LLM calls per
invocation (some at paid Anthropic tiers), and wiring them into every
message would multiply the cost/latency of ordinary conversation for a
benefit that mostly matters on hard, deliberate queries — the same
judgment call already applied to Tree of Thought/ReAct/Reflexion/Mixture
of Agents in server/routes/brain_enhancement.py."""
from fastapi import APIRouter, Depends

from utils.security import verify_token

router = APIRouter(prefix="/stark/brain", tags=["ultimate-brain"], dependencies=[Depends(verify_token)])


@router.post("/metacognition")
def brain_metacognition(body: dict):
    from core.metacognition import metacog
    query = body.get("query", "")
    meta = metacog.evaluate_approach(query)
    meta["recommended_tool"] = metacog.choose_reasoning_tool(query, meta)
    return meta


@router.get("/epistemic")
def brain_epistemic(query: str, confidence: int = 75):
    from core.epistemic import epistemic
    return epistemic.calibrate(query, confidence)


@router.get("/working_memory")
def brain_working_memory():
    from core.working_memory import working_mem
    return working_mem.summary()


@router.get("/narrative")
def brain_narrative():
    from core.narrative import narrative
    return narrative.current_arc


@router.post("/debate")
def brain_debate(body: dict):
    from core.structured_debate import debate
    return debate.debate(body.get("proposition", ""), body.get("context", ""))


@router.post("/abductive")
def brain_abductive(body: dict):
    from core.abductive import abductive
    return abductive.best_explanation(body.get("observations", []), body.get("domain", ""))


@router.post("/abductive/debug")
def brain_abductive_debug(body: dict):
    from core.abductive import abductive
    return abductive.debug_system(body.get("symptoms", []), body.get("context", ""))


@router.post("/bayesian")
def brain_bayesian(body: dict):
    from core.bayesian import bayesian
    return bayesian.estimate_probability(body.get("claim", ""), body.get("context", ""))


@router.post("/bayesian/compare")
def brain_bayesian_compare(body: dict):
    from core.bayesian import bayesian
    return bayesian.compare_hypotheses(body.get("hypotheses", []), body.get("evidence", ""))


@router.post("/longterm")
def brain_longterm(body: dict):
    from core.temporal_long import long_term
    return long_term.analyze(body.get("decision", ""), body.get("context", ""))


@router.post("/cumulative")
def brain_cumulative(body: dict):
    from core.cumulative import cumulative
    return cumulative.reason(body.get("query", ""), body.get("context", ""))


@router.post("/graph")
def brain_graph_of_thought(body: dict):
    from core.graph_of_thought import got
    return got.think(body.get("problem", ""), body.get("depth", 2), body.get("breadth", 3))


@router.post("/analogical/transfer")
def brain_analogical_transfer(body: dict):
    from core.analogical import analogical
    return analogical.transfer_from_domain(body.get("problem", ""), body.get("source_domain", ""))


@router.post("/memory/compress")
def brain_memory_compress(body: dict):
    from core.memory import semantic_compress
    return {"compressed": semantic_compress(body.get("memories", []), body.get("target_size", 10))}
