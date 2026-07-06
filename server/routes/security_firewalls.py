"""server/routes/security_firewalls.py — AI firewall, circuit breaker,
immutable audit log, egress filter, cryptographic state machine, and suit
security endpoints.

Deliberately not included from the original request: a standalone
"deception network" (already covered by GET /stark/security/honeypot in
security_max.py — see services/honeypot.py) and a plain egress request log
(egress redaction reuses core.protocols.shield, whose own redaction log is
exposed below)."""
from fastapi import APIRouter, Depends, Body

from utils.security import verify_token

router = APIRouter(prefix="/stark/security", tags=["security-firewalls"], dependencies=[Depends(verify_token)])
suit_router = APIRouter(prefix="/stark/suit", tags=["suit-security"], dependencies=[Depends(verify_token)])


@router.get("/firewall/stats")
def firewall_stats():
    from services.ai_firewall import ai_firewall
    return ai_firewall.stats()


@router.get("/circuit/dashboard")
def circuit_dashboard():
    from services.circuit_breaker import cb
    return cb.dashboard()


@router.get("/audit/recent")
def audit_recent(n: int = 20):
    from services.audit_log import audit_log
    return audit_log.get_recent(n)


@router.get("/audit/verify")
def audit_verify():
    from services.audit_log import audit_log
    return audit_log.verify_chain()


@router.get("/egress/log")
def egress_log():
    """core.protocols.shield's redaction log — egress_filter.py reuses
    Shield's patterns rather than keeping a second one, so this is the
    same log the input-side shielding writes to."""
    from core.protocols import _P26_REDACT_LOG, _load_json
    return {"redactions": _load_json(_P26_REDACT_LOG, list)[-50:]}


@router.get("/state")
def get_state():
    from services.state_machine import state_machine
    return {"state": state_machine.get_state(), "history": state_machine.get_history()}


@router.post("/state/transition")
def transition_state(body: dict = Body(...)):
    from services.state_machine import state_machine, JarvisState
    try:
        target = JarvisState(body.get("target", ""))
    except ValueError:
        return {"success": False, "reason": f"Unknown state: {body.get('target')}"}
    return state_machine.transition(target, body.get("auth_token", ""))


@suit_router.get("/neural_profile")
def neural_profile():
    from services.suit_security import suit_security
    return suit_security.get_neural_profile()


@suit_router.get("/biometric_baseline")
def biometric_baseline():
    from services.suit_security import suit_security
    return suit_security._load_biometric()


@suit_router.post("/biometric_update")
def biometric_update(body: dict = Body(...)):
    from services.suit_security import suit_security
    return suit_security.update_biometric_baseline(
        heart_rate=body.get("heart_rate", 0),
        hrv=body.get("hrv", 0),
        blood_oxygen=body.get("blood_oxygen", 0),
        voice_pattern=body.get("voice_pattern", ""),
    )


@suit_router.post("/biometric_verify")
def biometric_verify(body: dict = Body(...)):
    from services.suit_security import suit_security
    return suit_security.verify_biometrics(
        heart_rate=body.get("heart_rate", 0),
        hrv=body.get("hrv", 0),
    )
