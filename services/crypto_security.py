"""services/crypto_security.py — HMAC request signing (for a phone
Shortcut or other client to sign requests before sending), replay
protection, per-device tokens, and at-rest encryption for sensitive data."""
import hashlib
import hmac
import secrets
import time
from base64 import b64encode

from config.settings import SECRET_KEY


class CryptoSecurity:

    def sign_request(self, body: str, timestamp: int | None = None) -> str:
        """Sign a request body with JARVIS's secret key — use this
        client-side (e.g. an iPhone Shortcut) before sending."""
        ts = timestamp or int(time.time())
        msg = f"{ts}.{body}".encode()
        sig = hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).digest()
        return f"{ts}.{b64encode(sig).decode()}"

    def verify_signature(self, body: str, signature: str, max_age_seconds: int = 300) -> bool:
        """Verify a signed request. Rejects wrong signatures and replayed
        (stale) requests."""
        try:
            ts_str, sig_b64 = signature.split(".", 1)
            ts = int(ts_str)

            if abs(time.time() - ts) > max_age_seconds:
                return False

            expected = self.sign_request(body, ts)
            _, expected_sig = expected.split(".", 1)
            return hmac.compare_digest(sig_b64, expected_sig)
        except Exception:
            return False

    def generate_device_token(self, device_name: str) -> dict:
        """A distinct token per device — compromising one doesn't
        compromise others. Note: this only generates a credential; it
        isn't wired into utils/security.py's auth check, which still uses
        the single JARVIS_API_TOKEN. Rotating to per-device tokens would
        need utils/security.py updated to check against a device-token
        store instead of one shared secret — a bigger change than this
        batch, left as a deliberate scope boundary."""
        from datetime import datetime
        token = secrets.token_urlsafe(32)
        device_id = hashlib.sha256(f"{device_name}{time.time()}".encode()).hexdigest()[:16]
        return {
            "device": device_name, "device_id": device_id, "token": token,
            "created": datetime.now().isoformat(), "type": "device_token",
        }

    def encrypt_sensitive(self, data: str) -> str:
        from cryptography.fernet import Fernet
        key = b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
        return Fernet(key).encrypt(data.encode()).decode()

    def decrypt_sensitive(self, encrypted: str) -> str:
        from cryptography.fernet import Fernet
        key = b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
        return Fernet(key).decrypt(encrypted.encode()).decode()


crypto = CryptoSecurity()
