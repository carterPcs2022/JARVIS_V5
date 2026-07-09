"""server/routes/military.py — endpoints for the military-grade systems
(OODA, DEFCON, Gold Codes, EMCON, BDA, House Party) and the MCU-framed
scenario/evacuation tools. All opt-in / on-demand, gated the same as every
other /stark route."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["military"], dependencies=[Depends(verify_token)])


# ── OODA ─────────────────────────────────────────────────────────────────────

@router.post("/ooda")
def ooda_run(body: dict):
    from core.ooda import ooda
    return ooda.run(body.get("situation", ""), body.get("context", ""))


@router.post("/ooda/rapid")
def ooda_rapid(body: dict):
    from core.ooda import ooda
    return {"result": ooda.rapid_ooda(body.get("situation", ""))}


# ── DEFCON ───────────────────────────────────────────────────────────────────

@router.get("/defcon")
def defcon_status():
    from services.defcon import defcon
    return defcon.status()


@router.post("/defcon/set")
def defcon_set(body: dict, gold_code: str = ""):
    from services.gold_codes import gold_codes
    if not gold_codes.verify(gold_code):
        return {"error": "Invalid Gold Code"}
    from services.defcon import defcon
    return defcon.set(body.get("level", 5), body.get("reason", ""))


@router.post("/defcon/assess")
def defcon_assess():
    from services.defcon import defcon
    return {"level": defcon.auto_assess()}


# ── Gold Codes ───────────────────────────────────────────────────────────────

@router.get("/gold-codes/setup")
def gold_codes_setup():
    from services.gold_codes import gold_codes
    return {"setup_uri": gold_codes.get_setup_uri(), "configured": bool(gold_codes.get_setup_uri())}


# ── EMCON ────────────────────────────────────────────────────────────────────

@router.get("/emcon")
def emcon_status():
    from services.emcon import emcon
    return emcon.status()


@router.post("/emcon/activate")
def emcon_activate(body: dict):
    from services.emcon import emcon
    return emcon.activate(body.get("level", 2), body.get("reason", ""))


@router.post("/emcon/deactivate")
def emcon_deactivate():
    from services.emcon import emcon
    return emcon.deactivate()


# ── BDA ──────────────────────────────────────────────────────────────────────

@router.post("/bda/assess")
def bda_assess(body: dict):
    from services.bda import bda
    return bda.assess(body.get("incident", ""), body.get("threat_type", ""),
                      body.get("affected", []), body.get("tier", "standard"))


@router.get("/bda/pending")
def bda_pending():
    from services.bda import bda
    return {"pending": bda.pending_remediation()}


# ── House Party Protocol ─────────────────────────────────────────────────────

@router.post("/protocols/house_party")
def house_party_activate():
    from core.house_party import house_party
    return house_party.activate()


# ── Scenario engine (14M futures framing) ────────────────────────────────────

@router.post("/scenarios/futures")
def scenarios_futures(body: dict):
    from core.scenario_engine import scenario_engine
    return scenario_engine.analyze_futures(body.get("situation", ""), body.get("n_scenarios", 10))


# ── Sokovia Protocol ─────────────────────────────────────────────────────────

@router.post("/sokovia/evacuation")
def sokovia_evacuation(body: dict):
    from core.sokovia import sokovia
    return sokovia.evacuation_analysis(body.get("situation", ""), body.get("location", ""),
                                       body.get("population", 0))


@router.post("/sokovia/safe-action")
def sokovia_safe_action(body: dict):
    from core.sokovia import sokovia
    return sokovia.calculate_safe_action(body.get("action", ""), body.get("constraints", []))
