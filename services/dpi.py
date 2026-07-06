"""services/dpi.py — Deep Packet Inspection.

Analyzes request payload structure/encoding (not just keyword content) and
monitors outbound responses for leaked secrets/PII. Complements
services/ai_firewall.py (which screens intent) by screening payload shape.
"""
import re
import math
from collections import Counter


class DeepPacketInspector:

    ENCODING_PATTERNS = [
        r"base64[,:]",
        r"\\x[0-9a-fA-F]{2}",   # hex encoding
        r"%[0-9a-fA-F]{2}",     # URL encoding in body
        r"\\u[0-9a-fA-F]{4}",   # unicode escapes
        r"\{\{.*\}\}",          # template injection
        r"\$\{.*\}",            # expression injection
    ]

    SUSPICIOUS_STRUCTURES = [
        r"<script", r"javascript:", r"data:text/html", r"vbscript:",
        r"\beval\s*\(", r"\bexec\s*\(", r"os\.system", r"subprocess",
        r"__import__",
    ]

    def inspect(self, payload: str, endpoint: str = "") -> dict:
        """Deep inspection of request payload. Returns threat assessment."""
        findings = []

        for pattern in self.ENCODING_PATTERNS:
            if re.search(pattern, payload, re.IGNORECASE):
                findings.append({"type": "ENCODING_ANOMALY", "pattern": pattern, "severity": "medium"})

        for pattern in self.SUSPICIOUS_STRUCTURES:
            if re.search(pattern, payload, re.IGNORECASE):
                findings.append({"type": "INJECTION_STRUCTURE", "pattern": pattern, "severity": "high"})

        json_count = payload.count('{"')
        if json_count > 5:
            findings.append({"type": "NESTED_JSON", "count": json_count, "severity": "medium"})

        non_printable = sum(1 for c in payload if ord(c) < 32 and c not in "\n\r\t")
        if non_printable > 5:
            findings.append({"type": "BINARY_IN_TEXT", "count": non_printable, "severity": "high"})

        entropy = self._entropy(payload[:500])
        if entropy > 4.5 and len(payload) > 100:
            findings.append({
                "type": "HIGH_ENTROPY", "entropy": entropy, "severity": "medium",
                "note": "Possible encrypted/obfuscated content",
            })

        risk = "none"
        if any(f["severity"] == "high" for f in findings):
            risk = "high"
        elif findings:
            risk = "medium"

        return {
            "payload_length": len(payload), "findings": findings,
            "risk": risk, "entropy": entropy, "safe": risk == "none",
        }

    def _entropy(self, text: str) -> float:
        if not text:
            return 0
        counts = Counter(text)
        total = len(text)
        entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
        return round(entropy, 3)

    def monitor_response(self, response: str) -> dict:
        """Egress scan of an outbound response for API-key patterns not
        already covered by core.protocols.shield's redaction (that covers
        credit_card/ssn/password/api_key already at the response-shielding
        call site — this adds a few provider-specific key formats it
        doesn't enumerate individually, for defense in depth)."""
        leaks = []
        API_KEY_PATTERNS = [
            r"sk-[a-zA-Z0-9]{20,}", r"gsk_[a-zA-Z0-9]{20,}",
            r"sk_[a-zA-Z0-9]{20,}", r"tvly-[a-zA-Z0-9]{20,}",
            r"ghp_[a-zA-Z0-9]{20,}",
        ]
        for pattern in API_KEY_PATTERNS:
            if re.search(pattern, response):
                leaks.append({"type": "API_KEY_LEAK", "severity": "critical"})

        PERSONAL_PATTERNS = {
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
            "ssn":   r"\b\d{3}-\d{2}-\d{4}\b",
            "cc":    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        }
        for data_type, pattern in PERSONAL_PATTERNS.items():
            matches = re.findall(pattern, response)
            if len(matches) > 2:  # a couple of false positives are expected
                leaks.append({"type": f"PII_LEAK_{data_type.upper()}", "count": len(matches), "severity": "high"})

        if leaks:
            try:
                from core.event_bus import bus
                bus.alert(
                    f"EGRESS ALERT: Response contains potential sensitive data: {[l['type'] for l in leaks]}",
                    severity="critical", category="EGRESS_FILTER",
                )
            except Exception:
                pass

        return {"leaks": leaks, "clean": not leaks}


dpi = DeepPacketInspector()
