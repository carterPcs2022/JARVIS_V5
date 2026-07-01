"""services/backup.py — Memory and config backup."""
import json, shutil, os
from datetime import datetime
from pathlib import Path
from config.settings import BACKUP_DIR, SHORT_TERM_FILE, LONG_TERM_FILE, CONVERSATIONS_FILE

def backup_all() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = []
    for src in [SHORT_TERM_FILE, LONG_TERM_FILE, CONVERSATIONS_FILE]:
        if src.exists():
            dst = BACKUP_DIR / f"{ts}_{src.name}"
            shutil.copy2(src, dst)
            saved.append(str(dst))
    prune()
    return {"backed_up": saved, "ts": ts}

def prune(keep: int = 10):
    if not BACKUP_DIR.exists(): return
    for pattern in ["*short_term*", "*long_term*", "*conversations*"]:
        files = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        for old in files[keep:]:
            old.unlink()

def status() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = list(BACKUP_DIR.glob("*.json"))
    return {"backup_dir": str(BACKUP_DIR), "total_files": len(files),
            "latest": max((f.stat().st_mtime for f in files), default=0)}
