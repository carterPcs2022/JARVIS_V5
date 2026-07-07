"""server/routes/model_updater.py — model self-update status/trigger endpoints."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["model-updater"], dependencies=[Depends(verify_token)])


@router.get("/models/status")
def models_status():
    """Current model registry and recent update history."""
    from services.model_updater import model_updater
    return model_updater.get_status()


@router.post("/models/check")
def models_check():
    """Force an immediate check-and-apply cycle now."""
    from services.model_updater import model_updater
    return model_updater.force_check_now()


@router.get("/models/log")
def models_log():
    """Full history of applied model updates."""
    import json
    from services.model_updater import UPDATE_LOG_FILE
    log = []
    if UPDATE_LOG_FILE.exists():
        try:
            log = json.loads(UPDATE_LOG_FILE.read_text())
        except Exception:
            log = []
    return {"updates": log}
