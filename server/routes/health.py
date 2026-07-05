from fastapi import APIRouter
from core.state import state

router = APIRouter(tags=["health"])

@router.get("/")
def root():
    return {
        "status":      "JARVIS V5 ONLINE",
        "version":     "5.0",
        "state":       state.get("status"),
        "hud":         "/hud",
        "hud_desktop": "/hud/desktop",
        "hud_mobile":  "/hud/mobile",
        "api_docs":    "/docs",
        "health":      "/health",
    }

@router.get("/health")
def health():
    import time
    from server.api import BOOT_TIME
    return {
        "healthy": True,
        "uptime_seconds": int(time.time() - BOOT_TIME),
        "state": state.snapshot(),
    }
