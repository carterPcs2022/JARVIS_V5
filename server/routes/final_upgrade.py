"""server/routes/final_upgrade.py — 10/10 upgrade: fine-tuning, active
learning, predictive intelligence, domain expertise, neuro mirroring, and
Tony Stark suit capabilities."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["final-upgrade"], dependencies=[Depends(verify_token)])


# ── Fine-tuning ────────────────────────────────────────────────────────────────

@router.post("/train")
def train():
    """Triggers the full fine-tune pipeline — can take several minutes
    (invokes `ollama create`, which builds a model layer)."""
    from services.fine_tuning import fine_tuner
    return fine_tuner.build_personal_model()


@router.get("/train/status")
def train_status():
    from services.fine_tuning import FINETUNE_LOG
    import json
    if not FINETUNE_LOG.exists():
        return {"builds": []}
    return {"builds": json.loads(FINETUNE_LOG.read_text())}


@router.get("/train/data")
def train_data():
    from services.fine_tuning import fine_tuner
    return fine_tuner.prepare_training_data()


# ── Active learning ────────────────────────────────────────────────────────────

@router.post("/feedback")
def feedback(body: dict):
    from core.active_learning import learner
    return learner.record_feedback(body.get("response_id", ""), body.get("rating", 3), body.get("comment", ""))


@router.post("/correct")
def correct(body: dict):
    from core.active_learning import learner
    return learner.record_correction(body.get("query", ""), body.get("wrong", ""),
                                     body.get("correct", ""), body.get("source", "user"))


@router.get("/learning/report")
def learning_report():
    from core.active_learning import learner, CORRECTIONS_FILE, FEEDBACK_FILE
    return {
        "corrections": len(learner._load(CORRECTIONS_FILE)),
        "feedback_items": len(learner._load(FEEDBACK_FILE)),
    }


# ── Prediction ─────────────────────────────────────────────────────────────────

@router.get("/predict/next")
def predict_next(last_query: str = ""):
    from services.predictor import predict_next_query
    return {"predicted": predict_next_query(last_query)}


@router.get("/predict/patterns")
def predict_patterns():
    from services.predictor import analyze_patterns
    return analyze_patterns()


@router.post("/simulate")
def simulate(body: dict):
    from services.predictor import run_simulation
    return run_simulation(body.get("scenario", ""), body.get("variables"), body.get("time_horizon", "1 week"))


# ── Domain expertise ───────────────────────────────────────────────────────────

@router.get("/domains")
def domains_list():
    from core.domain_expert import domain_expert
    return domain_expert.list_domains()


@router.post("/domains")
def domains_register(body: dict):
    from core.domain_expert import domain_expert
    return domain_expert.register_domain(
        body.get("name", ""), body.get("description", ""), body.get("key_files"),
        body.get("key_concepts"), body.get("specialized_tools"),
    )


@router.get("/domains/{name}")
def domains_get(name: str):
    from core.domain_expert import domain_expert
    domain = domain_expert.DOMAINS.get(name.lower())
    return domain or {"error": "Domain not found"}


# ── Neuro profile ──────────────────────────────────────────────────────────────

@router.get("/neuro")
def neuro_get():
    from core.neuro_mirror import neuro
    return neuro.profile


@router.post("/neuro/analyze")
def neuro_analyze():
    from core.neuro_mirror import neuro
    from core.memory import _load
    from config.settings import CONVERSATIONS_FILE
    convs = _load(CONVERSATIONS_FILE) or []
    return neuro.analyze_thinking_style(convs)


# ── Suit ───────────────────────────────────────────────────────────────────────

@router.get("/suit/status")
def suit_status():
    from services.suit_diagnostics import suit_status_report
    return {"status": suit_status_report()}


@router.get("/suit/full")
def suit_full():
    from services.suit_diagnostics import suit_status_full
    return suit_status_full()


@router.post("/suit/translate")
def suit_translate(body: dict):
    from services.comms import instant_translate
    return instant_translate(body.get("text", ""), body.get("from_lang", "auto"), body.get("to_lang", "en"))


@router.post("/suit/calculate")
def suit_calculate(body: dict):
    from core.tools.system import run_calculation
    return run_calculation(body.get("expression", ""))


@router.post("/suit/simulate")
def suit_simulate(body: dict):
    from services.predictor import run_simulation
    return run_simulation(body.get("scenario", ""), body.get("variables"), body.get("time_horizon", "1 week"))


@router.post("/suit/identify")
def suit_identify(body: dict):
    from services.vision import identify_person_from_image
    return identify_person_from_image(body.get("image_path", ""))


@router.post("/suit/network-audit")
def suit_network_audit():
    from services.network_intel import analyze_own_network_security
    return analyze_own_network_security()


@router.post("/suit/threat-analysis")
def suit_threat_analysis(body: dict):
    from services.sentinel import analyze_threat
    return analyze_threat(body.get("threat_data", {}))


@router.post("/suit/pushback")
def suit_pushback(body: dict):
    """"Should JARVIS push back on this?" — on-demand judgment call, one LLM call."""
    from core.brain_v2 import Reasoner, Executor
    intent = Reasoner().analyze(body.get("request", ""))
    message = Executor().check_for_pushback(intent)
    return {"should_pushback": message is not None, "message": message}
