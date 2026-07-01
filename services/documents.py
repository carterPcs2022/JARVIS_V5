"""services/documents.py — Document intelligence. Drop a file, JARVIS reads it."""
from __future__ import annotations
import json, logging, hashlib
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)
_DOCS_FILE = Path("data/documents.json")


def _load_index() -> list:
    _DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _DOCS_FILE.exists():
        try:
            return json.loads(_DOCS_FILE.read_text())
        except Exception:
            pass
    return []


def _save_index(data: list):
    _DOCS_FILE.write_text(json.dumps(data, indent=2))


def _extract_text(file_path: str) -> str:
    p   = Path(file_path)
    ext = p.suffix.lower()

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(p))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(p))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                return "[PDF extraction unavailable — install pypdf: pip3 install pypdf]"

    if ext in (".docx", ".doc"):
        try:
            from docx import Document
            doc = Document(str(p))
            return "\n".join(para.text for para in doc.paragraphs)
        except ImportError:
            return "[DOCX extraction unavailable — install python-docx: pip3 install python-docx]"

    if ext in (".txt", ".md", ".rst", ".csv", ".json", ".py", ".js", ".ts", ".html"):
        return p.read_text(errors="ignore")

    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        try:
            from services.vision import analyze_image
            result = analyze_image(file_path)
            return result.get("description", "") if isinstance(result, dict) else str(result)
        except Exception as e:
            return f"[Image OCR failed: {e}]"

    return f"[Unsupported file type: {ext}]"


def _doc_id(file_path: str) -> str:
    return hashlib.sha256(str(Path(file_path).resolve()).encode()).hexdigest()[:12]


def ingest(file_path: str) -> dict:
    """Process a document and store its summary in memory."""
    p = Path(file_path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {file_path}"}

    text = _extract_text(file_path)
    if not text.strip():
        return {"ok": False, "error": "Could not extract text from file"}

    # Summarize with LLM
    summary = summarize(file_path, text_override=text[:8000])

    doc = {
        "id":          _doc_id(file_path),
        "path":        str(p.resolve()),
        "name":        p.name,
        "ext":         p.suffix.lower(),
        "size_bytes":  p.stat().st_size,
        "ingested_at": datetime.now().isoformat(),
        "text":        text[:20000],
        "summary":     summary,
        "word_count":  len(text.split()),
    }

    index = _load_index()
    index = [d for d in index if d["id"] != doc["id"]]  # replace if re-ingesting
    index.append(doc)
    _save_index(index)

    try:
        from core.memory import store_long_term
        store_long_term(f"Document ingested: {p.name}", summary, tags=["document", p.suffix])
    except Exception:
        pass

    log.info("Ingested %s (%d words)", p.name, doc["word_count"])
    return {"ok": True, "id": doc["id"], "name": p.name, "summary": summary, "word_count": doc["word_count"]}


def summarize(file_path: str, length: str = "brief", text_override: str | None = None) -> str:
    text = text_override or _extract_text(file_path)
    if not text.strip():
        return "Could not extract text from document."

    style = {
        "brief":    "2-3 sentences maximum",
        "detailed": "comprehensive summary with key points",
        "bullets":  "bullet points covering all main topics",
    }.get(length, "brief summary")

    prompt = f"Summarize this document in {style}:\n\n{text[:6000]}"
    try:
        from core.llm.router import think
        return think(prompt, max_tokens=512)
    except Exception as e:
        return f"[Summary unavailable: {e}]"


def ask_about(document_id: str, question: str) -> str:
    index = _load_index()
    doc   = next((d for d in index if d["id"] == document_id), None)
    if not doc:
        return f"Document {document_id} not found. Ingest it first."

    prompt = f"Based on this document, answer the question.\n\nDocument ({doc['name']}):\n{doc['text'][:6000]}\n\nQuestion: {question}"
    try:
        from core.llm.router import think
        return think(prompt, max_tokens=512)
    except Exception as e:
        return f"[Q&A unavailable: {e}]"


def find_in_documents(query: str) -> list[dict]:
    index = _load_index()
    q_low = query.lower()
    results = []
    for doc in index:
        text = (doc.get("text", "") + " " + doc.get("summary", "")).lower()
        if q_low in text:
            results.append({
                "id":      doc["id"],
                "name":    doc["name"],
                "path":    doc["path"],
                "summary": doc["summary"][:200],
                "match":   True,
            })
    return results


def list_documents() -> list[dict]:
    return [{"id": d["id"], "name": d["name"], "summary": d["summary"][:150],
             "ingested_at": d["ingested_at"]} for d in _load_index()]
