"""core/attachments.py — Fold an uploaded image or file into a real chat turn.

Every interactive surface (HUD web chat, Discord, Telegram) that lets a user
attach something routes through compose_turn_with_attachment() so all three
get the same behavior from one place, rather than each reimplementing its
own "what do I do with this file" logic.

Images route through the brain's existing vision pipeline instead of a new
one: Reasoner already classifies "photo"/"image"/"picture" text as a vision
action, and Executor._vision() regex-extracts a filesystem path out of the
raw text and calls core.tools.vision.analyze(path, question) — so embedding
the saved temp path in a bracketed note the reasoner recognizes reuses that
pipeline as-is, including the user's own question as the vision prompt
(richer than a fixed "describe this image" prompt) and its usual save_turn/
memory persistence via Executor.

Everything else (PDF, DOCX, TXT, ...) has no equivalent pipeline hook, so
it's pre-summarized via services.documents.ingest() and folded in as plain
context text — the same bracketed-note pattern already used elsewhere in
the pipeline (e.g. the repeated-question note in core/brain_v2.py, or the
stress-level note in server/routes/glasses.py) to give the LLM extra
context without it reading as a technical system message.
"""
from pathlib import Path

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def compose_turn_with_attachment(message: str, file_path: str, filename: str) -> str:
    """Returns the text to hand to brain.process_dict() for an uploaded
    image or file — the user's message plus a bracketed note pointing at
    (images) or summarizing (everything else) the attachment. If the user
    didn't type anything, a reasonable default question is used instead."""
    message = (message or "").strip()
    ext = Path(filename).suffix.lower()

    if ext in _IMAGE_EXTS:
        # "image" must appear as its own whitespace-delimited token — Reasoner
        # classifies the vision action via `toks & self._VISION_KW` on a
        # plain `.split()` (see core/brain_v2.py), so "image:" glued to the
        # path would silently fail to match and fall through to plain chat.
        note = f"[Attached image at path: {file_path}]"
        default_ask = "What do you see in this image?"
    else:
        from services.documents import ingest
        result = ingest(file_path)
        if result.get("ok"):
            note = f'[Attached file "{filename}": {result["summary"]}]'
        else:
            note = f'[Attached file "{filename}" could not be read: {result.get("error", "unknown error")}]'
        default_ask = f'What can you tell me about "{filename}"?'

    return f"{message}\n\n{note}" if message else f"{default_ask}\n\n{note}"
