"""services/side_channel.py — timing-attack-resistant comparisons and
error-message sanitization.

Two pieces of this module are deliberately NOT wired into the request
hot path, despite the source spec suggesting it:
- add_timing_noise() sleeps 10-150ms on every call — wiring that into
  auth would add real, permanent latency to every single request this
  personal assistant ever serves, for a threat (network timing analysis
  of a personal API with no meaningful adversary volume) that doesn't
  really apply here.
- normalize_response_size() pads responses with trailing spaces to a
  fixed size — applied to a JSON response body, this either breaks JSON
  parsing outright or (if the client tolerates it) leaks the pre-padding
  boundary anyway once you know the target size, defeating the point.

constant_time_compare() IS wired into utils/security.py's actual token
checks (see verify_token/verify_master_only) — that one is genuinely free
(same big-O cost as a naive comparison) and a real, standard hardening
with no downside."""
import hmac
import random
import time


class SideChannelPrevention:

    def constant_time_compare(self, a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode(), b.encode())

    def add_timing_noise(self, min_ms: float = 50, max_ms: float = 150):
        """Available for a caller who specifically wants this on some
        rarely-hit sensitive endpoint — not applied automatically."""
        time.sleep(random.uniform(min_ms, max_ms) / 1000)

    def obfuscate_error_messages(self, error: str) -> str:
        """Generic error messages only — detailed errors can leak system
        internals to a scanner."""
        SAFE_ERRORS = {
            "not found": "Request could not be processed.",
            "unauthorized": "Authentication required.",
            "forbidden": "Access denied.",
            "rate limit": "Please wait before retrying.",
            "internal": "An error occurred. Please retry.",
            "invalid": "Invalid request.",
            "timeout": "Request timed out.",
        }
        error_lower = error.lower()
        for key, safe_msg in SAFE_ERRORS.items():
            if key in error_lower:
                return safe_msg
        return "Request could not be processed."


side_channel = SideChannelPrevention()
