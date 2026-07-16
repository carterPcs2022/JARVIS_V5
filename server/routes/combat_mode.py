"""server/routes/combat_mode.py — combat mode status + trigger history.

Gated behind verify_token since entries include raw message text from
whatever triggered/reviewed a combat-mode event.
"""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["combat-mode"], dependencies=[Depends(verify_token)])


@router.get("/combat_mode/status")
def combat_mode_status():
    from services.combat_mode import combat_mode
    return combat_mode.status()


@router.get("/combat_mode/log")
def combat_mode_log(n: int = 50):
    """Recent engage/disengage events, for reviewing false positives/negatives
    before retuning COMBAT_MODE_CONFIDENCE_THRESHOLD in config/settings.py."""
    from services.audit_log import audit_log
    entries = [
        e for e in audit_log.get_recent(n=max(n, 200))
        if e.get("action") in ("COMBAT_MODE_ENGAGE", "COMBAT_MODE_DISENGAGE")
    ]
    return {"entries": entries[-n:]}
