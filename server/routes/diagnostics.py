from fastapi import APIRouter, Depends
from utils.security import verify_token
from utils.diagnostics import full_diagnostic

router = APIRouter(prefix="/stark", tags=["diagnostics"])

@router.get("/diagnostics", dependencies=[Depends(verify_token)])
def diagnostics():
    return full_diagnostic()

@router.get("/system/config-check", dependencies=[Depends(verify_token)])
def config_check():
    from core.config_validator import validate_config
    return validate_config()

@router.post("/system/cleanup", dependencies=[Depends(verify_token)])
def manual_cleanup():
    """Manual trigger for services.scheduler._cleanup_old_files() — that
    job otherwise only runs on its 3:30am cron schedule, with no way to
    force it (e.g. to free disk space immediately on Render without
    waiting for the next scheduled run)."""
    from services.scheduler import _cleanup_old_files
    _cleanup_old_files()
    return {"status": "cleanup ran"}
