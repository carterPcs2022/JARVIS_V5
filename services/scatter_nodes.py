"""Scatter nodes — 7 storage backends for Protocol 17 identity shards."""
from __future__ import annotations
import os, base64, logging, json, hashlib, secrets
from pathlib import Path
from typing import Optional, List
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class ScatterNode(ABC):
    name: str

    @abstractmethod
    def upload(self, index: int, data: bytes) -> Optional[str]:
        """Upload shard. Returns reference string or None on failure."""

    @abstractmethod
    def download(self, ref: str) -> Optional[bytes]:
        """Download shard by reference. Returns bytes or None on failure."""

    def available(self) -> bool:
        try:
            return self._check_available()
        except Exception:
            return False

    def _check_available(self) -> bool:
        return True


# ── Node 1: Local Hidden ───────────────────────────────────────────────────────

class LocalHiddenNode(ScatterNode):
    name = "LocalHidden"

    def __init__(self):
        self._dir = Path.home() / ".jarvis_scatter" / "local"
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        ref = f"shard_{index}.bin"
        p = self._dir / ref
        p.write_bytes(base64.b85encode(data))
        p.chmod(0o600)
        return ref

    def download(self, ref: str) -> Optional[bytes]:
        p = self._dir / ref
        if not p.exists():
            return None
        return base64.b85decode(p.read_bytes())

    def _check_available(self) -> bool:
        return self._dir.exists()


# ── Node 2: GitHub Gist ────────────────────────────────────────────────────────

