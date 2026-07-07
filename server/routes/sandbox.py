"""server/routes/sandbox.py — self-programming sandbox endpoints.

Every mutating action here (improve/approve/reject/rollback) requires the
master token, not just any bearer token — this is the endpoint group that
can eventually write to real files, so it gets the same bar as
lockdown/coldfire in server/routes/protocols.py.
"""
from fastapi import APIRouter, Depends
from utils.security import verify_token
from server.routes.protocols import verify_master_only

router = APIRouter(prefix="/stark/sandbox", tags=["sandbox"])


@router.get("/analyze", dependencies=[Depends(verify_token)])
def sandbox_analyze():
    """JARVIS analyzes his own code. Read-only."""
    from core.self_analysis import self_analysis
    return self_analysis.analyze_self()


@router.post("/analyze/file", dependencies=[Depends(verify_token)])
def sandbox_analyze_file(body: dict):
    """Analyze a specific allowlisted file. Read-only."""
    from core.self_analysis import self_analysis
    filepath = body.get("filepath", "")
    if not filepath:
        return {"error": "filepath required"}
    return self_analysis.analyze_file(filepath)


@router.get("/bottlenecks", dependencies=[Depends(verify_token)])
def sandbox_bottlenecks():
    """Find performance bottlenecks. Read-only."""
    from core.self_analysis import self_analysis
    return self_analysis.find_bottlenecks()


@router.post("/improve", dependencies=[Depends(verify_master_only)])
def sandbox_improve():
    """Run analyze -> write -> sandbox-test -> queue. Never deploys —
    see /stark/sandbox/approve/{id}."""
    from core.self_improvement import self_improvement
    return self_improvement.run_improvement_cycle()


@router.get("/pending", dependencies=[Depends(verify_token)])
def sandbox_pending():
    """Improvements awaiting approval."""
    from core.self_improvement import self_improvement
    return {"pending": self_improvement.get_pending_approvals()}


@router.post("/approve/{improvement_id}", dependencies=[Depends(verify_master_only)])
def sandbox_approve(improvement_id: str):
    """Approve and deploy a queued improvement. The only path that writes
    a real file."""
    from core.self_improvement import self_improvement
    return self_improvement.approve_improvement(improvement_id)


@router.post("/reject/{improvement_id}", dependencies=[Depends(verify_master_only)])
def sandbox_reject(improvement_id: str):
    """Reject a queued improvement."""
    from core.self_improvement import self_improvement
    return self_improvement.reject_improvement(improvement_id)


@router.get("/history", dependencies=[Depends(verify_token)])
def sandbox_history():
    """Deployment history."""
    from core.sandbox import jarvis_sandbox
    return {"deployments": jarvis_sandbox.get_deployment_history()}


@router.post("/rollback", dependencies=[Depends(verify_master_only)])
def sandbox_rollback(body: dict):
    """Roll back a deployment from its backup."""
    from core.sandbox import jarvis_sandbox
    filepath = body.get("filepath", "")
    backup   = body.get("backup", "")
    if not filepath or not backup:
        return {"error": "filepath and backup required"}
    return jarvis_sandbox.rollback(filepath, backup)
