"""server/routes/sandbox.py — self-programming sandbox endpoints.

Every mutating action here (improve/approve/reject/rollback/persist)
requires the master token, not just any bearer token — this is the
endpoint group that can eventually write to real files, so it gets the
same bar as lockdown/coldfire in server/routes/protocols.py.

approve and persist additionally require SANDBOX_APPROVAL_TOKEN — a
second, distinct secret from the master token (see config/settings.py).
Reject and rollback don't: rejecting never touches a real file, and
rollback is a defensive undo of an already-approved change, not a new
grant of write access.
"""
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException
from utils.security import verify_token
from server.routes.protocols import verify_master_only
from config.settings import SANDBOX_APPROVAL_TOKEN

router = APIRouter(prefix="/stark/sandbox", tags=["sandbox"])


def verify_sandbox_approval(x_sandbox_approval_token: str = Header(default="")):
    """Gate for the two actions that make a self-modification real or
    permanent (approve, persist). Deliberately fails CLOSED if
    SANDBOX_APPROVAL_TOKEN isn't configured — every other optional secret
    in this codebase treats "unset" as "this gate doesn't apply," but
    doing that here would defeat the reason this exists: to require
    something beyond the everyday master token, not fall back to it."""
    if not SANDBOX_APPROVAL_TOKEN:
        raise HTTPException(503, "SANDBOX_APPROVAL_TOKEN is not configured — "
                                  "approval/persist is disabled until it's set.")
    if not hmac.compare_digest(x_sandbox_approval_token or "", SANDBOX_APPROVAL_TOKEN):
        raise HTTPException(401, "Invalid or missing X-Sandbox-Approval-Token header.")
    return True


async def verify_iris_confirmation(x_iris_confirm_token: str = Header(default="")):
    """Iris AND-gate for approve/persist, alongside (never instead of)
    verify_sandbox_approval above. Only applies when an iris profile is
    actually enrolled (checked live against the Mac Bridge) — same
    "unset/not-opted-in = gate doesn't apply" convention as
    SANDBOX_APPROVAL_TOKEN's sibling checks elsewhere in this codebase,
    just evaluated dynamically instead of via a static env var, since
    enrollment is itself dynamic state."""
    from core.protocols import consume_iris_confirmation
    from server.routes.iris import iris_profile_enrolled
    if not await iris_profile_enrolled():
        return True
    if not x_iris_confirm_token or not consume_iris_confirmation(x_iris_confirm_token):
        raise HTTPException(403, "Iris verification required — call POST /stark/iris/verify "
                                  "and pass the returned iris_confirm_token as "
                                  "X-Iris-Confirm-Token header.")
    return True


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


@router.post("/approve/{improvement_id}",
             dependencies=[Depends(verify_master_only), Depends(verify_sandbox_approval),
                           Depends(verify_iris_confirmation)])
def sandbox_approve(improvement_id: str):
    """Approve and deploy a queued improvement — locally only, not pushed
    to GitHub. The only path that writes a real file. See
    POST /stark/sandbox/persist/{deployment_id} to make it durable."""
    from core.self_improvement import self_improvement
    return self_improvement.approve_improvement(improvement_id)


@router.post("/persist/{deployment_id}",
             dependencies=[Depends(verify_master_only), Depends(verify_sandbox_approval),
                           Depends(verify_iris_confirmation)])
def sandbox_persist(deployment_id: str):
    """Second, explicit step after approve: commit and push an
    already-deployed change to GitHub so it survives a redeploy. Requires
    the same elevated credential as approve — this is still part of the
    "make this change permanent" action, not a lesser one."""
    from core.self_improvement import self_improvement
    return self_improvement.persist_deployment(deployment_id)


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
