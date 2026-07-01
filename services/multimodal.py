"""
services/multimodal.py — MultimodalInput: screen capture, clipboard, file uploads, webcam.
"""
import os
import re
import threading
import time
from pathlib import Path

try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import cv2
except ImportError:
    cv2 = None

from core.event_bus import bus


class MultimodalInput:

    # ------------------------------------------------------------------ #
    # Screen                                                               #
    # ------------------------------------------------------------------ #

    def capture_screen(self):
        """Capture the primary monitor and save to /tmp/jarvis_screen.png."""
        if mss is None:
            return {"error": "mss not installed", "install": "pip install mss"}

        try:
            out_path = "/tmp/jarvis_screen.png"
            with mss.mss() as sct:
                monitor = sct.monitors[1]          # primary monitor
                screenshot = sct.grab(monitor)
                mss.tools.to_png(screenshot.rgb, screenshot.size, output=out_path)
            return out_path
        except Exception as e:
            return {"error": str(e)}

    def analyze_screen_content(self) -> str:
        """Capture the screen and return vision analysis."""
        from core.tools.vision import analyze

        result = self.capture_screen()
        if isinstance(result, dict):
            return f"Screen capture failed: {result.get('error', 'unknown error')}"

        try:
            analysis = analyze(result)
            return analysis
        except Exception as e:
            return f"Vision analysis failed: {e}"

    # ------------------------------------------------------------------ #
    # Clipboard                                                            #
    # ------------------------------------------------------------------ #

    def get_clipboard(self) -> str:
        """Return clipboard text, or an informative string if unavailable."""
        if pyperclip is None:
            return "pyperclip not installed — run: pip install pyperclip"

        try:
            content = pyperclip.paste()
            if not content or not content.strip():
                return "Clipboard is empty."
            return content
        except Exception as e:
            return f"Clipboard unavailable: {e}"

    def _classify_clipboard(self, text: str) -> str:
        """Classify clipboard content type."""
        stripped = text.strip()
        if stripped.startswith("http://") or stripped.startswith("https://"):
            return "url"
        if any(kw in stripped for kw in ("def ", "function ", "import ", "var ", "const ", "class ")):
            return "code"
        addr_pattern = re.compile(
            r"\b\d+\b.{1,40}(street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln)\b",
            re.IGNORECASE,
        )
        if addr_pattern.search(stripped):
            return "address"
        return "text"

    def watch_clipboard(self):
        """Start a daemon thread that polls clipboard every 2s and publishes changes."""
        _previous: list = [None]

        def _poll():
            while True:
                try:
                    if pyperclip is not None:
                        content = pyperclip.paste()
                        if content and content != _previous[0]:
                            _previous[0] = content
                            content_type = self._classify_clipboard(content)
                            bus.publish(
                                "clipboard_change",
                                {
                                    "content": content,
                                    "type": content_type,
                                    "preview": content[:100],
                                },
                                severity="info",
                            )
                except Exception:
                    pass
                time.sleep(2)

        t = threading.Thread(target=_poll, daemon=True, name="clipboard-watcher")
        t.start()

    # ------------------------------------------------------------------ #
    # File upload dispatcher                                               #
    # ------------------------------------------------------------------ #

    def handle_upload(self, file_path: str, original_name: str):
        """Dispatch uploaded file to the appropriate handler based on extension."""
        ext = Path(original_name).suffix.lower()

        doc_exts   = {".pdf", ".docx"}
        code_exts  = {".py", ".js", ".ts", ".txt", ".md"}
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        audio_exts = {".mp3", ".wav", ".m4a"}

        try:
            if ext in doc_exts:
                from services.documents import ingest
                return ingest(file_path)

            elif ext in code_exts:
                try:
                    from services.dev_intel import explain_file
                    return explain_file(file_path)
                except ImportError:
                    from core.llm.router import think
                    content = Path(file_path).read_text(errors="replace")[:4000]
                    return think(f"Explain this file:\n\n{content}")

            elif ext in image_exts:
                from core.tools.vision import analyze
                return analyze(file_path)

            elif ext in audio_exts:
                from services.voice import transcribe
                return transcribe(file_path)

            else:
                return {"status": "unknown_type", "file": original_name}

        except Exception as e:
            return {"status": "error", "file": original_name, "error": str(e)}

    # ------------------------------------------------------------------ #
    # Webcam                                                               #
    # ------------------------------------------------------------------ #

    def webcam_snapshot(self):
        """Capture a single frame from the default webcam."""
        if cv2 is None:
            return {"error": "cv2 not installed", "install": "pip install opencv-python"}

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"error": "Camera not available or already in use"}

        try:
            ret, frame = cap.read()
            if not ret:
                return {"error": "Failed to capture frame from camera"}

            out_path = "/tmp/jarvis_webcam.jpg"
            cv2.imwrite(out_path, frame)
            return out_path
        except Exception as e:
            return {"error": str(e)}
        finally:
            cap.release()


# Module-level singleton
multimodal = MultimodalInput()
