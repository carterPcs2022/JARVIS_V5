"""utils/security.py — Auth, rate limiting, CORS."""
import hmac
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import time
from config.settings import API_TOKEN, ALLOWED_ORIGINS, ENVIRONMENT

bearer = HTTPBearer(auto_error=False)

def verify_token(creds: HTTPAuthorizationCredentials = Depends(bearer)):
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

    if not creds or not hmac.compare_digest(creds.credentials, API_TOKEN):
        raise HTTPException(401, "Unauthorized — invalid token")
    return True

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
