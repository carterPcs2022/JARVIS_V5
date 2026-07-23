"""Protocol 17 scatter/reassemble endpoints.

Scatter previously accepted ANY string as "passphrase" (it's used directly
as a key-derivation input, not compared against a known secret) and only
required a generic verify_token — meaning Pepper/Rhodey-tier tokens, not
just the master token, could trigger it, with zero confirmation step.
Found and fixed after a real incident where this + the generic
core.protocols.run_protocol("scatter") dispatch (also now blocked) were both
reachable with just a valid token. Now mirrors Lockdown/Coldfire's pattern:
master-only auth, plus a two-step Avengers confirmation (submit, get a
token, resubmit the same passphrase + token within the window) before
actually scattering. Reassemble is the recovery action, not the
destructive one, so it keeps master-only auth without the extra
confirmation step — it doesn't need friction against use.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from utils.security import verify_token
from server.routes.protocols import verify_master_only

router = APIRouter(prefix="/stark/scatter", tags=["scatter"])


class ScatterRequest(BaseModel):
    passphrase: str
    confirm_token: str = ""
    iris_token: str = ""


class ReassembleRequest(BaseModel):
    passphrase: str


@router.post("")
async def scatter(req: ScatterRequest, _=Depends(verify_master_only)):
    from core.protocols import (
        request_avengers_confirmation, confirm_avengers,
        consume_iris_confirmation,
    )
    from server.routes.iris import iris_profile_enrolled

    if not req.confirm_token:
        tok = request_avengers_confirmation("scatter", req.passphrase)
        from datetime import datetime
        from services.notifications import critical
        critical("Scatter Protocol requested",
                  f"Requested at {datetime.now().strftime('%H:%M:%S')}. This will "
                  f"disperse your identity across nodes — not easily reversible. "
                  f"Approve via iris scan + confirm token within 10 minutes, or "
                  f"ignore to leave it unexecuted.")
        return {
            "status":          "awaiting_confirmation",
            "confirm_token":   tok,
            "warning":         "Scatter will disperse your identity across nodes. Not easily reversible.",
            "message":         "Send this token back within 10 minutes, with the same passphrase, to confirm.",
            "expires_seconds": 600,
        }

    if not confirm_avengers(req.confirm_token, req.passphrase):
        raise HTTPException(403, "Confirmation failed or expired")

    if await iris_profile_enrolled():
        if not req.iris_token or not consume_iris_confirmation(req.iris_token):
            raise HTTPException(403, "Iris verification required — call POST /stark/iris/verify "
                                      "and pass the returned iris_confirm_token as iris_token.")

    from core.scatter import get_engine
    result = get_engine().scatter(req.passphrase)
    if not result["ok"]:
        raise HTTPException(503, detail=result.get("error", "Scatter failed"))
    return result


@router.get("/status")
async def scatter_status(_=Depends(verify_master_only)):
    from core.scatter import get_engine
    return get_engine().status()


@router.post("/reassemble")
async def reassemble(req: ReassembleRequest, _=Depends(verify_master_only)):
    from core.scatter import get_engine
    result = get_engine().reassemble(req.passphrase)
    if not result["ok"]:
        raise HTTPException(400, detail=result.get("error", "Reassembly failed"))
    return result


@router.get("/nodes")
async def list_nodes(_=Depends(verify_token)):
    from services.scatter_nodes import get_nodes
    nodes = get_nodes()
    return {"nodes": [{"name": n.name, "available": n.available()} for n in nodes]}
