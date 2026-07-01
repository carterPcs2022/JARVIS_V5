"""services/vision.py — Vision service (delegates to core/tools/vision.py)."""
from core.tools.vision import analyze

def analyze_image(path: str, prompt: str = "Describe this image.") -> str:
    return analyze(path, prompt)
