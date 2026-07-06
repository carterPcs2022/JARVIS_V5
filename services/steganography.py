"""services/steganography.py — invisible zero-width-Unicode watermarks
for detecting response tampering in transit.

NOT wired into core/brain_v2.py to watermark every response by default.
The threat model this defends against (a man-in-the-middle modifying
JARVIS's responses after they leave the server) doesn't really apply here
— this is a personal assistant talking to its own HUD/phone client over
HTTPS, not a system relaying through an untrusted intermediary. Meanwhile
the actual cost is real: zero-width characters survive copy-paste and can
trip spam/content filters or look like mojibake if a client mishandles
Unicode. Available as an opt-in utility instead."""
import hashlib
from datetime import datetime

_ZERO_WIDTH = {"0": "​", "1": "‌"}
_ZERO_WIDTH_MAP = {v: k for k, v in _ZERO_WIDTH.items()}


class Steganography:

    def watermark_response(self, text: str, session_id: str = "") -> str:
        if not text:
            return text

        ts = datetime.now().strftime("%Y%m%d%H%M")
        signature = hashlib.sha256(f"{text[:50]}{session_id}{ts}".encode()).hexdigest()[:8]
        watermark = f"JARVIS:{signature}:{ts}"

        binary = "".join(format(ord(c), "08b") for c in watermark[:20])
        invisible = "".join(_ZERO_WIDTH[b] for b in binary)

        sentences = text.split(". ", 1)
        if len(sentences) > 1:
            return sentences[0] + ". " + invisible + sentences[1]
        return text + invisible

    def extract_watermark(self, text: str) -> dict:
        binary = "".join(_ZERO_WIDTH_MAP.get(c, "") for c in text if c in _ZERO_WIDTH_MAP)
        if not binary:
            return {"watermarked": False}

        try:
            chars = [chr(int(binary[i:i + 8], 2)) for i in range(0, len(binary) - 7, 8)]
            watermark = "".join(chars)
            parts = watermark.split(":")
            if len(parts) >= 3 and parts[0] == "JARVIS":
                return {"watermarked": True, "signature": parts[1], "timestamp": parts[2], "authentic": True}
        except Exception:
            pass

        return {"watermarked": True, "authentic": False, "tampered": True}

    def verify_response_chain(self, responses: list[str]) -> dict:
        results = [self.extract_watermark(r) for r in responses]
        return {
            "chain_length": len(responses),
            "all_authentic": all(r.get("authentic", False) for r in results),
            "tampered": sum(1 for r in results if r.get("tampered", False)),
            "details": results,
        }


stegano = Steganography()
