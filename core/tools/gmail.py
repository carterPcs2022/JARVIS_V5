"""
core/tools/gmail.py — Gmail via Google OAuth2.

First-time setup:
  1. Go to https://console.cloud.google.com → Create project → Enable Gmail API
  2. Create OAuth 2.0 credentials (Desktop app) → Download JSON
  3. Save it as JARVIS_V5/config/gmail_credentials.json
  4. On first use JARVIS will open a browser for you to authorize — token is saved automatically.
"""
import os, base64, json
from pathlib import Path
from email.mime.text import MIMEText
from config.settings import BASE_DIR

CREDENTIALS_FILE = BASE_DIR / "config" / "gmail_credentials.json"
TOKEN_FILE       = BASE_DIR / "config" / "gmail_token.json"
SCOPES           = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {CREDENTIALS_FILE}. "
                    "See setup instructions in core/tools/gmail.py"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _parse_message(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    snippet = msg.get("snippet", "")
    body    = ""

    parts = msg["payload"].get("parts", [])
    if parts:
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                    break
    else:
        data = msg["payload"].get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    return {
        "id":      msg["id"],
        "from":    headers.get("From", ""),
        "to":      headers.get("To", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "date":    headers.get("Date", ""),
        "snippet": snippet,
        "body":    body[:2000],
        "unread":  "UNREAD" in msg.get("labelIds", []),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def check_inbox(max_results: int = 10, unread_only: bool = True) -> list[dict]:
    """Return the latest inbox emails."""
    try:
        svc = _get_service()
        q   = "in:inbox is:unread" if unread_only else "in:inbox"
        res = svc.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
        msgs = res.get("messages", [])
        emails = []
        for m in msgs:
            full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            emails.append(_parse_message(full))
        return emails
    except Exception as e:
        return [{"error": str(e)}]


def search_emails(query: str, max_results: int = 5) -> list[dict]:
    """Search Gmail with any query string."""
    try:
        svc = _get_service()
        res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        msgs = res.get("messages", [])
        emails = []
        for m in msgs:
            full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            emails.append(_parse_message(full))
        return emails
    except Exception as e:
        return [{"error": str(e)}]


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email from the authorized account."""
    try:
        svc = _get_service()
        msg = MIMEText(body)
        msg["to"]      = to
        msg["subject"] = subject
        raw  = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "id": sent["id"], "message": f"Email sent to {to}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def mark_as_read(message_id: str) -> dict:
    try:
        svc = _get_service()
        svc.users().messages().modify(
            userId="me", id=message_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return {"ok": True, "message": f"Marked {message_id} as read"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def get_unread_count() -> int:
    try:
        svc  = _get_service()
        res  = svc.users().labels().get(userId="me", id="INBOX").execute()
        return res.get("messagesUnread", 0)
    except Exception:
        return -1


def is_configured() -> bool:
    return CREDENTIALS_FILE.exists()
