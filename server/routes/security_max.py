"""server/routes/security_max.py — self-audit, behavioral/adaptive-
ratelimit visibility, honeypot management, threat intel, and the red team
exercise. See services/self_audit.py, services/behavioral_security.py,
services/adaptive_ratelimit.py docstrings for what's deliberately NOT
auto-wired (and why) in this batch."""
from fastapi import APIRouter, Depends, HTTPException

from utils.security import verify_token

router = APIRouter(prefix="/stark/security", tags=["security-max"], dependencies=[Depends(verify_token)])


@router.post("/audit")
def security_audit_run():
    from services.self_audit import audit
    return audit.full_audit()


@router.get("/audit/last")
def security_audit_last():
    from services.self_audit import audit
    return audit.last_audit() or {"error": "No audit has run yet"}


@router.post("/audit/secrets")
def security_scan_secrets():
    from services.self_audit import audit
    return {"findings": audit.scan_for_secrets()}


@router.post("/redteam")
def security_redteam_run():
    from services.red_team import red_team
    return red_team.run_exercise()


@router.get("/redteam/last")
def security_redteam_last():
    from services.red_team import red_team
    return red_team.last_report() or {"error": "No red team exercise has run yet"}


@router.get("/honeypot")
def security_honeypot_log():
    from services.honeypot import honeypot
    return honeypot.log_summary()


@router.get("/behavioral")
def security_behavioral_summary():
    from services.behavioral_security import behavioral
    return behavioral.threat_summary()


@router.get("/behavioral/{ip}")
def security_behavioral_ip(ip: str):
    from services.behavioral_security import behavioral
    return behavioral.get_risk_score(ip)


@router.get("/blocklist")
def security_blocklist():
    from services.honeypot import honeypot
    return honeypot.get_blocklist()


@router.post("/unblock")
def security_unblock(body: dict):
    from services.honeypot import honeypot
    return honeypot.unblock(body.get("ip", ""))


@router.get("/threats")
def security_threats():
    from services.behavioral_security import behavioral
    return {"behavioral": behavioral.threat_summary()}


@router.post("/ip-reputation")
def security_ip_reputation(body: dict):
    from services.threat_intel import threat_intel
    return threat_intel.check_ip_reputation(body.get("ip", ""))


@router.get("/attack-patterns")
def security_attack_patterns():
    from services.threat_intel import threat_intel
    return {"patterns": threat_intel.get_latest_attack_patterns()}


@router.post("/redteam-analysis")
def security_redteam_analysis():
    from services.threat_intel import threat_intel
    return {"analysis": threat_intel.red_team_analysis()}


@router.get("/ratelimit-check")
def security_ratelimit_check(ip: str, endpoint: str = "/stark/chat"):
    """Preview what the adaptive rate limiter *would* decide for this IP —
    informational only, not enforced (see services/adaptive_ratelimit.py)."""
    from services.adaptive_ratelimit import rate_limiter
    return rate_limiter.check(ip, endpoint)


@router.get("/siem")
def security_siem_dashboard():
    from services.siem import siem
    return siem.security_dashboard()
