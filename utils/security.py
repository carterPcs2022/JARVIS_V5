"""utils/security.py — Auth, rate limiting, CORS."""
import hmac
import ipaddress
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import time
from config.settings import API_TOKEN, ALLOWED_ORIGINS, ENVIRONMENT, PUBLIC_URL, TWILIO_AUTH_TOKEN

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


def _check_protocol_ip_allowlist(ip: str):
    """Optional extra layer on top of the master token for the highest-
    stakes routes (lockdown, coldfire, scatter, sandbox approve/persist,
    run_protocol) — set PROTOCOL_ALLOWED_IPS (comma-separated IPs/CIDRs,
    your real public IP(s)) to reject requests from anywhere else even
    with a valid master token. Empty/unset = disabled, same "unset secret
    = gate doesn't apply" convention as every other gate this session —
    most home ISPs rotate residential public IPs periodically, so a
    hardcoded allowlist could otherwise lock the owner out with no way
    back in except Render's dashboard. This is opt-in and only as strict
    as the value you actually set."""
    allowed = os.getenv("PROTOCOL_ALLOWED_IPS", "")
    if not allowed:
        return
    entries = [e.strip() for e in allowed.split(",") if e.strip()]
    if not entries:
        return
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(403, "Request origin could not be verified")
    for entry in entries:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return
            elif addr == ipaddress.ip_address(entry):
                return
        except ValueError:
            continue
    try:
        from services.notifications import alert
        alert("Protocol request from unrecognized network",
              f"A Stark Protocol endpoint was called with a valid master "
              f"token from {ip}, which isn't in PROTOCOL_ALLOWED_IPS. "
              f"Rejected — if this was really you, add this IP to that "
              f"env var.")
    except Exception:
        pass
    raise HTTPException(403, "Request origin not in the allowed network")


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


def _public_request_url(request: Request) -> str:
    """Reconstruct the externally-visible URL a signer (Twilio, GitHub)
    actually sent its request to. Render terminates TLS at its edge and
    forwards internally over plain http, so request.url reports the wrong
    scheme/host unless we honor X-Forwarded-* — same problem PUBLIC_URL
    already exists to solve for outbound TwiML action URLs in
    services/phone.py, so prefer it when it's actually configured."""
    if PUBLIC_URL and "localhost" not in PUBLIC_URL:
        base = PUBLIC_URL.rstrip("/")
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        base = f"{proto}://{host}"
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base}{request.url.path}{query}"


def verify_twilio_signature(request: Request, form: dict):
    """Twilio's own documented scheme: HMAC-SHA1 (via twilio's
    RequestValidator) over the exact request URL + sorted POST params,
    compared against X-Twilio-Signature. Fails closed — if
    TWILIO_AUTH_TOKEN isn't set, every request is rejected rather than
    silently accepted, same convention as every other secret-gated check
    in this file (unset secret = the gate stays shut, not open)."""
    if not TWILIO_AUTH_TOKEN:
        raise HTTPException(403, "SMS webhook not configured")
    signature = request.headers.get("x-twilio-signature", "")
    if not signature:
        raise HTTPException(403, "Missing X-Twilio-Signature")
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = _public_request_url(request)
    if not validator.validate(url, form, signature):
        raise HTTPException(403, "Invalid Twilio signature")


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
    # allow_credentials=True + a wildcard origin lets Starlette reflect
    # *any* requesting Origin back with Access-Control-Allow-Credentials:
    # true — effectively "any website may make credentialed requests,"
    # which defeats the point of restricting origins at all. Auth here is
    # a bearer token, not a cookie, so credentialed cross-origin requests
    # aren't needed when the origin list hasn't been explicitly narrowed;
    # only turn credentials on once ALLOWED_ORIGINS names real origins.
    wildcard = ALLOWED_ORIGINS == ["*"]
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_credentials=not wildcard, allow_methods=["*"], allow_headers=["*"])
