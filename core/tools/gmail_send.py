"""core/tools/gmail_send.py — Gmail send via OAuth2, reusing the same
Google Cloud app and refresh token as core/tools/google_calendar.py
(scope expanded in server/routes/calendar_auth.py to include gmail.send).

Draft-then-confirm only, no exceptions: draft_email() never sends
anything — it stores a pending draft and returns it for review.
send_pending_draft() is the ONLY function in this module that ever calls
Gmail's send API, and only for a draft that was explicitly created via
draft_email() and hasn't expired. There is no path from draft to sent
that skips the explicit send_pending_draft() call.
"""
import base64
import json
import time
import uuid
from email.message import EmailMessage

from config.settings import (
    GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_REFRESH_TOKEN, BASE_DIR,
)

_PENDING_FILE = BASE_DIR / "memory" / "pending_email_draft.json"
# A draft sitting unconfirmed for a while shouldn't still be sendable long
# after the conversation that created it has moved on — 10 minutes is
# generous for "review it, then say send" without becoming a stale
# loaded gun.
_DRAFT_EXPIRY_SECONDS = 600


def is_configured() -> bool:
    return bool(GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET
                and GOOGLE_CALENDAR_REFRESH_TOKEN)


def _get_service():
    """Raises on missing dependencies/credentials; callers decide how to
    degrade — same convention as core/tools/google_calendar.py."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=GOOGLE_CALENDAR_REFRESH_TOKEN,
        client_id=GOOGLE_CALENDAR_CLIENT_ID,
        client_secret=GOOGLE_CALENDAR_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def draft_email(to: str, subject: str, body: str) -> dict:
    """Create a pending draft for review. Never sends anything — replaces
    whatever draft (if any) was pending before, since there's only ever
    one active review at a time."""
    draft = {
        "id":      uuid.uuid4().hex[:12],
        "to":      to,
        "subject": subject,
        "body":    body,
        "created": time.time(),
    }
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PENDING_FILE.write_text(json.dumps(draft))
    return draft


def get_pending_draft() -> dict | None:
    """None if no draft is pending, or the pending one has expired (and
    is cleaned up as a side effect of checking)."""
    if not _PENDING_FILE.exists():
        return None
    try:
        draft = json.loads(_PENDING_FILE.read_text())
    except Exception:
        return None
    if time.time() - draft.get("created", 0) > _DRAFT_EXPIRY_SECONDS:
        discard_pending_draft()
        return None
    return draft


def discard_pending_draft() -> bool:
    if _PENDING_FILE.exists():
        _PENDING_FILE.unlink()
        return True
    return False


def send_pending_draft(draft_id: str | None = None) -> dict:
    """The only function in this module that calls Gmail's send API.
    Requires an explicit call — draft_email() never calls this itself,
    and no scheduled job or background process calls it either. Sends
    the current pending draft if one exists, hasn't expired, and (when
    draft_id is given) matches it."""
    draft = get_pending_draft()
    if not draft:
        return {"ok": False, "message": "No pending draft to send — it may have expired. Draft it again."}
    if draft_id and draft["id"] != draft_id:
        return {"ok": False, "message": "That draft ID doesn't match the current pending draft."}
    if not is_configured():
        return {"ok": False, "message": "Gmail OAuth isn't configured."}

    try:
        service = _get_service()
        message = EmailMessage()
        message.set_content(draft["body"])
        message["To"] = draft["to"]
        message["Subject"] = draft["subject"]
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
    except Exception as e:
        return {"ok": False, "message": f"Send failed: {e}"}

    gmail_message_id = result.get("id", "")
    _log_sent(draft, gmail_message_id)
    discard_pending_draft()
    return {"ok": True, "message": f"Sent to {draft['to']}.", "gmail_message_id": gmail_message_id}


def _log_sent(draft: dict, gmail_message_id: str):
    """Durable record separate from Gmail's own Sent folder — reuses the
    existing hash-chained audit log (services/audit_log.py) rather than a
    new log format, matching how other real/sensitive actions in this
    codebase are already recorded."""
    from services.audit_log import audit_log
    audit_log.record(
        "EMAIL_SENT",
        details={
            "to": draft["to"], "subject": draft["subject"],
            "body_preview": draft["body"][:200],
            "gmail_message_id": gmail_message_id,
        },
    )
