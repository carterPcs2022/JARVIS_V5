"""services/alert_email.py — Direct-send alert email, independent of Gmail's
draft-then-confirm flow in core/tools/gmail_send.py.

That module's send_pending_draft() is deliberately the only path that can
ever call Gmail's send API, and only for a human-reviewed draft — exactly
right for user-facing "send this email" requests, wrong for automated
alerts, which by definition can't wait for a human to review and confirm
before they fire. This is a second, narrower path: reuses the same Gmail
OAuth app/credentials as the backend, sends immediately with no draft step,
and is only ever called from core/event_bus.py's alert() for critical/high
severity — never anywhere a draft-confirm flow would be appropriate.
"""
import base64
from email.message import EmailMessage

from config.settings import (
    GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_REFRESH_TOKEN, EMERGENCY_CONTACT_EMAIL,
)


def is_configured() -> bool:
    return bool(GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET
                and GOOGLE_CALENDAR_REFRESH_TOKEN and EMERGENCY_CONTACT_EMAIL)


def _get_service():
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


def send_alert_email(severity: str, category: str, message: str) -> dict:
    """Fire-and-forget — called from core/event_bus.py alongside Pushover.
    Never raises; a broken email path must not be able to block or crash
    the alert it exists to back up, same convention every other channel in
    EventBus.alert() already follows."""
    if not is_configured():
        return {"ok": False, "error": "not configured"}
    try:
        service = _get_service()
        subject = f"[JARVIS {severity.upper()}] {category}: {message[:80]}"
        body = f"Severity: {severity.upper()}\nCategory: {category}\n\n{message}"
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = EMERGENCY_CONTACT_EMAIL
        msg["Subject"] = subject
        encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
        return {"ok": True, "gmail_message_id": result.get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
