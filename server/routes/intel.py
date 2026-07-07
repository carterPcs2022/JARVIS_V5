"""server/routes/intel.py — unified threat intelligence endpoint.
Aggregates honeypot, AI firewall, behavioral anomaly, and sentinel
brute-force sources into one feed. Powers the global threat map
(hud_mobile/intelligence_map.html).

Deliberately does NOT also pull services.siem — honeypot.trigger() and
behavioral_security._log_anomaly() already forward into siem.log_event(),
so including it too would double-count the same triggers under a
different label."""
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends

from utils.security import verify_token

router = APIRouter(prefix="/stark/intel", tags=["intel"], dependencies=[Depends(verify_token)])

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@router.get("/threats")
def get_threats(limit: int = 100):
    """Unified threat feed for the global intelligence map."""
    threats = []

    # ── Honeypot triggers — logs/honeypot.json, flat list of entries ─────────
    try:
        from services.honeypot import HONEYPOT_FILE
        if HONEYPOT_FILE.exists():
            log = json.loads(HONEYPOT_FILE.read_text())
            for entry in log[-limit:]:
                threats.append({
                    "ip":          entry.get("ip", ""),
                    "threat_type": "HONEYPOT",
                    "severity":    entry.get("severity", "CRITICAL"),
                    "endpoint":    entry.get("endpoint", ""),
                    "ts":          entry.get("ts", ""),
                    "blocked":     True,
                })
    except Exception:
        pass

    # ── AI Firewall blocks — logs/ai_firewall.json, flat list of entries ──────
    try:
        from services.ai_firewall import FIREWALL_LOG
        if FIREWALL_LOG.exists():
            log = json.loads(FIREWALL_LOG.read_text())
            for entry in log[-limit:]:
                raw_type = entry.get("threat_type") or ""
                threat_type = "INJECTION" if raw_type in (
                    "PROMPT_INJECTION", "SOCIAL_ENGINEERING",
                ) else "BLOCKED"
                threats.append({
                    "ip":          entry.get("ip", ""),
                    "threat_type": threat_type,
                    "severity":    "CRITICAL" if threat_type == "INJECTION" else "HIGH",
                    "endpoint":    "/stark/chat",
                    "ts":          entry.get("ts", ""),
                    "blocked":     True,
                    "reason":      entry.get("reason", ""),
                })
    except Exception:
        pass

    # ── Behavioral anomalies — in-memory only, not file-backed ────────────────
    try:
        from services.behavioral_security import behavioral
        for entry in behavioral.get_anomaly_log(limit):
            threats.append({
                "ip":          entry.get("ip", ""),
                "threat_type": "ANOMALY",
                "severity":    entry.get("severity", "MEDIUM"),
                "endpoint":    ", ".join(entry.get("anomalies", []))[:60],
                "ts":          entry.get("ts", ""),
                "blocked":     False,
            })
    except Exception:
        pass

    # ── Sentinel brute-force — logs/threats.json has no dedicated ip field,
    # it's embedded in the detail string (see services/sentinel.py
    # record_failed_auth); other categories (file tamper, CPU/RAM/disk) have
    # no originating IP at all and are skipped since they can't be plotted ──
    try:
        from services.sentinel import threats as sentinel_threats
        for t in sentinel_threats(24):
            if t.get("category") != "BRUTE_FORCE":
                continue
            m = _IP_RE.search(t.get("detail", ""))
            if not m:
                continue
            threats.append({
                "ip":          m.group(0),
                "threat_type": "SCAN",
                "severity":    (t.get("severity") or "medium").upper(),
                "endpoint":    "/stark/chat",
                "ts":          t.get("ts", ""),
                "blocked":     False,
            })
    except Exception:
        pass

    threats = [t for t in threats if t.get("ip")]
    threats.sort(key=lambda x: x.get("ts", ""), reverse=True)

    return {
        "threats": threats[:limit],
        "total":   len(threats),
        "ts":      datetime.now().isoformat(),
    }
