"""services/github_intel.py — JARVIS watches your GitHub: reviews PRs,
summarizes repos, tracks commit activity for the morning brief."""
import base64
import os
from datetime import datetime, timedelta

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_USER = os.getenv("GITHUB_USERNAME", "carterPcs2022")


class GitHubIntelligence:

    def __init__(self):
        self.headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        self.base = "https://api.github.com"

    def get_repos(self) -> list[dict]:
        try:
            r = httpx.get(f"{self.base}/user/repos", headers=self.headers, timeout=10)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def get_recent_commits(self, repo: str, days: int = 7) -> list[dict]:
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            r = httpx.get(
                f"{self.base}/repos/{GITHUB_USER}/{repo}/commits",
                params={"since": since}, headers=self.headers, timeout=10,
            )
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def review_pr(self, repo: str, pr_number: int) -> dict:
        """JARVIS reviews a pull request: bugs, security, missing tests, style."""
        from core.llm.router import think

        try:
            r = httpx.get(
                f"{self.base}/repos/{GITHUB_USER}/{repo}/pulls/{pr_number}",
                headers={**self.headers, "Accept": "application/vnd.github.v3.diff"}, timeout=10,
            )
            diff = r.text[:3000] if r.status_code == 200 else ""
        except Exception:
            diff = ""

        if not diff:
            return {"pr": pr_number, "repo": repo, "review": "Could not fetch PR diff — check GITHUB_TOKEN and PR number."}

        review = think(
            f"Review this code change for repository '{repo}':\n\n{diff}\n\n"
            f"Check for:\n1. Logic errors or bugs\n2. Security vulnerabilities\n"
            f"3. Performance issues\n4. Missing error handling\n5. Code quality and style\n"
            f"6. What this change actually does\n\n"
            f"Be specific. Reference line numbers when possible.",
            force_model="coder",
        )
        return {"pr": pr_number, "repo": repo, "review": review}

    def watch_repos(self, repos: list[str]) -> dict:
        changes = {}
        for repo in repos:
            commits = self.get_recent_commits(repo, days=1)
            if commits:
                changes[repo] = {
                    "new_commits": len(commits),
                    "latest": commits[0].get("commit", {}).get("message", ""),
                }
        return changes

    def code_summary(self, repo: str) -> str:
        from core.llm.router import think

        readme = ""
        try:
            r = httpx.get(f"{self.base}/repos/{GITHUB_USER}/{repo}/readme", headers=self.headers, timeout=10)
            if r.status_code == 200:
                content = r.json().get("content", "")
                readme = base64.b64decode(content).decode(errors="replace")[:2000]
        except Exception:
            pass

        return think(
            f"Explain what this GitHub repository is and does:\n"
            f"Repo: {repo}\nREADME: {readme[:1000]}\n\n"
            f"Explain in 3 sentences as if briefing someone who needs to work on it.",
            force_model="standard",
        )

    def daily_dev_brief(self) -> str:
        from core.llm.router import think

        repos = self.get_repos()
        activity = []
        for repo in repos[:5]:
            name = repo.get("name", "")
            commits = self.get_recent_commits(name, days=1)
            if commits:
                msg = commits[0].get("commit", {}).get("message", "")[:60]
                activity.append(f"{name}: {len(commits)} commit(s) — {msg}")

        if not activity:
            return "No repository activity in the last 24 hours."

        return think(
            f"Summarize this GitHub activity briefly:\n" + "\n".join(activity) +
            "\nBe concise. JARVIS-style delivery.",
            force_model="instant",
        )


github = GitHubIntelligence()
