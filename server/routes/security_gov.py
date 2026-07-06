"""server/routes/security_gov.py — two-man rule, zero-knowledge auth,
dead man's switch, canaries, timelock, and steganography verification.
Endpoints for the "government-grade" security batch — see each
services/*.py module's docstring for what's deliberately opt-in-only."""
from fastapi import APIRouter, Depends

from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["security-gov"], dependencies=[Depends(verify_token)])


# ── Two-man rule ───────────────────────────────────────────────────────────────

@router.post("/authorize/initiate")
def authorize_initiate(body: dict):
    from services.two_man_rule import two_man
    return two_man.initiate_action(body.get("action", ""), body.get("token", ""), body.get("reason", ""))


@router.post("/authorize/approve")
def authorize_approve(body: dict):
    from services.two_man_rule import two_man
    return two_man.approve_action(body.get("auth_id", ""), body.get("token", ""))


@router.get("/authorize/pending")
def authorize_pending():
    from services.two_man_rule import two_man
    return two_man.list_pending()


@router.get("/authorize/{auth_id}")
def authorize_status(auth_id: str):
    from services.two_man_rule import two_man
    return {"auth_id": auth_id, "approved": two_man.is_approved(auth_id)}


# ── Zero-knowledge auth ────────────────────────────────────────────────────────

@router.get("/auth/challenge")
def zk_challenge(session_id: str = ""):
    from services.zero_knowledge import zk_auth
    return zk_auth.create_challenge(session_id)


@router.post("/auth/verify")
def zk_verify(body: dict):
    from services.zero_knowledge import zk_auth
    return zk_auth.verify_proof(body.get("session_id", ""), body.get("proof", ""), body.get("secret_hash", ""))


# ── Dead man's switch ───────────────────────────────────────────────────────────

@router.post("/dms/configure")
def dms_configure(body: dict):
    from services.dead_mans_switch import dms
    return dms.configure(
        body.get("check_in_hours", 24), body.get("warning_hours", 12),
        body.get("emergency_contact", ""), body.get("protective_action", "alert"),
    )


@router.post("/dms/checkin")
def dms_checkin():
    from services.dead_mans_switch import dms
    return dms.check_in()


@router.get("/dms/status")
def dms_status():
    from services.dead_mans_switch import dms
    return dms.status()


# ── Canaries ────────────────────────────────────────────────────────────────────

@router.get("/security/canaries")
def security_canaries():
    from services.canary import canary
    return canary.list_canaries()


@router.post("/security/canaries/plant")
def security_canaries_plant():
    from services.canary import canary
    return {"planted": canary.plant_in_memory_files()}


# ── Timelock ────────────────────────────────────────────────────────────────────

@router.get("/security/timelock")
def security_timelock_check(action: str):
    from services.timelock import timelock
    return timelock.check(action)


@router.post("/security/timelock/unlock")
def security_timelock_unlock(body: dict):
    from services.timelock import timelock
    return timelock.emergency_unlock(
        body.get("action", ""), body.get("passphrase", ""), body.get("duration_minutes", 5)
    )



# ── Steganography ──────────────────────────────────────────────────────────────

@router.post("/security/watermark")
def security_watermark(body: dict):
    from services.steganography import stegano
    return {"watermarked": stegano.watermark_response(body.get("text", ""), body.get("session_id", ""))}


@router.post("/security/verify-watermark")
def security_verify_watermark(body: dict):
    from services.steganography import stegano
    return stegano.extract_watermark(body.get("text", ""))
