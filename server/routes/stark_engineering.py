"""STARK Engineering Mode — bounded code intelligence surface.

Read/inspect and verify candidate changes through the existing coding engine.
This router deliberately stops before applying or deploying changes.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.security import verify_token

router = APIRouter(prefix="/stark/engineering", tags=["stark-engineering"], dependencies=[Depends(verify_token)])


@router.get("/status")
def engineering_status():
    from core.system_health import snapshot
    health = snapshot()
    component = next((c for c in health.get("components", []) if c.get("name") == "ENGINEERING"), None)
    return {
        "mode": "ENGINEERING",
        "status": (component or {}).get("status", "standby"),
        "approval_required": True,
        "deployment_enabled": False,
        "workflow": ["inspect", "propose", "validate", "smoke_test", "approve", "apply", "persist"],
    }


@router.post("/inspect")
def engineering_inspect(body: dict):
    filepath = (body.get("filepath") or "").strip()
    objective = (body.get("objective") or "").strip()
    if not filepath:
        raise HTTPException(400, "filepath required")
    from core.coding_engine import CodeTask, coding_engine
    return coding_engine.inspect(CodeTask(filepath=filepath, objective=objective))


@router.post("/build")
def engineering_build(body: dict):
    filepath = (body.get("filepath") or "").strip()
    objective = (body.get("objective") or "").strip()
    reason = (body.get("reason") or "").strip()
    if not filepath or not objective:
        raise HTTPException(400, "filepath and objective required")
    from core.coding_engine import CodeTask, coding_engine
    return coding_engine.run(CodeTask(filepath=filepath, objective=objective, reason=reason))
