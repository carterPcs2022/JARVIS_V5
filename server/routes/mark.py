"""server/routes/mark.py — Mark System routes."""
from fastapi import APIRouter, Depends
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["mark"])

@router.get("/mark", dependencies=[Depends(verify_token)])
def get_current_mark():
    from services.mark_system import mark_system
    return mark_system.current_mark()

@router.get("/mark/history", dependencies=[Depends(verify_token)])
def get_mark_history():
    from services.mark_system import mark_system
    return mark_system.mark_history()

@router.get("/mark/changelog", dependencies=[Depends(verify_token)])
def get_mark_changelog():
    from services.mark_system import mark_system
    return {"changelog": mark_system.mark_changelog()}

@router.post("/mark/upgrade", dependencies=[Depends(verify_token)])
def upgrade_mark(body: dict):
    from services.mark_system import mark_system
    capabilities = body.get("capabilities", [])
    notes = body.get("notes", "")
    return mark_system.upgrade_mark(capabilities, notes)

@router.get("/mark/damage", dependencies=[Depends(verify_token)])
def get_damage_report():
    from services.mark_system import mark_system
    return mark_system.damage_report()
