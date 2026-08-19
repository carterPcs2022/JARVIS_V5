"""core/self_analysis.py — Level 1 of the self-programming sandbox.

JARVIS reads his own code and reports possible improvements. Read-only:
this module never writes to a file, never deploys anything, and never
runs any code it analyzes. See core/sandbox.py (Level 2, writes + tests
candidate changes in an isolated subprocess) and core/self_improvement.py
(Level 3, the review/approval/deploy cycle) for what happens after a
suggestion exists — nothing here can act on its own findings.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR

# Files JARVIS is allowed to analyze and, subject to Level 3's human
# approval gate, eventually propose changes to.
ALLOWED_FILES = [
    "core/llm/router.py",
    "core/brain_v2.py",
    "core/memory.py",
    "core/metacognition.py",
    "core/bayesian.py",
    "core/abductive.py",
    "core/mental_models.py",
    "core/working_memory.py",
    "core/narrative.py",
    "core/uncertainty.py",
    "core/first_principles.py",
    "core/cumulative.py",
    "core/fermi.py",
    "services/spotify.py",
    "services/news_anchor.py",
]

# Files JARVIS can never analyze-for-modification or write to, regardless
# of confidence — enforced again independently in core/sandbox.py, since
# this list being right is load-bearing for the "no Ultron scenarios" goal.
LOCKED_FILES = [
    "server/api.py",
    "core/protocols.py",
    "services/sentinel.py",
    "services/ai_firewall.py",
    "services/audit_log.py",
    "services/two_man_rule.py",
    "core/sandbox.py",
    "core/self_analysis.py",
    "core/self_improvement.py",
    "config/settings.py",
    ".env",
]

ANALYSIS_LOG = BASE_DIR / "logs" / "self_analysis.json"


class SelfAnalysis:

    def analyze_file(self, filepath: str) -> dict:
        """Analyze a single file for improvements. Read-only — never
        writes back, never executes the file."""
        from core.llm.router import think

        # Allowlist, not a denylist — this is reachable from a network
        # endpoint with a free-text filepath, so "not explicitly allowed"
        # is the safe default rather than "not explicitly locked" (which
        # a path like "../../.env" would slip past).
        if filepath not in ALLOWED_FILES:
            return {"error": f"File not analyzable: {filepath}"}

        path = BASE_DIR / filepath
        if not path.exists():
            return {"error": f"File not found: {filepath}"}

        code = path.read_text()

        analysis = think(
            f"You are analyzing your own code for improvements.\n"
            f"File: {filepath}\n\n"
            f"```python\n{code[:4000]}\n```\n\n"
            f"Identify:\n"
            f"1. Performance improvements\n"
            f"2. Logic bugs or edge cases\n"
            f"3. Missing error handling\n"
            f"4. Better algorithms\n"
            f"5. Code that could be more reliable\n\n"
            f"For each improvement:\n"
            f"- What line(s) to change\n"
            f"- What to change it to\n"
            f"- Why this is better\n"
            f"- Confidence (0-100%)\n"
            f"- Risk level (LOW/MEDIUM/HIGH)\n\n"
            f"Only suggest changes you're 80%+ confident in.\n"
            f"Only suggest LOW or MEDIUM risk changes.\n"
            f'Reply as JSON: {{"improvements": ['
            f'{{"description": "", "lines": "", "change": "", "reason": "", '
            f'"confidence": 0, "risk": "LOW"}}]}}',
            force_model="fable",
            max_tokens=4096,
        )

        # think() never raises on total provider failure — it returns a
        # "[JARVIS OFFLINE] ..." string (see core/llm/router.py's chat()),
        # which then fails json.loads() below and used to silently become
        # improvements: [] — indistinguishable from "analyzed this file
        # and found nothing," when actually nothing was analyzed at all.
        # Same stable-marker convention core/brain_v2.py and
        # services/self_audit.py already check for.
        offline = analysis.startswith("[JARVIS OFFLINE]")

        try:
            clean = re.sub(r"```json|```", "", analysis).strip()
            data = json.loads(clean)
        except Exception:
            data = {"improvements": [], "raw": analysis}

        result = {
            "file":         filepath,
            "improvements": [] if offline else data.get("improvements", []),
            "count":        0 if offline else len(data.get("improvements", [])),
            "error":        analysis if offline else None,
            "ts":           datetime.now().isoformat(),
        }

        self._log_analysis(result)
        return result

    def analyze_self(self) -> dict:
        """Analyze JARVIS's most important files. Weekly self-review.

        Each file's analyze_file() call is a real, independent LLM
        request (core/llm/router.py's think()) — running the 5 of them
        sequentially previously meant a single call (or its rate-limit
        fallback chain) added its full latency 5 times over. Confirmed
        live: a cycle with nothing to report still took ~2.5 minutes.
        They don't depend on each other, so running them concurrently
        via a thread pool cuts total latency to roughly the slowest
        single call instead of the sum of all five, without changing
        what gets analyzed or how."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_improvements = []
        failed_files = []
        files = [f for f in ALLOWED_FILES[:5] if (BASE_DIR / f).exists()]

        with ThreadPoolExecutor(max_workers=len(files) or 1) as pool:
            future_to_file = {pool.submit(self.analyze_file, f): f for f in files}
            for future in as_completed(future_to_file):
                filepath = future_to_file[future]
                try:
                    result = future.result()
                except Exception as e:
                    print(f"[SelfAnalysis] {filepath} analysis failed: {e}")
                    failed_files.append(filepath)
                    continue
                if result.get("error"):
                    failed_files.append(filepath)
                    continue
                for imp in result.get("improvements", []):
                    imp["file"] = filepath
                    all_improvements.append(imp)

        all_improvements.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        safe = [
            i for i in all_improvements
            if i.get("confidence", 0) >= 80 and i.get("risk", "HIGH") in ("LOW", "MEDIUM")
        ]

        if safe:
            from core.event_bus import bus
            bus.system(
                f"Self-analysis complete. Found {len(safe)} potential improvements. "
                f"Say 'JARVIS improve yourself' to write and test them."
            )

        return {
            "total_found":  len(all_improvements),
            "safe":         len(safe),
            "improvements": safe[:10],
            "failed_files": failed_files,
            "analyzed":     len(files) - len(failed_files),
            "ts":           datetime.now().isoformat(),
        }

    def find_bottlenecks(self) -> dict:
        """Find performance bottlenecks in the critical chat path. Read-only."""
        from core.llm.router import think

        router_code = (BASE_DIR / "core/llm/router.py").read_text()[:3000]
        brain_code  = (BASE_DIR / "core/brain_v2.py").read_text()[:3000]

        analysis = think(
            f"Analyze these critical path files for performance bottlenecks:\n\n"
            f"Router:\n{router_code}\n\n"
            f"Brain:\n{brain_code}\n\n"
            f"What is slowing JARVIS down? What would have the biggest impact "
            f"on response speed? Specific, actionable improvements only.",
            force_model="opus",
            max_tokens=2048,
        )
        return {"bottlenecks": analysis}

    def _log_analysis(self, result: dict):
        log = []
        if ANALYSIS_LOG.exists():
            try:
                log = json.loads(ANALYSIS_LOG.read_text())
            except Exception:
                log = []
        log.append(result)
        ANALYSIS_LOG.parent.mkdir(parents=True, exist_ok=True)
        ANALYSIS_LOG.write_text(json.dumps(log[-100:], indent=2))


self_analysis = SelfAnalysis()
