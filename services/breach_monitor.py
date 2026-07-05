"""services/breach_monitor.py — checks emails against known data breaches
(HaveIBeenPwned) and password strength (k-anonymity range API — the
plaintext password is never sent anywhere, only a 5-char SHA-1 prefix)."""
import hashlib
import os

import httpx


class BreachMonitor:

    def check_email(self, email: str) -> dict:
        try:
            r = httpx.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers={"hibp-api-key": os.getenv("HIBP_API_KEY", ""), "User-Agent": "JARVIS-SecurityMonitor"},
                timeout=10,
            )
            if r.status_code == 200:
                breaches = r.json()
                if breaches:
                    from core.event_bus import bus
                    bus.alert(f"Email {email} found in {len(breaches)} data breach(es)!", severity="high", category="SECURITY")
                return {
                    "email": email, "breached": bool(breaches), "count": len(breaches) if breaches else 0,
                    "breaches": [b.get("Name", "") for b in (breaches or [])[:5]],
                }
            if r.status_code == 404:
                return {"email": email, "breached": False, "count": 0}
            if r.status_code == 401:
                return {"error": "HIBP_API_KEY not set or invalid — sign up at haveibeenpwned.com/API/Key"}
            return {"error": f"HaveIBeenPwned returned {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def check_password_strength(self, password: str) -> dict:
        length = len(password)
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(not c.isalnum() for c in password)

        score = sum([length >= 12, length >= 16, has_upper, has_lower, has_digit, has_special])

        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        try:
            r = httpx.get(f"https://api.pwnedpasswords.com/range/{prefix}", timeout=10)
            pwned = suffix in r.text
        except Exception:
            pwned = False

        return {
            "score": f"{score}/6",
            "strength": ["Very Weak", "Weak", "Fair", "Good", "Strong", "Very Strong", "Excellent"][min(score, 6)],
            "pwned": pwned, "length": length,
        }


breach_monitor = BreachMonitor()
