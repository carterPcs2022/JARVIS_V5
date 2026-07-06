"""
services/email_intel.py — EmailIntelligence: IMAP reading, classification, drafting, watching.
"""
import email
import imaplib
import json
import os
from datetime import datetime
from email.header import decode_header
from pathlib import Path

from core.llm.router import think
from config.settings import BASE_DIR

_PEOPLE_FILE  = BASE_DIR / "memory" / "people.json"
_WATCHES_FILE = BASE_DIR / "memory" / "email_watches.json"

_URGENT_KEYWORDS = {"urgent", "deadline", "asap", "immediately", "critical"}


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


class EmailIntelligence:

    # ------------------------------------------------------------------ #
    # IMAP connection                                                      #
    # ------------------------------------------------------------------ #

    def _connect_imap(self):
        """Connect to IMAP and select INBOX. Returns connection or None."""
        server   = os.environ.get("IMAP_SERVER",   "imap.gmail.com")
        username = os.environ.get("IMAP_USERNAME",  "")
        password = os.environ.get("IMAP_PASSWORD",  "")

        if not username or not password:
            return None

        try:
            conn = imaplib.IMAP4_SSL(server)
            conn.login(username, password)
            conn.select("INBOX")
            return conn
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Reading emails                                                       #
    # ------------------------------------------------------------------ #

    def get_unread(self, max_emails: int = 10) -> list:
        """Fetch unread emails with classification."""
        conn = self._connect_imap()
        if conn is None:
            return []

        try:
            _, data = conn.search(None, "UNSEEN")
            msg_ids = data[0].split()
            # Most recent first, capped at max_emails
            msg_ids = msg_ids[-max_emails:][::-1]

            # Load known people for importance check
            known_senders = set()
            people = _load_json(_PEOPLE_FILE, {})
            if isinstance(people, list):
                for p in people:
                    for email_addr in p.get("emails", []):
                        known_senders.add(email_addr.lower())
            elif isinstance(people, dict):
                for _, p in people.items():
                    for email_addr in p.get("emails", []):
                        known_senders.add(email_addr.lower())

            emails = []
            for msg_id in msg_ids:
                try:
                    _, msg_data = conn.fetch(msg_id, "(RFC822)")
                    raw         = msg_data[0][1]
                    msg         = email.message_from_bytes(raw)

                    subject = self._decode_header_str(msg.get("Subject", ""))
                    sender  = msg.get("From", "")
                    date_   = msg.get("Date", "")
                    body    = self._decode_email_body(msg)
                    preview = body[:200]

                    classification = self._classify_email(subject, body, sender)

                    # Upgrade to "important" if sender is known
                    sender_clean = sender.lower()
                    if any(k in sender_clean for k in known_senders):
                        classification = "important"

                    emails.append({
                        "id":             msg_id.decode(),
                        "sender":         sender,
                        "subject":        subject,
                        "date":           date_,
                        "preview":        preview,
                        "classification": classification,
                        "known_sender":   any(k in sender_clean for k in known_senders),
                    })
                except Exception:
                    continue

            conn.logout()
            return emails

        except Exception:
            try:
                conn.logout()
            except Exception:
                pass
            return []

    # ------------------------------------------------------------------ #
    # Summarization                                                        #
    # ------------------------------------------------------------------ #

    def summarize_inbox(self) -> str:
        """LLM generates a JARVIS-style inbox summary."""
        emails = self.get_unread()
        if not emails:
            return "Inbox is clear. No unread messages, sir."

        lines = []
        for e in emails:
            lines.append(
                f"- [{e['classification'].upper()}] From {e['sender']}: "
                f"\"{e['subject']}\" — {e['preview'][:80]}..."
            )

        prompt = (
            "You are JARVIS. Summarize this inbox in your signature style — "
            "concise, helpful, a touch of dry wit:\n\n"
            + "\n".join(lines)
        )
        return think(prompt)

    # ------------------------------------------------------------------ #
    # Drafting                                                             #
    # ------------------------------------------------------------------ #

    def draft_reply(self, email_id: str, intent: str) -> dict:
        """LLM drafts a reply — never sent automatically."""
        prompt = (
            f"Draft a professional email reply. Email ID context: {email_id}. "
            f"Intent for reply: {intent}. "
            "Write in JARVIS's professional but warm voice. Be concise and clear."
        )
        draft = think(prompt)
        return {
            "draft":  draft,
            "status": "awaiting_approval",
            "note":   (
                "PROTOCOL 1: Email requires explicit approval. "
                "JARVIS never sends automatically."
            ),
        }

    # ------------------------------------------------------------------ #
    # Watching                                                             #
    # ------------------------------------------------------------------ #

    def watch_for_sender(self, email_address: str) -> dict:
        """Add an email address to the watch list."""
        watches = _load_json(_WATCHES_FILE, [])
        if email_address not in watches:
            watches.append(email_address)
            _save_json(_WATCHES_FILE, watches)
        return {
            "status":  "watching",
            "address": email_address,
            "message": f"I'll flag any messages from {email_address}, sir.",
        }

    # ------------------------------------------------------------------ #
    # Daily brief                                                          #
    # ------------------------------------------------------------------ #

    def email_brief_daily(self) -> str:
        """Format inbox summary for a morning briefing."""
        summary = self.summarize_inbox()
        timestamp = datetime.now().strftime("%A, %B %d at %I:%M %p")
        return f"Email brief as of {timestamp}:\n\n{summary}"

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _decode_header_str(self, value: str) -> str:
        """Decode an encoded email header value to a plain string."""
        parts = decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded)

    def _decode_email_body(self, msg) -> str:
        """Extract plain text body from a MIME email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition  = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body   += payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body    = payload.decode(charset, errors="replace")
        return body.strip()

    def _classify_email(self, subject: str, body: str, sender: str) -> str:
        """Classify an email as urgent / newsletter / important / spam."""
        combined = (subject + " " + body).lower()

        # Urgent
        if any(kw in combined for kw in _URGENT_KEYWORDS):
            return "urgent"

        # Newsletter / marketing
        if "unsubscribe" in combined:
            return "newsletter"

        # Default — caller may upgrade to "important" based on people memory
        return "spam"


# Module-level singleton
email_intel = EmailIntelligence()
