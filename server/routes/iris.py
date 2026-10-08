"""server/routes/iris.py — REST proxy to the Mac Bridge's iris-recognition
pipeline (real MediaPipe landmark detection + Daugman/Gabor iris coding),
replacing the old services/retinal_scan.py entirely rather than patching it
(that implementation SHA256-hashed the derived pattern before comparison,
which destroys the similarity structure needed for real matching, and
verify with nothing enrolled silently auto-enrolled whoever submitted
first — confirmed by direct execution, not assumed).

Thin-proxy pattern mirrors server/routes/voice.py exactly: the Mac Bridge
token never reaches the browser, only this server holds it.
"""
import os
import httpx
from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from utils.security import verify_token
from config.settings import AVENGERS_PASSPHRASE

router = APIRouter(prefix="/stark/iris", tags=["iris"])

MAC_BRIDGE_URL = os.getenv("MAC_BRIDGE_URL", "")
MAC_BRIDGE_TOKEN = os.getenv("MAC_BRIDGE_TOKEN", "")

# Mirrors voice.py's ENROLL_TARGET convention: a profile only counts as
# "fully enrolled" (subject to re-auth-to-overwrite, and eligible to make
# the lockdown/sandbox AND-gate below actually apply) once it has a real
# number of samples, not just one. The bridge caps stored samples at 5.
IRIS_ENROLL_TARGET = 3


def _passphrase_ok(body: dict) -> bool:
    if not AVENGERS_PASSPHRASE:
        return True
    return body.get("passphrase", "") == AVENGERS_PASSPHRASE


async def _profile_fully_enrolled(profile: str) -> bool:
    """Fails CLOSED (an unreachable bridge counts as "fully enrolled," i.e.
    keeps the re-auth-to-overwrite gate up) — same reasoning as voice.py's
    identically-named function: a bridge hiccup must never be usable as an
    excuse to skip re-auth before destroying or overwriting a stored iris
    profile."""
    if not MAC_BRIDGE_URL:
        return True
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MAC_BRIDGE_URL}/iris/profile/status",
                params={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            data = resp.json()
            return bool(data.get("enrolled")) and data.get("sample_count", 0) >= IRIS_ENROLL_TARGET
    except Exception:
        return True


async def iris_profile_enrolled(profile: str = "default") -> bool:
    """Whether the Suit Lockdown / sandbox approve+persist AND-gate applies
    at all. Fails OPEN (bridge unreachable => gate does not apply) —
    the opposite of _profile_fully_enrolled above, and deliberately so:
    that function protects an EXISTING profile from being overwritten
    without re-auth, but this one only decides whether a *second* factor
    turns on. A bridge hiccup must not silently make lockdown/sandbox
    harder to reach than intended by activating a gate nobody enrolled
    through that same bridge could ever pass."""
    if not MAC_BRIDGE_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MAC_BRIDGE_URL}/iris/profile/status",
                params={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            data = resp.json()
            return bool(data.get("enrolled")) and data.get("sample_count", 0) >= IRIS_ENROLL_TARGET
    except Exception:
        return False


def _reauth_required_response() -> JSONResponse:
    return JSONResponse(status_code=403, content={
        "error": "Re-authentication required — an iris profile is already enrolled.",
        "reauth_required": True,
    })


async def _proxy_to_bridge_response(resp: httpx.Response) -> JSONResponse:
    """A 4xx/5xx from the bridge must not be disguised as a 200 to the
    browser — same reasoning as voice.py's identically-named helper."""
    try:
        resp.raise_for_status()
        return JSONResponse(status_code=200, content=resp.json())
    except httpx.HTTPStatusError:
        try:
            body = resp.json()
        except Exception:
            body = {"error": resp.text}
        return JSONResponse(status_code=resp.status_code, content=body)


@router.post("/enroll", dependencies=[Depends(verify_token)])
async def enroll_iris(image: UploadFile = File(...), profile: str = Form("default"), passphrase: str = Form("")):
    """Thin proxy to the Mac Bridge's iris enrollment. Gated behind
    AVENGERS_PASSPHRASE once a profile is already fully enrolled — see
    _profile_fully_enrolled()'s docstring. A fresh, in-progress enrollment
    is never gated."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    if await _profile_fully_enrolled(profile) and not _passphrase_ok({"passphrase": passphrase}):
        return _reauth_required_response()
    image_bytes = await image.read()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{MAC_BRIDGE_URL}/iris/enroll",
                files={"image": (image.filename or "eye.jpg", image_bytes)},
                data={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            return await _proxy_to_bridge_response(resp)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@router.post("/verify", dependencies=[Depends(verify_token)])
async def verify_iris(image: UploadFile = File(...), profile: str = Form("default")):
    """Thin proxy to the Mac Bridge's fail-closed iris verification. On a
    genuine match, also issues a short-lived confirmation token (mirrors
    core/protocols.py's existing request_avengers_confirmation() pattern)
    that Suit Lockdown and sandbox approve/persist accept as the iris leg
    of their AND-gate, ALONGSIDE — never instead of — their existing
    passphrase/approval-token checks."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    image_bytes = await image.read()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{MAC_BRIDGE_URL}/iris/verify",
                files={"image": (image.filename or "eye.jpg", image_bytes)},
                data={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

    if data.get("verified"):
        from core.protocols import issue_iris_confirmation
        data["iris_confirm_token"] = issue_iris_confirmation()
    return JSONResponse(status_code=200, content=data)


@router.get("/profile/status", dependencies=[Depends(verify_token)])
async def iris_profile_status_route(profile: str = "default"):
    """Thin proxy to the Mac Bridge's iris enrollment status check."""
    if not MAC_BRIDGE_URL:
        return {"enrolled": False, "sample_count": 0, "available": False, "error": "Mac bridge not configured"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{MAC_BRIDGE_URL}/iris/profile/status",
                params={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            data = resp.json()
            if resp.status_code >= 400:
                return {"enrolled": False, "sample_count": 0, "available": False, "error": f"bridge HTTP {resp.status_code}"}
            data["available"] = True
            return data
    except Exception as e:
        return {"enrolled": False, "sample_count": 0, "available": False, "error": f"bridge unreachable: {type(e).__name__}"}


@router.post("/reset", dependencies=[Depends(verify_token)])
async def reset_iris_profile(body: dict):
    """Thin proxy to the Mac Bridge's /iris/reset. Gated behind
    AVENGERS_PASSPHRASE once a profile is already fully enrolled — same
    reasoning as voice.py's reset_voice_profile()."""
    if not MAC_BRIDGE_URL:
        return JSONResponse(status_code=503, content={"error": "Mac bridge not configured"})
    profile = body.get("profile", "default")
    if await _profile_fully_enrolled(profile) and not _passphrase_ok(body):
        return _reauth_required_response()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{MAC_BRIDGE_URL}/iris/reset",
                data={"profile": profile},
                headers={"Authorization": f"Bearer {MAC_BRIDGE_TOKEN}"},
            )
            return await _proxy_to_bridge_response(resp)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
