"""core/tools/vision.py — Image analysis."""
import base64
import re
from pathlib import Path

# llava-v1.5-7b-4096-preview was decommissioned by Groq. qwen/qwen3.6-27b is
# the only vision-capable model in Groq's live catalog as of 2026-07-18
# (verified against console.groq.com/docs/vision and a real API call before
# wiring it in here) — it's also already used as this project's Groq
# reasoning-tier model. Like that tier, it emits inline <think>...</think>
# chain-of-thought before the real answer, in the same "content" field
# (unlike Cerebras's gpt-oss-120b, which uses a separate "reasoning" field).
# Stripping it isn't cosmetic: services/glasses_cv.py's threat_scan() does a
# raw `"THREAT" in result.upper()` substring check on this return value, and
# the model's own reasoning prose routinely contains the word "threat" while
# discussing the task ("scan for threats...") even when the real verdict is
# CLEAR — verified this exact false-positive shape with a real test image.
# Left unstripped, that reads as a real threat detection and fires
# core/event_bus.py's severity="critical" alert (voice + Telegram + an
# actual phone call) for nothing.
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _strip_think_tags(text: str) -> str:
    cleaned = re.sub(_THINK_RE, "", text).strip()
    return cleaned or text  # fall back to the original if stripping left nothing


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
            "model": "qwen/qwen3.6-27b",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            # 512 was tuned for the old model. This one's internal reasoning
            # alone can run well past that before ever reaching an answer —
            # verified an open-ended "describe what you see" prompt still
            # hadn't finished at 1500 tokens against a trivial test image;
            # structured short-answer prompts (e.g. threat_scan's CLEAR/
            # CAUTION/THREAT) finish comfortably under 300. 2048 covers the
            # structured prompts with real margin; the open-ended analyze()
            # prompt can still occasionally run long — if that happens in
            # practice, tightening that prompt to ask for a fixed short
            # format (like threat_scan already does) would help more than a
            # larger token budget would.
            "max_tokens": 2048,
        }
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{GROQ_BASE_URL}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _strip_think_tags(content)
    except Exception as e:
        return f"[Vision error: {e}]"
