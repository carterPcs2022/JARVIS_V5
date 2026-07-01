from fastapi import APIRouter
from core.tools.system import snapshot
import datetime

router = APIRouter(prefix="/stark", tags=["telemetry"])

@router.get("/telemetry")
def telemetry():
    s = snapshot()
    return {"cpu": s["cpu_percent"], "ram": s["ram_used_pct"],
            "disk": s["disk_used_pct"], "timestamp": datetime.datetime.now().isoformat(),
            "uptime_hours": s["uptime_hours"]}
