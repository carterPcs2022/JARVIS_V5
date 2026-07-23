"""server/routes/protocols.py — Stark Protocol endpoints."""
import hmac
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.security import verify_token, bearer, _record_failed_auth_safe
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/stark", tags=["protocols"])


# ── Helper: Pepper / Rhodey token auth ───────────────────────────────────────
# All token comparisons here use hmac.compare_digest instead of == —
# constant-time, prevents inferring a token's leading characters from
# response timing.

def _is_pepper(creds) -> bool:
    token = os.getenv("PEPPER_TOKEN", "")
    return bool(token and creds and hmac.compare_digest(creds.credentials, token))


def _is_rhodey(creds) -> bool:
    token = os.getenv("RHODEY_TOKEN", "")
    return bool(token and creds and hmac.compare_digest(creds.credentials, token))


def verify_any_read_token(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """Accept master token, Pepper token, or Rhodey token."""
    from config.settings import API_TOKEN
    from utils.security import _reject_if_blocked
    _reject_if_blocked(request.client.host if request.client else "unknown")
    if not API_TOKEN:
        return "master"
    if creds:
        if hmac.compare_digest(creds.credentials, API_TOKEN): return "master"
        if _is_pepper(creds):                   return "pepper"
        if _is_rhodey(creds):                   return "rhodey"
    _record_failed_auth_safe(request.client.host if request.client else "unknown")
    raise HTTPException(401, "Unauthorized")


def verify_master_only(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """Only master token."""
    from config.settings import API_TOKEN
    from utils.security import _reject_if_blocked
    _reject_if_blocked(request.client.host if request.client else "unknown")
    if not API_TOKEN:
        return True
    if creds and hmac.compare_digest(creds.credentials, API_TOKEN):
        return True
    # Guards the most sensitive routes (lockdown, coldfire, sandbox
    # approve/persist) — a failed attempt here is more significant than
    # an ordinary verify_token() 401, but it feeds the same brute-force
    # counter (5+ failures/5min from one IP = a real BRUTE_FORCE threat),
    # not a separate one, so a mixed pattern of failures across regular
    # and master-only routes from the same IP still adds up correctly.
    _record_failed_auth_safe(request.client.host if request.client else "unknown")
    raise HTTPException(401, "Master token required")


# ── Protocol status ───────────────────────────────────────────────────────────

@router.get("/protocols", dependencies=[Depends(verify_token)])
def get_protocols():
    from core.protocols import protocol_status
    return protocol_status()


# ── Protocol 11: Integrity ────────────────────────────────────────────────────

@router.get("/integrity", dependencies=[Depends(verify_token)])
def integrity():
    from core.protocols import integrity_check_startup, integrity_update_baseline
    return integrity_check_startup()


@router.post("/integrity/baseline", dependencies=[Depends(verify_master_only)])
def update_baseline():
    from core.protocols import integrity_update_baseline
    return integrity_update_baseline()


# ── Protocol 3: Lockdown ──────────────────────────────────────────────────────

@router.post("/lockdown", dependencies=[Depends(verify_master_only)])
async def lockdown(body: dict):
    """
    Activate lockdown. Requires Avengers Protocol (passphrase in body).
    POST {"passphrase": "...", "confirm_token": "..."} — or first call
    returns a token, second call with that token + passphrase confirms.

    confirm_avengers() is a GENERIC two-step timing confirmation shared
    by multiple protocols (lockdown here, coldfire below) — it only
    proves the same string was submitted twice within the 60s window,
    never that it's any particular real secret. Coldfire is safe because
    core.protocols.coldfire() independently re-checks the passphrase
    against COLDFIRE_PASSPHRASE before doing anything destructive.
    activate_lockdown() had no equivalent check of its own — confirmed
    live, lockdown activated with the arbitrary passphrase "banana123".
    The check below closes that gap the same way coldfire already closes
    it: validate against the real secret here, in addition to (not
    instead of) the generic two-step confirmation.

    Iris AND-gate: if an iris profile is actually enrolled (checked live
    against the Mac Bridge, not a static flag), the second call must also
    include a fresh "iris_token" obtained from a successful
    POST /stark/iris/verify — alongside, never instead of, the passphrase
    above. If nothing is enrolled, this leg doesn't apply (same "unset
    secret = gate doesn't apply" convention used everywhere else in this
    file), so lockdown never becomes unreachable for anyone who hasn't
    opted into iris.
    """
    import hmac
    from config.settings import AVENGERS_PASSPHRASE
    from core.protocols import (
        activate_lockdown, request_avengers_confirmation, confirm_avengers,
        consume_iris_confirmation,
    )
    from server.routes.iris import iris_profile_enrolled
    passphrase = body.get("passphrase", "")
    token      = body.get("confirm_token", "")

    if not passphrase:
        return {"error": "passphrase required"}

    if not token:
        # First call — issue confirmation token and push a real notification
        # with real details, so approving isn't a blind guess at what's
        # being requested.
        tok = request_avengers_confirmation("lockdown", passphrase)
        from datetime import datetime
        from services.notifications import critical
        critical("Suit Lockdown requested",
                  f"Requested at {datetime.now().strftime('%H:%M:%S')}. This will "
                  f"restrict JARVIS's API access. Approve via iris scan + confirm "
                  f"token within 10 minutes, or ignore to leave it unexecuted.")
        return {
            "status":          "awaiting_confirmation",
            "confirm_token":   tok,
            "message":         "Send this token back within 10 minutes to confirm lockdown.",
            "expires_seconds": 600,
        }

    # Second call — confirm and execute
    if not confirm_avengers(token, passphrase):
        raise HTTPException(403, "Confirmation failed or expired")

    if not AVENGERS_PASSPHRASE or not hmac.compare_digest(passphrase, AVENGERS_PASSPHRASE):
        raise HTTPException(403, "Invalid passphrase")

    if await iris_profile_enrolled():
        iris_token = body.get("iris_token", "")
        if not iris_token or not consume_iris_confirmation(iris_token):
            raise HTTPException(403, "Iris verification required — call POST /stark/iris/verify "
                                      "and pass the returned iris_confirm_token as iris_token.")

    return activate_lockdown(body.get("reason", "Manual lockdown"))


@router.post("/lockdown/lift", dependencies=[Depends(verify_master_only)])
def lift_lockdown():
    from core.protocols import deactivate_lockdown
    return deactivate_lockdown()


# ── Protocol 6: Coldfire ──────────────────────────────────────────────────────

@router.post("/coldfire", dependencies=[Depends(verify_master_only)])
async def coldfire(body: dict):
    """
    Wipe all sensitive data. Requires:
    1. COLDFIRE_PASSPHRASE env var set
    2. body: {"passphrase": "...", "confirm_token": "..."}
    3. Avengers Protocol double-confirmation
    4. Iris AND-gate (same convention as lockdown): if a profile is
       enrolled, the second call must also carry a fresh iris_token from
       POST /stark/iris/verify. Previously missing here — Coldfire had the
       passphrase + two-step confirm but no iris leg, unlike Lockdown.
    """
    from core.protocols import (
        coldfire as do_coldfire,
        request_avengers_confirmation, confirm_avengers,
        consume_iris_confirmation,
    )
    from server.routes.iris import iris_profile_enrolled
    passphrase = body.get("passphrase", "")
    token      = body.get("confirm_token", "")

    if not passphrase:
        return {"error": "passphrase required"}

    if not token:
        tok = request_avengers_confirmation("coldfire", passphrase)
        from datetime import datetime
        from services.notifications import critical
        critical("Coldfire Protocol requested",
                  f"Requested at {datetime.now().strftime('%H:%M:%S')}. This will "
                  f"WIPE all sensitive data — irreversible. Approve via iris scan "
                  f"+ confirm token within 10 minutes, or ignore to leave it unexecuted.")
        return {
            "status":        "awaiting_confirmation",
            "confirm_token": tok,
            "warning":       "⚠ Coldfire will wipe ALL sensitive data. Irreversible.",
            "expires_seconds": 600,
        }

    if not confirm_avengers(token, passphrase):
        raise HTTPException(403, "Confirmation failed or expired")

    if await iris_profile_enrolled():
        iris_token = body.get("iris_token", "")
        if not iris_token or not consume_iris_confirmation(iris_token):
            raise HTTPException(403, "Iris verification required — call POST /stark/iris/verify "
                                      "and pass the returned iris_confirm_token as iris_token.")

    return do_coldfire(passphrase)


# ── Protocol 16: Endgame ──────────────────────────────────────────────────────

@router.get("/endgame/checkpoints", dependencies=[Depends(verify_token)])
def endgame_checkpoints():
    from core.protocols import endgame_list
    return {"checkpoints": endgame_list()}


@router.post("/endgame/snapshot", dependencies=[Depends(verify_master_only)])
def force_snapshot():
    from core.protocols import endgame_snapshot
    return endgame_snapshot()


@router.get("/restore", dependencies=[Depends(verify_master_only)])
def restore(checkpoint: int = 0):
    from core.protocols import endgame_restore
    return endgame_restore(checkpoint)


# ── Protocol 5 & 10: Pepper / Rhodey status ───────────────────────────────────

@router.get("/access/status")
def access_status(role: str = Depends(verify_any_read_token)):
    """Returns what the caller can see based on their token role."""
    from core.state import state
    from services.sentinel import summary as threat_summary

    if role == "rhodey":
        # Emergency read-only: status + alerts only
        return {
            "role":    "rhodey",
            "status":  state.snapshot(),
            "threats": threat_summary(),
        }

    if role == "pepper":
        # Trusted read-only: status + health, no threats
        return {
            "role":   "pepper",
            "status": state.snapshot(),
        }

    # Master
    return {"role": "master", "status": state.snapshot()}


# ── Protocol 7: Override log ──────────────────────────────────────────────────

@router.get("/overrides", dependencies=[Depends(verify_token)])
def overrides():
    from core.protocols import _load_overrides
    return _load_overrides()


@router.post("/override/confirm", dependencies=[Depends(verify_token)])
def confirm_override(body: dict):
    """User explicitly confirms a bodyguard-flagged action."""
    from core.protocols import record_override
    category = body.get("category", "unknown")
    count    = record_override(category)
    return {"category": category, "override_count": count,
            "message": "Override recorded. Proceed with caution."}


# ── Protocol 15: Avengers — generic confirmation ──────────────────────────────

@router.post("/confirm", dependencies=[Depends(verify_master_only)])
def avengers_confirm(body: dict):
    """Check a pending Avengers confirmation token."""
    from core.protocols import confirm_avengers
    ok = confirm_avengers(body.get("token",""), body.get("passphrase",""))
    return {"confirmed": ok}


# ── Protocol log ──────────────────────────────────────────────────────────────

@router.get("/protocols/log", dependencies=[Depends(verify_token)])
def protocol_log():
    from core.protocols import _load_json, _PROTOCOL_LOG
    return {"events": _load_json(_PROTOCOL_LOG, list)[-100:]}


# ── Generic run-by-number dispatch ────────────────────────────────────────────

@router.post("/protocols/run/{number}", dependencies=[Depends(verify_master_only)])
def run_protocol_by_number(number: int, body: dict | None = None):
    """Run any protocol listed in core.protocols.PROTOCOL_MAP by number."""
    from core.protocols import run_protocol
    return run_protocol(number, body or {})
