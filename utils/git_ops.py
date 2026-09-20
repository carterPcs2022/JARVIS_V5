"""utils/git_ops.py — shared git commit+push helper for autonomous file
changes that need to survive a Render redeploy (the filesystem there is
ephemeral, and nothing else in this app pushes to git).

Authenticates the push with GITHUB_TOKEN when set, building a one-off
token-embedded URL passed explicitly to `git push` rather than `git remote
set-url` — the token is never written to .git/config, so it can't leak via
anything that later reads or logs that file. It's still visible briefly in
this process's argv (e.g. `ps aux` on the same container) for the duration
of the push — an accepted tradeoff on a single-tenant Render container,
where the token is already sitting in plaintext in the process's own
environment either way.

Previously did a bare `git push` with no credential of any kind, working
only by accident if the deploy environment happened to already have
write-capable git credentials configured some other way (it never did on
Render) — commit_and_push() fails closed either way: the commit lands
locally (still lost on next redeploy) and the failure is logged, never
raised.
"""
from __future__ import annotations
import os
import re
import subprocess
from config.settings import BASE_DIR

# Passed as -c flags (this invocation only) rather than `git config
# --global` — never mutates the repo's or environment's persistent git
# config, just satisfies "who authored this commit" for this one command.
_GIT_AUTHOR = ["-c", "user.name=JARVIS", "-c", "user.email=jarvis@localhost"]


def _authenticated_push_target() -> tuple[str, str] | None:
    """(url, branch) for an explicit `git push <url> HEAD:<branch>`, with
    GITHUB_TOKEN embedded in the URL — or None if there's no token or the
    remote isn't a plain https://github.com/... URL (e.g. SSH, which
    already carries its own auth and shouldn't be touched)."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return None

    remote = subprocess.run(
        ["git", "-C", str(BASE_DIR), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    remote_url = remote.stdout.strip() if remote.returncode == 0 else ""
    if not remote_url.startswith("https://github.com/"):
        repository = os.getenv("GITHUB_REPOSITORY", "carterPcs2022/JARVIS_V5").strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            return None
        remote_url = f"https://github.com/{repository}.git"

    branch = subprocess.run(
        ["git", "-C", str(BASE_DIR), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    if branch.returncode != 0:
        return None

    url = remote_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/", 1)
    return url, branch.stdout.strip()


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

        target = _authenticated_push_target()
        if target:
            push_cmd = ["git", "-C", str(BASE_DIR), "push", target[0], f"HEAD:{target[1]}"]
        else:
            branch = subprocess.run(
                ["git", "-C", str(BASE_DIR), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            if branch.returncode != 0 or not branch.stdout.strip():
                return {"committed": True, "pushed": False, "error": "could not determine current git branch"}
            push_cmd = ["git", "-C", str(BASE_DIR), "push", "origin", f"HEAD:{branch.stdout.strip()}"]
        push = subprocess.run(push_cmd, capture_output=True, text=True, timeout=30)
        if push.returncode != 0:
            # git's own error text sometimes echoes the remote URL verbatim
            # (e.g. "unable to access 'https://x-access-token:<token>@...'")
            # — redact before this reaches a log or an API response.
            token = os.getenv("GITHUB_TOKEN", "")
            stderr = push.stderr.strip().replace(token, "***") if token else push.stderr.strip()
            print(f"{log_prefix} git push failed (commit made locally, not pushed): {stderr}")
            return {"committed": True, "pushed": False, "error": stderr}

        print(f"{log_prefix} Committed and pushed: {message}")
        return {"committed": True, "pushed": True, "message": message}

    except Exception as e:
        print(f"{log_prefix} git operation failed: {e}")
        return {"committed": False, "pushed": False, "error": str(e)}
