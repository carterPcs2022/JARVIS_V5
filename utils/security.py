"""utils/security.py — Auth, rate limiting, CORS."""
import hmac
import ipaddress
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import time
from config.settings import API_TOKEN, ALLOWED_ORIGINS, ENVIRONMENT

bearer = HTTPBearer(auto_error=False)

# ── Trusted IP whitelist ──────────────────────────────────────────────────────
# Shared by services/sentinel.py and services/behavioral_security.py so
# loopback traffic, Render's internal network, and uptime monitors don't
# trip brute-force/behavioral-anomaly alerts.
TRUSTED_IPS: list[str] = [
    "127.0.0.1",
    "::1",
    "10.0.0.0/8",       # Internal Render network
    "169.254.0.0/16",   # Render health checks
]

# UptimeRobot's published IP list (https://uptimerobot.com/inc/files/ips-v4.txt)
# is a large, individually-listed set that changes over time — hardcoding a
# stale copy here would either miss real monitor IPs or silently keep
# trusting addresses UptimeRobot no longer owns. Set UPTIMEROBOT_IP_RANGES
# (comma-separated IPs/CIDRs, pulled from that URL) in .env instead.
for _env_var in ("UPTIMEROBOT_IP_RANGES", "TRUSTED_IP_RANGES"):
    _extra = os.getenv(_env_var, "")
    if _extra:
        TRUSTED_IPS += [ip.strip() for ip in _extra.split(",") if ip.strip()]


def is_trusted_ip(ip: str) -> bool:
    """True if `ip` matches an exact address or falls inside a CIDR range
    in TRUSTED_IPS."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in TRUSTED_IPS:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False

def verify_token(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """
    - If JARVIS_API_TOKEN is empty -> open access (no auth needed at all).
    - If ENVIRONMENT is 'local' and DEV_MODE=true -> bypass auth, for painless
      local development. Never set DEV_MODE=true anywhere reachable from the
      internet (Railway, Docker exposed to a network, etc).
    - Otherwise -> require a valid Bearer token.
    Uses hmac.compare_digest rather than == — constant-time, so a token
    guesser can't use response timing to infer how many leading characters
    they got right. Free to do (same cost as == for strings this short);
    no reason not to.
    """
    if not API_TOKEN:
        return True

    if ENVIRONMENT == "local" and os.getenv("DEV_MODE", "false").lower() == "true":
        return True

    ip = request.client.host if request.client else "unknown"
    _reject_if_blocked(ip)

    if not creds or not hmac.compare_digest(creds.credentials, API_TOKEN):
        _record_failed_auth_safe(ip)
        raise HTTPException(401, "Unauthorized — invalid token")
    return True


def _reject_if_blocked(ip: str):
    """Checked before the token comparison on every auth path (REST,
    WebSocket, Pepper/Rhodey/master tiers) — an IP that's tripped the
    brute-force threshold (services.sentinel.is_blocked) gets rejected
    immediately, without ever reaching hmac.compare_digest. Wrapped in
    try/except like _record_failed_auth_safe below — a sentinel hiccup
    must never be able to turn a normal auth check into a 500, or worse,
    silently let blocking stop working."""
    try:
        from services.sentinel import is_blocked
        if is_blocked(ip):
            raise HTTPException(403, "Too many failed attempts — temporarily blocked")
    except HTTPException:
        raise
    except Exception:
        pass


def _record_failed_auth_safe(ip: str):
    """services.sentinel.record_failed_auth() existed but was never
    actually called from any real auth-check path — confirmed by grep,
    every rejected request (401s, WS 403s) went completely unrecorded,
    so the sentinel's threat log only ever reflected resource pressure
    (HIGH_CPU/HIGH_DISK), never actual unauthenticated access attempts.
    Wrapped in try/except since a sentinel hiccup must never be able to
    turn a normal 401 into a 500."""
    try:
        from services.sentinel import record_failed_auth
        record_failed_auth(ip)
    except Exception:
        pass

_rate_store: dict = defaultdict(list)
RATE_LIMIT, RATE_WINDOW = 60, 60

def rate_limit(request: Request):
    ip = request.client.host
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded")
    _rate_store[ip].append(now)

def add_cors(app):
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
