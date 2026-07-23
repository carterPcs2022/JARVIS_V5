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

@router.api_route("/health", methods=["GET", "HEAD"])
def health():
    import time
    from server.api import BOOT_TIME
    return {
        "healthy": True,
        "uptime_seconds": int(time.time() - BOOT_TIME),
        "state": state.snapshot(),
    }


# Deliberately unauthenticated, same as /health above — an external
# watchdog (UptimeRobot etc.) can't carry a bearer token, and there's
# nothing sensitive in the response (just a timestamp and a job id).
#
# This exists because /health only proves uvicorn is answering requests —
# it stayed green throughout the 2026-07-16 incident where a NameError
# during job registration silently killed services.scheduler's entire
# BackgroundScheduler on every boot. That failure mode needs its own
# check: is the scheduler itself actually still cycling through jobs.
STALE_AFTER_SECONDS = 600  # p25_snap_monitor alone runs every 60s, so a
                           # healthy scheduler heartbeats well under this


@router.api_route("/stark/scheduler/heartbeat", methods=["GET", "HEAD"])
def scheduler_heartbeat():
    from datetime import datetime
    from fastapi.responses import JSONResponse
    from services.scheduler import last_heartbeat

    hb = last_heartbeat()
    ts = hb.get("ts")

    if ts is None:
        return JSONResponse({"healthy": False, "reason": "no job has run yet"}, status_code=503)

    age_seconds = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    healthy = age_seconds < STALE_AFTER_SECONDS

    body = {
        "healthy": healthy,
        "last_job_id": hb.get("job_id"),
        "last_job_outcome": hb.get("outcome"),
        "last_job_at": ts,
        "age_seconds": round(age_seconds, 1),
    }
    return JSONResponse(body, status_code=200 if healthy else 503)
