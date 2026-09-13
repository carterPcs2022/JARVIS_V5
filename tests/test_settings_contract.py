"""Regression test for the settings contract.

A previous security refactor removed configuration symbols that dozens of
modules still imported, causing the Render service to die during startup.
This test catches that class of regression before deployment.
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "config" / "settings.py"


def _defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def test_all_settings_imports_exist():
    settings_tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    defined = _defined_names(settings_tree)
    missing: list[str] = []

    for path in ROOT.rglob("*.py"):
        if path == SETTINGS or any(part in {".git", ".venv", "venv"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "config.settings":
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in defined:
                    missing.append(f"{path.relative_to(ROOT)}: {alias.name}")

    assert not missing, "Missing config.settings symbols:\n" + "\n".join(sorted(set(missing)))
