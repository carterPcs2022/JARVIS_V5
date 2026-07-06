"""services/egress_filter.py — outbound traffic filtering.

Response redaction reuses core.protocols.shield (Protocol 26) rather than
maintaining a second, divergent copy of the same credit_card/ssn/password/
api_key regex list — Shield already redacts on the input/storage side;
this applies the identical patterns to the outbound response. The
domain-whitelist check for outbound HTTP requests is the genuinely new
piece here.
"""
from urllib.parse import urlparse

ALLOWED_DOMAINS = [
    "api.groq.com", "api.anthropic.com", "api.elevenlabs.io", "api.openai.com",
    "canarytokens.org", "api.pushover.net", "api.github.com", "api.spotify.com",
    "accounts.spotify.com", "api.aviationstack.com", "api.abuseipdb.com",
    "haveibeenpwned.com", "api.pwnedpasswords.com", "wttr.in", "serper.dev",
    "api.tavily.com",
]


class EgressFilter:

    def filter(self, response: str) -> dict:
        """Redact sensitive data from an outbound response before it's
        shown to the user. Returns {response, redacted, clean}."""
        from core.protocols import shield
        redacted_response = shield.scan_and_redact(response)
        redacted = redacted_response != response
        return {
            "response": redacted_response,
            "redacted": redacted,
            "clean": not redacted,
        }

    def check_outbound_request(self, url: str, data: dict | None = None) -> dict:
        """Check any outbound HTTP request JARVIS makes against a domain
        whitelist. Not enforced automatically on every httpx call site
        (that would need wrapping every external API client in the
        codebase) — call this explicitly before requests to
        user-influenced/dynamic URLs."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        allowed = any(domain == d or domain.endswith(f".{d}") for d in ALLOWED_DOMAINS)

        if not allowed:
            self._alert_outbound(url, domain)
            return {"allowed": False, "domain": domain, "reason": f"Domain {domain} not in whitelist"}

        return {"allowed": True, "domain": domain}

    def _alert_outbound(self, url: str, domain: str):
        try:
            from core.event_bus import bus
            bus.alert(
                f"EGRESS FILTER: Unauthorized outbound request to {domain} blocked. URL: {url[:100]}",
                severity="critical", category="EGRESS_OUTBOUND",
            )
        except Exception:
            pass


egress = EgressFilter()