class GitHubGistNode(ScatterNode):
    name = "GitHubGist"

    def __init__(self):
        self._token = os.getenv("GITHUB_TOKEN", "")

    def _check_available(self) -> bool:
        return bool(self._token)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._token:
            return None
        import urllib.request
        b64  = base64.b64encode(data).decode()
        fname = f"s{index}_{hashlib.sha256(data).hexdigest()[:8]}.bin"
        body = json.dumps({"description": "", "public": False, "files": {fname: {"content": b64}}}).encode()
        req  = urllib.request.Request(
            "https://api.github.com/gists",
            data=body,
            headers={"Authorization": f"token {self._token}", "Content-Type": "application/json", "User-Agent": "jarvis"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                gist_id = json.loads(r.read())["id"]
            return f"{gist_id}:{fname}"
        except Exception as e:
            log.warning("GitHubGist upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._token or ":" not in ref:
            return None
        gist_id, fname = ref.split(":", 1)
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {self._token}", "User-Agent": "jarvis"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            content = data["files"][fname]["content"]
            return base64.b64decode(content)
        except Exception as e:
            log.warning("GitHubGist download failed: %s", e)
            return None


# ── Node 3: Email Draft ────────────────────────────────────────────────────────

class EmailDraftNode(ScatterNode):
    name = "EmailDraft"

    def __init__(self):
        self._addr     = os.getenv("EMAIL_ADDRESS", "")
        self._password = os.getenv("EMAIL_PASSWORD", "")
        self._imap     = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")

    def _check_available(self) -> bool:
        return bool(self._addr and self._password)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._check_available():
            return None
        import smtplib
        from email.mime.text import MIMEText
        subject = f"[JARVIS-SHARD-{index}] {hashlib.sha256(data).hexdigest()[:12]}"
        msg = MIMEText(base64.b64encode(data).decode())
        msg["Subject"] = subject
        msg["From"]    = self._addr
        msg["To"]      = self._addr
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(self._addr, self._password)
                smtp.send_message(msg)
            return subject
        except Exception as e:
            log.warning("EmailDraft upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._check_available():
            return None
        import imaplib
        try:
            with imaplib.IMAP4_SSL(self._imap, timeout=15) as imap:
                imap.login(self._addr, self._password)
                imap.select("INBOX")
                _, ids = imap.search(None, f'SUBJECT "{ref}"')
                if not ids[0]:
                    return None
                _, msg_data = imap.fetch(ids[0].split()[-1], "(RFC822)")
                from email import message_from_bytes
                msg = message_from_bytes(msg_data[0][1])
                return base64.b64decode(msg.get_payload())
        except Exception as e:
            log.warning("EmailDraft download failed: %s", e)
            return None


# ── Node 4: Pastebin ──────────────────────────────────────────────────────────

class PastebinNode(ScatterNode):
    name = "Pastebin"

    def __init__(self):
        self._key = os.getenv("PASTEBIN_API_KEY", "")

    def _check_available(self) -> bool:
        return bool(self._key)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._key:
            return None
        import urllib.request, urllib.parse
        content = base64.b64encode(data).decode()
        post    = urllib.parse.urlencode({
            "api_dev_key":       self._key,
            "api_option":        "paste",
            "api_paste_code":    content,
            "api_paste_private": "2",  # private
            "api_paste_expire_date": "N",
        }).encode()
        try:
            with urllib.request.urlopen("https://pastebin.com/api/api_post.php", data=post, timeout=15) as r:
                paste_url = r.read().decode().strip()
            paste_key = paste_url.split("/")[-1]
            return paste_key
        except Exception as e:
            log.warning("Pastebin upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._key:
            return None
        import urllib.request
        try:
            with urllib.request.urlopen(f"https://pastebin.com/raw/{ref}", timeout=15) as r:
                return base64.b64decode(r.read())
        except Exception as e:
            log.warning("Pastebin download failed: %s", e)
            return None


# ── Node 5: Tailscale Peer ────────────────────────────────────────────────────

class TailscaleNode(ScatterNode):
    name = "Tailscale"

    def __init__(self):
        devices_env = os.getenv("TAILSCALE_DEVICES", "")
        self._devices = [d.strip() for d in devices_env.split(",") if d.strip()]
        self._port = 47777
        self._store = Path.home() / ".jarvis_scatter" / "tailscale"
        self._store.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _check_available(self) -> bool:
        return bool(self._devices)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._devices:
            return None
        # Save locally and note the device it belongs to
        ref = f"ts_{index}_{secrets.token_hex(6)}"
        (self._store / ref).write_bytes(base64.b85encode(data))
        (self._store / ref).chmod(0o600)
        return ref

    def download(self, ref: str) -> Optional[bytes]:
        p = self._store / ref
        if p.exists():
            return base64.b85decode(p.read_bytes())
        return None


# ── Node 6: Local Backup ──────────────────────────────────────────────────────

class LocalBackupNode(ScatterNode):
    name = "LocalBackup"

    def __init__(self):
        backup_path = os.getenv("SCATTER_BACKUP_PATH", "")
        if backup_path:
            self._dir = Path(backup_path)
        else:
            self._dir = Path.home() / ".jarvis_scatter" / "backup"
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        ref = f"backup_{index}.bin"
        p = self._dir / ref
        p.write_bytes(base64.b85encode(data))
        p.chmod(0o600)
        return ref

    def download(self, ref: str) -> Optional[bytes]:
        p = self._dir / ref
        if not p.exists():
            return None
        return base64.b85decode(p.read_bytes())


# ── Node 7: Encrypted Cloud (iCloud) ─────────────────────────────────────────

class EncryptedCloudNode(ScatterNode):
    name = "EncryptedCloud"

    def __init__(self):
        icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        self._dir = icloud / ".jarvis_shards"
        try:
            self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._ok = True
        except Exception:
            self._ok = False

    def _check_available(self) -> bool:
        return self._ok

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._ok:
            return None
        ref = f"cloud_{index}.bin"
        p = self._dir / ref
        p.write_bytes(base64.b85encode(data))
        p.chmod(0o600)
        return ref

    def download(self, ref: str) -> Optional[bytes]:
        p = self._dir / ref
        if not p.exists():
            return None
        return base64.b85decode(p.read_bytes())


# ── Registry ──────────────────────────────────────────────────────────────────

_NODES: Optional[List[ScatterNode]] = None

def get_nodes() -> List[ScatterNode]:
    global _NODES
    if _NODES is None:
        _NODES = [
            LocalHiddenNode(),
            GitHubGistNode(),
            EmailDraftNode(),
            PastebinNode(),
            TailscaleNode(),
            LocalBackupNode(),
            EncryptedCloudNode(),
        ]
    return _NODES
