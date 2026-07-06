"""services/self_audit.py — JARVIS reads his own code with an LLM and
reports vulnerabilities. Manual/on-demand only (see module docstring in
server/routes/security_max.py for why this isn't auto-scheduled nightly):
full_audit() alone is ~9 paid Anthropic calls (one per critical file) plus
a summary call — running that unattended every night would eat a large
chunk of the daily Opus/Fable call caps on its own."""
import json
import re
from pathlib import Path
from datetime import datetime

from config.settings import BASE_DIR

AUDIT_LOG = BASE_DIR / "logs" / "security_audit.json"

CRITICAL_FILES = [
    "server/api.py",
    "server/routes/chat.py",
    "server/routes/voice.py",
    "server/routes/glasses.py",
    "core/brain_v2.py",
    "core/llm/router.py",
    "config/settings.py",
    "services/sentinel.py",
]

_SECRET_PATTERNS = {
    "api_key": r'(?i)(api[_-]?key|apikey)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']',
    "password": r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{6,})["\']',
    "token": r'(?i)(token|secret)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']',
    "private_key": r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
    "groq_key": r"gsk_[a-zA-Z0-9]{48}",
    "anthropic_key": r"sk-ant-[a-zA-Z0-9\-]{48}",
    "elevenlabs_key": r"sk_[a-zA-Z0-9]{48}",
}

_SKIP_DIRS = (".git", "venv", ".venv", "__pycache__", "node_modules", ".env")


class SelfAudit:

    def audit_file(self, filepath: str) -> dict:
        """Use the top reasoning tier to analyze a single file for
        vulnerabilities. Uses "opus" (not "fable") — this runs across
        several files per audit, and opus is a third the cost for
        code-review-quality output that doesn't need fable's ceiling."""
        from core.llm.router import think

        path = BASE_DIR / filepath
        if not path.exists():
            return {"file": filepath, "error": "not found"}

        code = path.read_text()[:4000]

        analysis = think(
            f"You are a security researcher auditing Python code.\n"
            f"Analyze this file for security vulnerabilities:\n\n"
            f"File: {filepath}\nCode:\n{code}\n\n"
            f"Check for:\n"
            f"1. Authentication bypass vulnerabilities\n"
            f"2. Injection vulnerabilities (SQL, command, prompt)\n"
            f"3. Exposed secrets or credentials\n"
            f"4. Insecure deserialization\n"
            f"5. Race conditions\n"
            f"6. Missing input validation\n"
            f"7. Overly permissive access controls\n"
            f"8. Insecure default configurations\n"
            f"9. Logic errors that could be exploited\n"
            f"10. Missing rate limiting\n\n"
            f"For each finding: severity (CRITICAL/HIGH/MEDIUM/LOW), "
            f"description, line number if visible, fix recommendation.\n"
            f"Reply as JSON: {{\"findings\": [{{\"severity\":str, \"description\":str, "
            f"\"location\":str, \"fix\":str}}], \"overall_risk\": str}}",
            force_model="opus",
        )

        try:
            clean = re.sub(r"```json|```", "", analysis).strip()
            result = json.loads(clean)
        except Exception:
            result = {"findings": [], "raw": analysis, "overall_risk": "unknown"}

        result["file"] = filepath
        result["ts"] = datetime.now().isoformat()
        return result

    def full_audit(self) -> dict:
        """Complete self-audit of all critical files. Call manually via
        POST /stark/security/audit, or schedule it yourself if you're
        comfortable with the daily Opus call cost."""
        from core.event_bus import bus

        bus.system("Initiating security self-audit. Analyzing all critical systems.")

        all_findings = []
        critical_count = 0

        for filepath in CRITICAL_FILES:
            print(f"[Audit] Scanning: {filepath}")
            result = self.audit_file(filepath)
            findings = result.get("findings", [])
            for f in findings:
                f["file"] = filepath
                if f.get("severity") == "CRITICAL":
                    critical_count += 1
                all_findings.append(f)

        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        all_findings.sort(key=lambda x: severity_order.get(x.get("severity", "LOW"), 3))

        from core.llm.router import think
        summary = think(
            f"Generate a security audit summary report in JARVIS/Stark Industries style:\n\n"
            f"Total findings: {len(all_findings)}\nCritical: {critical_count}\n"
            f"Top findings:\n"
            + "\n".join(f"- [{f.get('severity','')}] {f.get('description','')[:100]}" for f in all_findings[:5]) +
            f"\n\nBe direct. Prioritize ruthlessly. Tony Stark doesn't want fluff.",
            force_model="standard",
        )

        report = {
            "ts": datetime.now().isoformat(), "total": len(all_findings),
            "critical": critical_count, "findings": all_findings,
            "summary": summary, "files_scanned": len(CRITICAL_FILES),
        }

        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_LOG.write_text(json.dumps(report, indent=2))

        if critical_count > 0:
            bus.alert(
                f"Security audit complete. {critical_count} critical finding(s) detected. "
                f"Immediate attention required.",
                severity="critical", category="SECURITY_AUDIT",
            )

        try:
            from services.siem import siem
            siem.log_event("SECURITY_AUDIT", details={"critical": critical_count, "total": len(all_findings)},
                          severity="CRITICAL" if critical_count else "INFO")
        except Exception:
            pass

        return report

    def last_audit(self) -> dict | None:
        if AUDIT_LOG.exists():
            try:
                return json.loads(AUDIT_LOG.read_text())
            except Exception:
                return None
        return None

    def scan_for_secrets(self) -> list[dict]:
        """Scan the repo for hardcoded secrets — Ivan Vanko's first step
        would be finding exposed credentials. Cheap (regex only, no LLM
        calls) — safe to run automatically."""
        findings = []
        for py_file in BASE_DIR.rglob("*.py"):
            if any(skip in py_file.parts for skip in _SKIP_DIRS):
                continue
            try:
                content = py_file.read_text()
            except Exception:
                continue
            for secret_type, pattern in _SECRET_PATTERNS.items():
                if re.search(pattern, content):
                    findings.append({
                        "file": str(py_file.relative_to(BASE_DIR)), "type": secret_type,
                        "severity": "CRITICAL", "description": f"Hardcoded {secret_type} found",
                    })
        return findings


audit = SelfAudit()
