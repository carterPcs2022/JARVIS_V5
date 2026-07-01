"""core/tools/files.py — Safe file operations."""
import os
from pathlib import Path

ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".yaml", ".yml",
                      ".csv", ".log", ".py", ".js", ".html", ".css"}
MAX_READ_BYTES = 50_000


def _safe_path(path: str) -> Path:
    p = Path(path).resolve()
    # Prevent traversal outside home/project
    home = Path.home()
    if not (str(p).startswith(str(home)) or str(p).startswith("/tmp")):
        raise PermissionError(f"Path outside allowed area: {p}")
    return p


def read_file(path: str) -> str:
    try:
        p = _safe_path(path)
        if p.suffix not in ALLOWED_EXTENSIONS:
            return f"[Error] File type {p.suffix} not allowed"
        if not p.exists():
            return f"[Error] File not found: {path}"
        with open(p, "r", errors="replace") as f:
            content = f.read(MAX_READ_BYTES)
        return content + ("\n[...truncated]" if p.stat().st_size > MAX_READ_BYTES else "")
    except Exception as e:
        return f"[Error] {e}"


def write_file(path: str, content: str) -> dict:
    try:
        p = _safe_path(path)
        if p.suffix not in ALLOWED_EXTENSIONS:
            return {"error": f"File type {p.suffix} not allowed"}
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return {"success": True, "path": str(p), "bytes": len(content)}
    except Exception as e:
        return {"error": str(e)}


def list_dir(path: str = ".") -> list[str]:
    try:
        p = _safe_path(path)
        return sorted(str(x.relative_to(p)) for x in p.iterdir())
    except Exception as e:
        return [f"Error: {e}"]
