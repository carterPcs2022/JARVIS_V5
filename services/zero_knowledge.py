"""services/zero_knowledge.py — challenge-response auth: prove you know a
secret without ever transmitting it, so an intercepted request leaks
nothing usable. Available standalone (GET /stark/auth/challenge, POST
/stark/auth/verify) — not wired as a replacement for the existing bearer-
token auth, since no client (iPhone Shortcut, HUD) currently implements
the challenge-solving side; wiring it in as required would lock out every
existing client immediately."""
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from config.settings import BASE_DIR

ZK_SESSIONS_FILE = BASE_DIR / "memory" / "zk_sessions.json"


class ZeroKnowledgeAuth:

    def create_challenge(self, session_id: str = "") -> dict:
        challenge = secrets.token_hex(32)
        nonce = secrets.token_hex(16)
        session = session_id or secrets.token_hex(8)
        ts = int(time.time())

        sessions = self._load()
        sessions[session] = {"challenge": challenge, "nonce": nonce, "ts": ts, "expires": ts + 60, "used": False}
        self._save(sessions)

        return {"session_id": session, "challenge": challenge, "nonce": nonce, "expires_in": 60}

    def solve_challenge(self, secret: str, challenge: str, nonce: str) -> str:
        """Call this client-side with your actual secret — never send the
        secret itself, only the solution."""
        return hashlib.sha3_256(f"{secret}:{challenge}:{nonce}".encode()).hexdigest()

    def verify_proof(self, session_id: str, proof: str, secret_hash: str) -> dict:
        """secret_hash is the server's stored hash of the secret — never
        the secret itself."""
        sessions = self._load()
        session = sessions.get(session_id)

        if not session:
            return {"verified": False, "reason": "session_not_found"}
        if time.time() > session["expires"]:
            return {"verified": False, "reason": "challenge_expired"}
        if session["used"]:
            return {"verified": False, "reason": "challenge_already_used"}

        expected = hashlib.sha3_256(f"{secret_hash}:{session['challenge']}:{session['nonce']}".encode()).hexdigest()
        verified = hmac.compare_digest(proof, expected)

        session["used"] = True
        sessions[session_id] = session
        self._save(sessions)

        return {"verified": verified, "session": session_id, "timestamp": int(time.time())}

    def _load(self) -> dict:
        if ZK_SESSIONS_FILE.exists():
            try:
                data = json.loads(ZK_SESSIONS_FILE.read_text())
            except Exception:
                return {}
            now = time.time()
            return {k: v for k, v in data.items() if v.get("expires", 0) > now}
        return {}

    def _save(self, sessions: dict):
        ZK_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ZK_SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


zk_auth = ZeroKnowledgeAuth()
