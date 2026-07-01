"""core/tools/browser.py — Web page fetch and text extraction."""
import httpx, re

TIMEOUT = 15

def fetch(url: str, max_chars: int = 4000) -> str:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": "JARVIS/5.0"})
            text = r.text
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception as e:
        return f"[Browser error: {e}]"

def screenshot_url(url: str) -> str:
    """Placeholder — wire to playwright/selenium if needed."""
    return f"[Screenshot not yet implemented for {url}]"
