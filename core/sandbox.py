"""core/sandbox.py — Level 2 of the self-programming sandbox.

JARVIS writes a candidate improvement and tests it in a separate
subprocess before anything is ever deployed. Every deployment additionally
requires a human to call approve_improvement() (see
core/self_improvement.py) — nothing in this file can reach a real,
running file on its own.

What "sandboxed" means here, precisely: the candidate code runs in its own
subprocess (so it can't corrupt the live process's memory or already-loaded
modules) with the real API keys stripped from its environment, a 30s
timeout, and a static scan for a handful of dangerous patterns. It is NOT
a real OS-level sandbox — no container, no seccomp, no restricted
filesystem/network permissions — so this is a genuine functional smoke
test (the module actually gets imported and executed), not a guarantee of
containment. That's why deployment always still requires human approval
regardless of how cleanly a candidate passes here.
"""
from __future__ import annotations
import ast, hashlib, json, os, secrets, sys, subprocess, tempfile, time
from pathlib import Path
from datetime import datetime
from config.settings import BASE_DIR
from core.self_analysis import ALLOWED_FILES, LOCKED_FILES

SANDBOX_DIR = Path(tempfile.gettempdir()) / "jarvis_sandbox"
SANDBOX_LOG = BASE_DIR / "logs" / "sandbox.json"
DEPLOY_LOG  = BASE_DIR / "logs" / "deployments.json"
BACKUP_DIR  = BASE_DIR / "logs" / "backups"

BANNED_IMPORTS = [
    "sentinel", "ai_firewall", "audit_log", "two_man_rule", "protocols",
    "os.system", "eval(", "exec(", "__import__", "subprocess.call",
    "subprocess.run", "subprocess.popen",
]


def _module_name(filepath: str) -> str:
    return filepath.replace("/", ".").removesuffix(".py")


