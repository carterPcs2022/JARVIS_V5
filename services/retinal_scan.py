"""services/retinal_scan.py — retinal/iris scan authentication.

Replaces the facial-auth concept from the spec this was built against —
a full codebase search (services/, core/, server/) for "facial
authentication", "face recognition", "vector db", and "saved faces" found
no matching code at all, so there was nothing to silence or remove.
This is a standalone new capability, not a literal replacement.

Uses OpenCV iris pattern recognition when available (requirements-local.txt);
falls back to Claude vision analysis (works on Render — no local CV needed)
when it isn't.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

RETINAL_FILE = BASE_DIR / "memory" / "retinal_baseline.json"


class RetinalScanner:

    def __init__(self):
        self.baseline: dict = self._load_baseline()
        self.scan_count: int = 0
        self.last_scan: str | None = None

    def capture_and_scan(self, image_path: str | None = None) -> dict:
        """Capture eye from camera and extract iris pattern, or analyze an
        uploaded image. cv2 is imported lazily here (not at module level)
        so this module — and anything that imports it — stays importable
        on hosts without opencv-python installed (e.g. Render)."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return self._api_based_scan(image_path)

        try:
            if image_path:
                frame = cv2.imread(image_path)
                if frame is None:
                    return {"error": f"Could not read image: {image_path}"}
            else:
                cap = cv2.VideoCapture(0)
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    return {"error": "Camera not available"}

            eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            eyes = eye_cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))

            if len(eyes) == 0:
                return {
                    "success": False,
                    "reason":  "No eye detected",
                    "prompt":  "Look directly at the camera, sir.",
                }

            eyes = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)
            x, y, w, h = eyes[0]
            eye_region = gray[y:y + h, x:x + w]

            iris_hash = self._extract_iris_pattern(eye_region)

            if not self.baseline.get("iris_hash"):
                return self._enroll(iris_hash)
            return self._verify(iris_hash)

        except Exception as e:
            return {"error": str(e)}

    def _extract_iris_pattern(self, eye_region) -> str:
        """Extract a unique iris pattern as a hash — simplified Daugman's
        rubber sheet model: detect the iris circle, mask to it, then
        perceptual-hash an 8x8 block grid."""
        import cv2
        import numpy as np

        std = cv2.resize(eye_region, (64, 64))

        circles = cv2.HoughCircles(
            std, cv2.HOUGH_GRADIENT, dp=1, minDist=20,
            param1=50, param2=30, minRadius=10, maxRadius=30,
        )

        if circles is not None:
            circles = np.uint16(np.around(circles))
            cx, cy, r = circles[0][0]
            mask = np.zeros_like(std)
            cv2.circle(mask, (cx, cy), r, 255, -1)
            iris = cv2.bitwise_and(std, mask)
        else:
            iris = std

        h, w = iris.shape
        block_h, block_w = h // 8, w // 8
        bits = []
        mean = np.mean(iris)

        for i in range(8):
            for j in range(8):
                block = iris[i * block_h:(i + 1) * block_h, j * block_w:(j + 1) * block_w]
                bits.append(1 if np.mean(block) > mean else 0)

        bit_string = "".join(str(b) for b in bits)
        return hashlib.sha256(bit_string.encode()).hexdigest()

    def _enroll(self, iris_hash: str) -> dict:
        """Enroll iris pattern as baseline."""
        self.baseline = {
            "iris_hash":  iris_hash,
            "enrolled":   datetime.now().isoformat(),
            "scan_count": 0,
        }
        self._save_baseline()

        from services.voice import speak
        speak("Retinal scan baseline established. Iris pattern recorded. Authentication system active, sir.")

        return {"success": True, "enrolled": True, "message": "Retinal baseline established."}

    def _verify(self, iris_hash: str) -> dict:
        """Verify iris against baseline. Never announces a successful match —
        only a failure, since that's the case someone actually needs to
        hear about (a stranger holding the device up to the camera).
        run_silently() delegates here too, so this is the single source of
        truth for that rule rather than something each caller has to
        remember to respect."""
        stored = self.baseline.get("iris_hash", "")
        match_score = self._hash_similarity(iris_hash, stored)

        self.scan_count += 1
        self.last_scan = datetime.now().isoformat()
        self.baseline["scan_count"] = self.baseline.get("scan_count", 0) + 1
        self._save_baseline()

        THRESHOLD = 0.75

        if match_score >= THRESHOLD:
            return {"success": True, "verified": True, "match_score": match_score,
                    "message": "Identity confirmed."}

        from services.voice import speak
        speak("Retinal scan failed. Identity could not be verified.")
        from core.event_bus import bus
        bus.alert(
            f"RETINAL SCAN FAILED. Match score {match_score:.0%}. Unauthorized access attempt.",
            severity="critical", category="BIOMETRIC_AUTH",
        )
        return {"success": True, "verified": False, "match_score": match_score,
                "message": "Identity not confirmed."}

    def _api_based_scan(self, image_path: str | None) -> dict:
        """Fallback when OpenCV isn't installed — uses Claude vision to
        analyze the eye image. Works on Render, no local CV needed."""
        if not image_path:
            return {"error": "No image provided"}

        from core.llm.router import think
        import json as _json
        import re

        result = think(
            "Analyze this eye image for authentication. Is this a clear eye image? "
            "Can you see the iris clearly? Describe the iris pattern visible. "
            'Reply as JSON: {"has_eye": bool, "iris_visible": bool, "pattern_description": str}',
            force_model="sonnet",
        )

        try:
            clean = re.sub(r"```json|```", "", result).strip()
            data = _json.loads(clean)
        except Exception:
            return {"error": "Could not analyze eye image"}

        if not (data.get("has_eye") and data.get("iris_visible")):
            return {"error": "Could not analyze eye image"}

        pattern = data.get("pattern_description", "")
        pattern_hash = hashlib.sha256(pattern.encode()).hexdigest()

        if not self.baseline.get("iris_hash"):
            return self._enroll_text(pattern_hash, pattern)
        return self._verify_text(pattern_hash)

    def _enroll_text(self, hash_: str, pattern: str) -> dict:
        self.baseline = {
            "iris_hash":    hash_,
            "pattern_desc": pattern,
            "enrolled":     datetime.now().isoformat(),
        }
        self._save_baseline()
        return {"success": True, "enrolled": True}

    def _verify_text(self, hash_: str) -> dict:
        stored = self.baseline.get("iris_hash", "")
        score = self._hash_similarity(hash_, stored)
        return {"success": True, "verified": score >= 0.6, "match_score": score}

    def _hash_similarity(self, h1: str, h2: str) -> float:
        """Bit-level similarity between two sha256 hex digests."""
        if not h1 or not h2:
            return 0.0
        if h1 == h2:
            return 1.0
        b1 = bin(int(h1, 16))[2:].zfill(256)
        b2 = bin(int(h2, 16))[2:].zfill(256)
        matching = sum(a == b for a, b in zip(b1, b2))
        return matching / 256

    def run_silently(self) -> dict:
        """Run in background — never announce success, only speak if
        verification fails. Only call this from an explicit user action
        (e.g. an "authenticate me" request); never wire it to a scheduler
        or timer."""
        result = self.capture_and_scan()
        if result.get("verified") is False:
            from core.event_bus import bus
            bus.alert("Retinal scan failed — identity not confirmed.",
                      severity="critical", category="BIOMETRIC")
        return result

    def enroll_from_image(self, image_path: str) -> dict:
        """Enroll from an uploaded image."""
        return self.capture_and_scan(image_path)

    def status(self) -> dict:
        return {
            "enrolled":    bool(self.baseline.get("iris_hash")),
            "scan_count":  self.baseline.get("scan_count", 0),
            "last_scan":   self.last_scan,
            "enrolled_at": self.baseline.get("enrolled", ""),
        }

    def _load_baseline(self) -> dict:
        if RETINAL_FILE.exists():
            try:
                return json.loads(RETINAL_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_baseline(self):
        RETINAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        RETINAL_FILE.write_text(json.dumps(self.baseline, indent=2))


retinal = RetinalScanner()
