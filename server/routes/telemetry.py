from fastapi import APIRouter, Depends
from utils.security import verify_token
from core.tools.system import snapshot
import datetime

router = APIRouter(prefix="/stark", tags=["telemetry"])


@router.get("/telemetry", dependencies=[Depends(verify_token)])
def telemetry():
    # snapshot() already guards each psutil call individually (see
    # core/tools/system.py), but wrap the whole call too — belt and
    # suspenders against anything psutil-related failing on Render's
    # sandboxed environment, so this endpoint always returns usable
    # defaults instead of a 500 with no body.
    try:
        s = snapshot()
    except Exception:
        s = {"cpu_percent": 0, "ram_used_pct": 0, "disk_used_pct": 0, "uptime_hours": 0}

    return {
        "cpu": s.get("cpu_percent", 0),
        "ram": s.get("ram_used_pct", 0),
        "disk": s.get("disk_used_pct", 0),
        "timestamp": datetime.datetime.now().isoformat(),
        "uptime_hours": s.get("uptime_hours", 0),
    }