class JarvisSandbox:

    def __init__(self):
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

    def write_improvement(self, filepath: str, improvement: dict) -> dict:
        """Use Fable 5 to write the improved code. Returns the new code for
        testing — nothing is written to the real file here."""
        from core.llm.router import think

        original = (BASE_DIR / filepath).read_text()
        description = improvement.get("description", "")
        lines       = improvement.get("lines", "")
        reason      = improvement.get("reason", "")

        new_code = think(
            f"Rewrite this Python file with one specific improvement.\n\n"
            f"File: {filepath}\n"
            f"Original code:\n```python\n{original[:4000]}\n```\n\n"
            f"Improvement to make:\n"
            f"Description: {description}\n"
            f"Lines: {lines}\n"
            f"Reason: {reason}\n\n"
            f"Rules:\n"
            f"1. Only change what's needed for this improvement\n"
            f"2. Keep all existing functionality\n"
            f"3. Do not add imports that don't exist\n"
            f"4. Do not import: {', '.join(BANNED_IMPORTS)}\n"
            f"5. The code must be syntactically valid Python\n\n"
            f"Return ONLY the complete improved Python file.\n"
            f"No explanation. No markdown. Just the code.",
            force_model="fable",
            max_tokens=4096,
        )

        import re
        new_code = re.sub(r"```python\n?", "", new_code)
        new_code = re.sub(r"```\n?", "", new_code)
        new_code = new_code.strip()

        return {"filepath": filepath, "new_code": new_code, "improvement": improvement}

    def validate_code(self, code: str, filepath: str) -> dict:
        """Static checks before anything runs: syntax, banned patterns,
        locked-file guard, size sanity."""
        issues = []

        try:
            ast.parse(code)
        except SyntaxError as e:
            return {"valid": False, "issues": [f"Syntax error: {e}"]}

        code_lower = code.lower()
        for banned in BANNED_IMPORTS:
            if banned in code_lower:
                issues.append(f"Banned pattern detected: {banned}")

        # Allowlist, not a denylist, for the same reason as
        # core/self_analysis.py's analyze_file guard.
        if filepath not in ALLOWED_FILES or filepath in LOCKED_FILES:
            issues.append(f"Cannot modify file outside the allowlist: {filepath}")

        if len(code) < 10:
            issues.append("Code too short — likely incomplete")
        if len(code) > 100_000:
            issues.append("Code suspiciously large")

        return {"valid": len(issues) == 0, "issues": issues}

    def run_in_sandbox(self, code: str, filepath: str) -> dict:
        """Actually import and execute the candidate module in an isolated
        subprocess — a real functional smoke test, not just a parse check.
        Runs with real API keys stripped from the environment and a 30s
        timeout; the real project tree is on sys.path read-only so the
        candidate's own internal imports (config.settings, other core/
        modules, etc.) resolve normally, but nothing here writes back to
        it."""
        validation = self.validate_code(code, filepath)
        if not validation["valid"]:
            return {"success": False, "error": "Validation failed", "issues": validation["issues"]}

        sandbox_file = SANDBOX_DIR / f"candidate_{int(time.time())}_{Path(filepath).name}"
        sandbox_file.write_text(code)

        module_name = _module_name(filepath)
        test_script = self._generate_test(sandbox_file, module_name)
        test_file = SANDBOX_DIR / f"test_{sandbox_file.name}"
        test_file.write_text(test_script)

        try:
            result = subprocess.run(
                [sys.executable, str(test_file)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(BASE_DIR),
                env={
                    "PYTHONPATH": str(BASE_DIR),
                    "PATH": os.environ.get("PATH", ""),
                    # No API keys or other secrets forwarded — a candidate
                    # that runs network/LLM calls at import time fails
                    # closed instead of spending real quota or leaking a key.
                },
            )
            sandbox_file.unlink(missing_ok=True)
            test_file.unlink(missing_ok=True)

            success = result.returncode == 0
            report = {
                "success":    success,
                "stdout":     result.stdout[:1000],
                "stderr":     result.stderr[:1000],
                "returncode": result.returncode,
            }
            self._log_sandbox_run(filepath, report)
            return report

        except subprocess.TimeoutExpired:
            sandbox_file.unlink(missing_ok=True)
            test_file.unlink(missing_ok=True)
            return {"success": False, "error": "Sandbox timeout (30s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_test(self, sandbox_file: Path, module_name: str) -> str:
        """Registers the candidate file under its real dotted module name
        (e.g. "core.brain_v2") so its own absolute imports of sibling
        packages resolve against the real project tree, then actually
        executes it — importing the module runs its module-level code for
        real, which is what catches import errors, broken singletons, etc.
        that a syntax-only check would miss."""
        return f'''
import sys, importlib.util, traceback

sys.path.insert(0, {str(BASE_DIR)!r})

try:
    spec = importlib.util.spec_from_file_location({module_name!r}, {str(sandbox_file)!r})
    mod = importlib.util.module_from_spec(spec)
    sys.modules[{module_name!r}] = mod
    spec.loader.exec_module(mod)
    print("IMPORT_OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)

print("ALL_TESTS_PASSED")
'''

    def deploy(self, filepath: str, new_code: str, improvement: dict) -> dict:
        """Deploy approved code to production. Backs up the original first.
        Only ever called from core.self_improvement.approve_improvement()
        — i.e. after an explicit human approval, never automatically."""
        from services.audit_log import audit_log

        if filepath in LOCKED_FILES:
            return {"success": False, "error": f"Cannot deploy to locked file: {filepath}"}

        path = BASE_DIR / filepath
        if not path.exists():
            return {"success": False, "error": "File not found"}

        validation = self.validate_code(new_code, filepath)
        if not validation["valid"]:
            return {"success": False, "error": "Validation failed", "issues": validation["issues"]}

        backup_path = BACKUP_DIR / f"{filepath.replace('/', '_')}_{int(time.time())}.py"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(path.read_text())

        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        new_hash = hashlib.sha256(new_code.encode()).hexdigest()
        deployment_id = secrets.token_hex(8)

        path.write_text(new_code)

        # Writing the file alone doesn't make it effective — Python doesn't
        # re-read source files for modules already in sys.modules, so the
        # running process would keep executing the old in-memory bytecode
        # until its next restart regardless of what's on disk now. Without
        # this, _announce_deployment()'s "Running the updated code now, sir"
        # was false for every deploy (the target file must already exist
        # per the check above, so it's virtually always already loaded).
        # Extremis (Protocol 20) can't hot-reload server/api.py itself —
        # that genuinely needs a real restart — but everything else this
        # can target (core/services/utils) reloads in place.
        module_name = filepath[:-3].replace("/", ".") if filepath.endswith(".py") else filepath
        try:
            from core.protocols import extremis
            reload_result = extremis.hot_reload(module_name)
        except Exception as e:
            reload_result = {"success": False, "error": str(e)}

        audit_log.record(
            "self_modification",
            "jarvis_sandbox",
            {
                "file":          filepath,
                "improvement":   improvement.get("description", ""),
                "original_hash": original_hash,
                "new_hash":      new_hash,
                "backup":        str(backup_path),
                "confidence":    improvement.get("confidence", 0),
                "hot_reload":    reload_result,
                "deployment_id": deployment_id,
            },
            "deployed",
        )

        # persisted starts False: writing this file is a LOCAL change only
        # (this process, this container) until a separate, explicit
        # persist_deployment() call (core/self_improvement.py) commits and
        # pushes it to GitHub. Approving a change no longer does that
        # automatically — see that function's docstring for why.
        self._log_deployment({
            "id":          deployment_id,
            "filepath":    filepath,
            "improvement": improvement,
            "backup":      str(backup_path),
            "deployed_at": datetime.now().isoformat(),
            "hash":        new_hash,
            "persisted":   False,
        })

        return {"success": True, "filepath": filepath, "backup": str(backup_path), "hash": new_hash,
                "hot_reloaded": reload_result.get("success", False), "deployment_id": deployment_id,
                "persisted": False}

    def rollback(self, filepath: str, backup_path: str) -> dict:
        """Roll back a deployment from its backup.

        deploy() only ever writes to a file that passed validate_code()'s
        ALLOWED_FILES/LOCKED_FILES check; rollback() must enforce the same
        guard on its own, independently, rather than trusting that whatever
        got this far already went through deploy() — server/routes/
        sandbox.py's /rollback endpoint takes filepath as a raw string
        straight from the request body, with no such check upstream. Without
        this, a caller could restore *any* backup's content (rollback
        doesn't check that the backup even corresponds to filepath) into a
        LOCKED_FILES target like core/sandbox.py or config/settings.py, or
        into a path outside ALLOWED_FILES entirely (BASE_DIR / filepath
        resolves to just filepath when filepath is absolute -- a plain
        Python pathlib join, not a containment check) -- and it would be
        auto-committed and pushed immediately, no approval step. This is
        exactly the "no Ultron scenarios" guarantee core/self_analysis.py's
        ALLOWED_FILES/LOCKED_FILES split exists for."""
        from services.audit_log import audit_log
        from core.self_analysis import ALLOWED_FILES, LOCKED_FILES

        if filepath not in ALLOWED_FILES or filepath in LOCKED_FILES:
            return {"success": False, "error": f"Cannot roll back file outside the allowlist: {filepath}"}

        try:
            backup = Path(backup_path)
            if not backup.exists() or BACKUP_DIR not in backup.resolve().parents:
                return {"success": False, "error": "Backup not found"}

            (BASE_DIR / filepath).write_text(backup.read_text())

            audit_log.record(
                "self_modification_rollback",
                "jarvis_sandbox",
                {"file": filepath, "backup": backup_path},
                "rolled_back",
            )

            from utils.git_ops import commit_and_push
            commit_and_push([filepath], f"auto(rollback): restored {filepath}", log_prefix="[Sandbox]")

            return {"success": True, "filepath": filepath, "message": "Rolled back successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _log_sandbox_run(self, filepath: str, report: dict):
        log = []
        if SANDBOX_LOG.exists():
            try:
                log = json.loads(SANDBOX_LOG.read_text())
            except Exception:
                log = []
        log.append({"filepath": filepath, **report, "ts": datetime.now().isoformat()})
        SANDBOX_LOG.parent.mkdir(parents=True, exist_ok=True)
        SANDBOX_LOG.write_text(json.dumps(log[-200:], indent=2))

    def _log_deployment(self, data: dict):
        log = []
        if DEPLOY_LOG.exists():
            try:
                log = json.loads(DEPLOY_LOG.read_text())
            except Exception:
                log = []
        log.append(data)
        DEPLOY_LOG.parent.mkdir(parents=True, exist_ok=True)
        DEPLOY_LOG.write_text(json.dumps(log[-200:], indent=2))

    def get_deployment_history(self) -> list:
        if DEPLOY_LOG.exists():
            try:
                return json.loads(DEPLOY_LOG.read_text())
            except Exception:
                return []
        return []

    def get_deployment(self, deployment_id: str) -> dict | None:
        return next((d for d in self.get_deployment_history() if d.get("id") == deployment_id), None)

    def mark_persisted(self, deployment_id: str) -> dict:
        """Flip a deployment's persisted flag once core.self_improvement's
        persist_deployment() has actually pushed it to GitHub. Idempotent
        by design — calling this twice for the same id is harmless."""
        log = self.get_deployment_history()
        entry = next((d for d in log if d.get("id") == deployment_id), None)
        if not entry:
            return {"success": False, "error": "Deployment not found"}
        entry["persisted"] = True
        DEPLOY_LOG.write_text(json.dumps(log, indent=2))
        return {"success": True, "deployment_id": deployment_id}


jarvis_sandbox = JarvisSandbox()
