"""services/dev_intel.py — JARVIS's awareness of your codebases."""
import ast
import json
import re
from pathlib import Path
from typing import Optional

from config.settings import BASE_DIR

INDEX_FILE = BASE_DIR / "memory" / "project_index.json"
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
_CODE_EXT  = {".py", ".js", ".ts", ".tsx", ".jsx"}


def _safe_path(path: str) -> Path | None:
    """Restricts explain_file()/review_file() to files inside this project
    (BASE_DIR) — both are reachable via POST /stark/code/{review,explain}
    with a raw, caller-supplied path and no other restriction, so an
    unrestricted Path(path).read_text() would let any authenticated caller
    read anything on the server (e.g. .env, config/settings.py). Returns
    None on any attempt to escape BASE_DIR, same convention as
    core/tools/files.py's _safe_path()."""
    try:
        p = Path(path).resolve()
        p.relative_to(BASE_DIR.resolve())
        return p
    except (ValueError, OSError):
        return None


def _load_json(path: Path, default):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class DeveloperIntelligence:

    def _walk_files(self, path: str):
        # index_project() is reachable via GET /stark/code/index?path=... —
        # token-gated, but the token gates the whole API, not filesystem
        # access outside this project specifically; restrict for the same
        # reason as _safe_path() above.
        root = _safe_path(path)
        if root is None:
            return
        for p in root.rglob("*"):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.suffix in _CODE_EXT:
                yield p

    def _extract_python(self, path: Path) -> dict:
        try:
            source = path.read_text(errors="ignore")
            tree   = ast.parse(source)
        except Exception:
            return {"functions": [], "classes": [], "imports": []}

        functions, classes, imports = [], [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name, "line": node.lineno,
                    "docstring": ast.get_docstring(node) or "",
                })
            elif isinstance(node, ast.ClassDef):
                classes.append({"name": node.name, "line": node.lineno})
            elif isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        return {"functions": functions, "classes": classes, "imports": imports}

    def index_project(self, path: str = ".") -> dict:
        index = {}
        for f in self._walk_files(path):
            rel = str(f)
            if f.suffix == ".py":
                index[rel] = self._extract_python(f)
            else:
                index[rel] = {"functions": [], "classes": [], "imports": []}

        _save_json(INDEX_FILE, index)
        return {
            "files_indexed": len(index),
            "total_functions": sum(len(v["functions"]) for v in index.values()),
            "total_classes":   sum(len(v["classes"])   for v in index.values()),
        }

    def find_function(self, name: str) -> list[dict]:
        index = _load_json(INDEX_FILE, {})
        hits = []
        for file, data in index.items():
            for fn in data.get("functions", []):
                if name.lower() in fn["name"].lower():
                    hits.append({"file": file, "line": fn["line"],
                                 "signature": fn["name"], "docstring": fn["docstring"]})
        return hits

    def explain_file(self, path: str) -> str:
        p = _safe_path(path)
        if p is None:
            return f"Path outside allowed area: {path}"
        if not p.exists():
            return f"File not found: {path}"
        try:
            content = p.read_text(errors="ignore")[:4000]
        except Exception as e:
            return f"Could not read file: {e}"
        try:
            from core.llm.router import think
            prompt = f"Briefly explain what this file does (2-3 sentences):\n\n{content}"
            return think(prompt, max_tokens=200)
        except Exception:
            return f"{path}: {len(content)} chars, unable to summarize (LLM unavailable)."

    def review_file(self, file_path: str) -> dict:
        """Deep code review — bugs, security issues, performance, missing
        error handling. Uses fable (deepest scrutiny tier) since a review
        is exactly the kind of task that benefits from it."""
        p = _safe_path(file_path)
        if p is None:
            return {"error": f"Path outside allowed area: {file_path}"}
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        try:
            code = p.read_text(errors="ignore")[:4000]
        except Exception as e:
            return {"error": str(e)}

        from core.llm.router import think
        review = think(
            f"Code review for {file_path}:\n\n{code}\n\n"
            f"Check for:\n"
            f"1. Bugs or logic errors\n"
            f"2. Security issues\n"
            f"3. Performance improvements\n"
            f"4. Code quality\n"
            f"5. Missing error handling\n"
            f"Be specific with line references.",
            force_model="fable",
        )
        return {"file": file_path, "review": review}

    def suggest_improvements(self, code: str) -> str:
        """Suggest the most impactful improvements for a code snippet."""
        from core.llm.router import think
        return think(
            f"Suggest specific improvements for this code:\n\n{code[:2000]}\n\n"
            f"Focus on the most impactful changes.",
            force_model="opus",
        )

    def find_todos(self, path: str = ".") -> list[dict]:
        pattern = re.compile(r"(TODO|FIXME|HACK)[:\s]+(.*)", re.I)
        todos = []
        for f in self._walk_files(path):
            try:
                for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                    m = pattern.search(line)
                    if m:
                        todos.append({"file": str(f), "line": i,
                                      "tag": m.group(1).upper(), "text": m.group(2).strip()})
            except Exception:
                continue
        return todos

    def git_summary(self, repo_path: str = ".") -> dict:
        try:
            import git
            repo = git.Repo(repo_path)
        except Exception as e:
            return {"error": f"Not a git repo or gitpython unavailable: {e}"}

        try:
            branch = repo.active_branch.name
        except Exception:
            branch = "detached"

        recent_commits = [
            {"sha": c.hexsha[:7], "message": c.message.strip(), "author": str(c.author),
             "date": c.committed_datetime.isoformat()}
            for c in list(repo.iter_commits(max_count=10))
        ]
        dirty = repo.is_dirty(untracked_files=True)
        uncommitted = [item.a_path for item in repo.index.diff(None)] + repo.untracked_files

        return {
            "branch": branch,
            "dirty": dirty,
            "uncommitted_files": uncommitted,
            "recent_commits": recent_commits,
        }

    def git_commit(self, repo_path: str, message: str) -> dict:
        try:
            import git
            repo = git.Repo(repo_path)
            repo.git.add(A=True)
            repo.index.commit(message)
            return {"ok": True, "message": message}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def error_log_analysis(self, log_path: str) -> dict:
        p = _safe_path(log_path)
        if p is None:
            return {"error": f"Path outside allowed area: {log_path}"}
        if not p.exists():
            return {"error": "log file not found"}
        lines = p.read_text(errors="ignore").splitlines()
        error_lines = [l for l in lines if re.search(r"error|exception|traceback", l, re.I)]
        counts: dict[str, int] = {}
        for l in error_lines:
            key = l.strip()[:80]
            counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"total_errors": len(error_lines), "top_patterns": top}

    def dependency_audit(self, requirements_path: str = "requirements.txt") -> dict:
        p = _safe_path(requirements_path)
        if p is None:
            return {"error": f"Path outside allowed area: {requirements_path}"}
        if not p.exists():
            return {"error": "requirements.txt not found"}
        deps = [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]
        return {"total_dependencies": len(deps), "dependencies": deps}


dev_intel = DeveloperIntelligence()
