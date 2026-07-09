"""services/gold_codes.py — TOTP-based second factor for critical actions
(Coldfire, DEFCON changes, etc), same algorithm as Google Authenticator/
Authy. Genuinely functional: standard RFC 6238 TOTP, not decorative.
Disabled (verify() always passes) when GOLD_CODE_SECRET isn't set, so it's
opt-in rather than an accidental lockout."""
import os
import time
import hmac
import hashlib
import base64
import struct

GOLD_SECRET = os.getenv("GOLD_CODE_SECRET", "")


class GoldCodes:

    def generate_current(self) -> str:
        """Current 6-digit TOTP code. Changes every 30 seconds."""
        if not GOLD_SECRET:
            return ""
        try:
            key = base64.b32decode(GOLD_SECRET.upper(), True)
            counter = int(time.time()) // 30
            mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
            offset = mac[-1] & 0x0f
            code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7fffffff) % 1000000
            return f"{code:06d}"
        except Exception:
            return ""

    def verify(self, provided: str, window: int = 1) -> bool:
        """Accepts the current code plus `window` codes on either side to
        allow for clock drift."""
        if not GOLD_SECRET:
            return True  # Disabled if not configured

        provided = (provided or "").strip().replace(" ", "")
        if len(provided) != 6 or not provided.isdigit():
            return False

        try:
            key = base64.b32decode(GOLD_SECRET.upper(), True)
        except Exception:
            return False

        now = int(time.time()) // 30
        for delta in range(-window, window + 1):
            mac = hmac.new(key, struct.pack(">Q", now + delta), hashlib.sha1).digest()
            offset = mac[-1] & 0x0f
            expected = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7fffffff) % 1000000
            if hmac.compare_digest(str(expected).zfill(6), provided):
                return True
        return False

    def get_setup_uri(self, account: str = "JARVIS", issuer: str = "StarkIndustries") -> str:
        """otpauth:// URI — scan directly in Google Authenticator/Authy."""
        if not GOLD_SECRET:
            return ""
        return (f"otpauth://totp/{issuer}:{account}?secret={GOLD_SECRET}"
                f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30")

    def time_remaining(self) -> int:
        return 30 - (int(time.time()) % 30)


gold_codes = GoldCodes()
