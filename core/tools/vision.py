"""core/tools/vision.py — Image analysis."""
import base64
from pathlib import Path

def analyze(path: str, prompt: str = "Describe this image in detail.") -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"[Vision error] File not found: {path}"
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = p.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif",
                "webp": "image/webp"}.get(ext, "image/jpeg")
        # Groq vision via OpenAI-compat
        from config.settings import GROQ_API_KEY, GROQ_BASE_URL
        import httpx
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llava-v1.5-7b-4096-preview",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 512,
        }
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{GROQ_BASE_URL}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Vision error: {e}]"
