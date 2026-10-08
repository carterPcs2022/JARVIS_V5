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
TRUSTED_IPS: list[str] = ["127.0.0.1", "::1", "10.0.0.0/8", "169.254.0.0/16"]
for _env_var in ("UPTIMEROBOT_IP_RANGES", "TRUSTED_IP_RANGES"):
    _extra = os.getenv(_env_var, "")
    if _extra:
        TRUSTED_IPS += [ip.strip() for ip in _extra.split(",") if ip.strip()]


def is_trusted_ip(ip: str) -> bool:
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
    """Authenticate requests; cloud deployments fail closed if no token is configured."""
    if not API_TOKEN:
        if ENVIRONMENT == "local":
            return True
        raise HTTPException(503, "JARVIS authentication is not configured")
    if ENVIRONMENT == "local" and os.getenv("DEV_MODE", "false").lower() == "true":
        return True
    ip = request.client.host if request.client.host else "unknown"
    token_ok = bool(creds) and hmac.compare_digest(creds.credentials, API_TOKEN)
    if not token_ok:
        _reject_if_blocked(ip)
        _record_failed_auth_safe(ip)
        raise HTTPException(401, "Unauthorized — invalid token")

    # A valid credential wins over a stale temporary failed-auth block.
    try:
        from services.sentinel import clear_failed_auth
        clear_failed_auth(ip)
    except Exception:
        pass
    return True


def _check_protocol_ip_allowlist(ip: str):
    allowed = os.getenv("PROTOCOL_ALLOWED_IPS", "")
    if not allowed:
        return
    entries = [e.strip() for e in allowed.split(",") if e.strip()]
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(403, "Request origin could not be verified")
    for entry in entries:
        try:
            if "/" in entry and addr in ipaddress.ip_network(entry, strict=False):
                return
            if "/" not in entry and addr == ipaddress.ip_address(entry):
                return
        except ValueError:
            continue
    try:
        from services.notifications import alert
        alert("Protocol request from unrecognized network", f"Rejected protocol request from {ip}.")
    except Exception:
        pass
    raise HTTPException(403, "Request origin not in the allowed network")


def _reject_if_blocked(ip: str):
    try:
        from services.sentinel import is_blocked
        if is_blocked(ip):
            raise HTTPException(403, "Too many failed attempts — temporarily blocked")
    except HTTPException:
        raise
    except Exception:
        pass


def _public_request_url(request: Request) -> str:
    if PUBLIC_URL and "localhost" not in PUBLIC_URL:
        base = PUBLIC_URL.rstrip("/")
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        base = f"{proto}://{host}"
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base}{request.url.path}{query}"


def verify_twilio_signature(request: Request, form: dict):
    if not TWILIO_AUTH_TOKEN:
        raise HTTPException(403, "SMS webhook not configured")
    signature = request.headers.get("x-twilio-signature", "")
    if not signature:
        raise HTTPException(403, "Missing X-Twilio-Signature")
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    if not validator.validate(_public_request_url(request), form, signature):
        raise HTTPException(403, "Invalid Twilio signature")


def _record_failed_auth_safe(ip: str):
    try:
        from services.sentinel import record_failed_auth
        record_failed_auth(ip)
    except Exception:
        pass

_rate_store: dict = defaultdict(list)
RATE_LIMIT, RATE_WINDOW = 60, 60
MAX_TRACKED_IPS = 4096


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded")
    _rate_store[ip].append(now)
    if len(_rate_store) > MAX_TRACKED_IPS:
        stale = [key for key, values in _rate_store.items() if not values]
        for key in stale[:512]:
            _rate_store.pop(key, None)


def add_cors(app):
    wildcard = ALLOWED_ORIGINS == ["*"]
    # In cloud, wildcard becomes no browser CORS until an explicit allowlist
    # is configured. Locally, wildcard remains usable but never credentialed.
    origins = [] if wildcard and ENVIRONMENT != "local" else ALLOWED_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=bool(origins and not wildcard),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
