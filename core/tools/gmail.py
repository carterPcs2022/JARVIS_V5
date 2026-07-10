"""
core/tools/gmail.py — Gmail via IMAP/SMTP + a Gmail App Password
(Google Account -> Security -> App Passwords, requires 2FA enabled) —
not OAuth2. Simpler setup, no Cloud Console project, no browser consent
flow, no credentials JSON file.

First-time setup:
  1. Enable 2-Step Verification on the Google account, if not already on.
  2. Google Account -> Security -> App Passwords -> generate one for "Mail".
  3. Set env vars: GMAIL_ADDRESS=you@gmail.com, GMAIL_APP_PASSWORD=<the 16-char password>.

Note on message IDs: check_inbox()/search_emails() now return IMAP UIDs
(strings), not Gmail API message IDs — a different ID space than the old
OAuth version used. mark_as_read() expects the same IMAP UID it just gave
you back, not a Gmail API id from anywhere else.
"""
import os
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText

GMAIL_USER = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD", "")


def _connect() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    return mail


def _decode_subject(msg) -> str:
    raw = msg.get("Subject", "") or ""
    if not raw:
        return "(no subject)"
    decoded = decode_header(raw)[0][0]
    if isinstance(decoded, bytes):
        decoded = decoded.decode(errors="replace")
    return decoded or "(no subject)"


def _get_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(errors="replace") if payload else ""


def _parse_message(mail: imaplib.IMAP4_SSL, uid: bytes) -> dict:
    _, data = mail.fetch(uid, "(RFC822 FLAGS)")
    raw = data[0][1]
    flags_blob = data[0][0].decode(errors="replace") if isinstance(data[0][0], (bytes, bytearray)) else str(data[0][0])
    msg = email.message_from_bytes(raw)
    body = _get_body(msg)

    return {
        "id": uid.decode(),
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": _decode_subject(msg),
        "date": msg.get("Date", ""),
        "snippet": body[:200],
        "body": body[:2000],
        "unread": "\\Seen" not in flags_blob,
    }


def _fetch(mail: imaplib.IMAP4_SSL, uids: list, max_results: int) -> list[dict]:
    emails = []
    # Each message gets its own try/except — one malformed message
    # (bad encoding, missing headers, non-text body) must not wipe out
    # the rest of the batch.
    for uid in reversed(uids[-max_results:]):
        try:
            emails.append(_parse_message(mail, uid))
        except Exception as e:
            print(f"[JARVIS Gmail] Failed to parse message {uid}: {e}")
    return emails


# ── Public API ────────────────────────────────────────────────────────────────
# Signatures unchanged from the OAuth version — server/routes/mac.py and
# services/scheduler.py call these by name/position, not aware of the
# swap underneath.

def check_inbox(max_results: int = 10, unread_only: bool = True) -> list[dict]:
    """Return the latest inbox emails."""
    if not is_configured():
        return [{"error": "Gmail not configured"}]
    mail = None
    try:
        mail = _connect()
        mail.select("inbox")
        criterion = "UNSEEN" if unread_only else "ALL"
        _, ids = mail.search(None, criterion)
        uids = ids[0].split()
        return _fetch(mail, uids, max_results)
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def search_emails(query: str, max_results: int = 5) -> list[dict]:
    """Search Gmail with Gmail's own query syntax (from:, subject:,
    is:unread, etc) via the X-GM-RAW IMAP extension Google's servers
    support — same query language the old Gmail-API version accepted."""
    if not is_configured():
        return [{"error": "Gmail not configured"}]
    mail = None
    try:
        mail = _connect()
        mail.select("inbox")
        _, ids = mail.search(None, "X-GM-RAW", f'"{query}"')
        uids = ids[0].split()
        return _fetch(mail, uids, max_results)
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email from the authorized account via SMTP (IMAP itself
    has no send capability — Gmail's SMTP server accepts the same app
    password)."""
    if not is_configured():
        return {"ok": False, "message": "Gmail not configured"}
    try:
        msg = MIMEText(body)
        msg["From"] = GMAIL_USER
        msg["To"] = to
        msg["Subject"] = subject
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, [to], msg.as_string())
        return {"ok": True, "message": f"Email sent to {to}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def mark_as_read(message_id: str) -> dict:
    """message_id must be an IMAP UID this module returned (from
    check_inbox()/search_emails()), not any other ID space."""
    if not is_configured():
        return {"ok": False, "message": "Gmail not configured"}
    mail = None
    try:
        mail = _connect()
        mail.select("inbox")
        mail.store(message_id.encode(), "+FLAGS", "\\Seen")
        return {"ok": True, "message": f"Marked {message_id} as read"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def get_unread_count() -> int:
    if not is_configured():
        return -1
    mail = None
    try:
        mail = _connect()
        mail.select("inbox")
        _, ids = mail.search(None, "UNSEEN")
        return len(ids[0].split())
    except Exception:
        return -1
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def is_configured() -> bool:
    return bool(GMAIL_USER and GMAIL_PASS)
