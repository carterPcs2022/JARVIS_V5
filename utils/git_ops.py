"""utils/git_ops.py — shared git commit+push helper for autonomous file
changes that need to survive a Render redeploy (the filesystem there is
ephemeral, and nothing else in this app pushes to git).

Requires the deploy environment to already have write-capable git
credentials configured (an HTTPS remote with an embedded token, or an SSH
deploy key) — this module can't provision that itself. Without it,
commit_and_push() fails closed: the commit lands locally (still lost on
next redeploy) and the failure is logged, never raised.
"""
from __future__ import annotations
import subprocess
from config.settings import BASE_DIR

# Passed as -c flags (this invocation only) rather than `git config
# --global` — never mutates the repo's or environment's persistent git
# config, just satisfies "who authored this commit" for this one command.
_GIT_AUTHOR = ["-c", "user.name=JARVIS", "-c", "user.email=jarvis@localhost"]


def commit_and_push(paths: list[str], message: str, log_prefix: str = "[GitOps]") -> dict:
    """Stage exactly `paths` — never `git add .` or `-A`, so any unrelated
    local changes in the working tree are left untouched — then commit and
    push. Every failure mode (nothing to commit, no credentials, network,
    a gitignored path) is expected to happen sometimes and is returned/
    logged rather than silently swallowed."""
    try:
        add = subprocess.run(
            ["git", "-C", str(BASE_DIR), "add", "--", *paths],
            capture_output=True, text=True, timeout=10,
        )
        if add.returncode != 0:
            print(f"{log_prefix} git add failed: {add.stderr.strip()}")
            return {"committed": False, "pushed": False, "error": add.stderr.strip()}

        commit = subprocess.run(
            ["git", "-C", str(BASE_DIR), *_GIT_AUTHOR, "commit", "-m", message],
            capture_output=True, text=True, timeout=10,
        )
        if commit.returncode != 0:
            combined = (commit.stdout + commit.stderr).lower()
            if "nothing to commit" in combined:
                return {"committed": False, "pushed": False, "reason": "nothing to commit"}
            print(f"{log_prefix} git commit failed: {commit.stderr.strip()}")
            return {"committed": False, "pushed": False, "error": commit.stderr.strip()}

        push = subprocess.run(
            ["git", "-C", str(BASE_DIR), "push"],
            capture_output=True, text=True, timeout=30,
        )
        if push.returncode != 0:
            print(f"{log_prefix} git push failed (commit made locally, not pushed): {push.stderr.strip()}")
            return {"committed": True, "pushed": False, "error": push.stderr.strip()}

        print(f"{log_prefix} Committed and pushed: {message}")
        return {"committed": True, "pushed": True, "message": message}

    except Exception as e:
        print(f"{log_prefix} git operation failed: {e}")
        return {"committed": False, "pushed": False, "error": str(e)}
