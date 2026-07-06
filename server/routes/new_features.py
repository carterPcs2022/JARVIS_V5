"""server/routes/new_features.py — the final batch: document upload analysis,
screen monitor, smart home scenes, reading memory, sleep intelligence,
relationship follow-ups, predictive scheduling, and code review/improve."""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["new-features"], dependencies=[Depends(verify_token)])


# ── Document analysis (drag-and-drop) ────────────────────────────────────────

@router.post("/documents/analyze")
async def documents_analyze(file: UploadFile = File(...), question: str = ""):
    from services import documents

    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = documents.ingest(tmp_path)
        if not result.get("ok"):
            return {"error": result.get("error", "Could not analyze document")}

        analysis = result["summary"]
        if question:
            analysis = documents.ask_about(result["id"], question)

        return {"file": file.filename, "analysis": analysis, "word_count": result.get("word_count", 0)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Screen monitor ────────────────────────────────────────────────────────────

@router.post("/screen/analyze")
def screen_analyze(body: dict | None = None):
    from services.screen_monitor import screen_monitor
    return screen_monitor.analyze_screen((body or {}).get("question", ""))
