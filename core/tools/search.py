"""
core/tools/search.py — Free search cascade.
Priority: Serper → Tavily → SerpApi → DuckDuckGo (always works, no key)
"""
from __future__ import annotations
import os, json, logging, urllib.request, urllib.parse, re, html
from typing import List

log = logging.getLogger(__name__)
_TIMEOUT = 10


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Serper (Google results, 2500 free, serper.dev) ────────────────────────────

def _serper(query: str, endpoint: str = "/search") -> List[dict]:
    key = os.getenv("SERPER_API_KEY", "")
    if not key:
        return []
    try:
        body = json.dumps({"q": query, "num": 10}).encode()
        req  = urllib.request.Request(
            f"https://google.serper.dev{endpoint}",
            data=body,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())

        results = []
        # answerBox — best quick answer
        if ab := data.get("answerBox", {}):
            results.append({"title": ab.get("title", ""), "url": ab.get("link", ""),
                             "snippet": _clean(ab.get("answer") or ab.get("snippet", "")), "source": "serper"})
        # organic / news / videos
        for key_name in ("organic", "news", "videos"):
            for item in data.get(key_name, []):
                results.append({
                    "title":   _clean(item.get("title", "")),
                    "url":     item.get("link", "") or item.get("url", ""),
                    "snippet": _clean(item.get("snippet", "") or item.get("description", "")),
                    "source":  "serper",
                })
        return results[:10]
    except Exception as e:
        log.debug("Serper failed (%s): %s", endpoint, e)
        return []


# ── Tavily (AI-optimized, 1000/month free, tavily.com) ───────────────────────

def _tavily(query: str, depth: str = "basic") -> List[dict]:
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return []
    try:
        body = json.dumps({
            "api_key": key, "query": query,
            "search_depth": depth, "include_answer": True, "max_results": 10,
        }).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())

        results = []
        # Tavily returns a synthesized answer — prepend it
        if ans := data.get("answer"):
            results.append({"title": "AI Answer", "url": "", "snippet": ans, "source": "tavily-answer"})
        for item in data.get("results", []):
            results.append({
                "title":   _clean(item.get("title", "")),
                "url":     item.get("url", ""),
                "snippet": _clean(item.get("content", "")),
                "source":  "tavily",
            })
        return results[:10]
    except Exception as e:
        log.debug("Tavily failed: %s", e)
        return []


# ── SerpApi (Google, 100/day free, serpapi.com) ───────────────────────────────

def _serpapi(query: str) -> List[dict]:
    key = os.getenv("SERPAPI_KEY", "")
    if not key:
        return []
    try:
        params = urllib.parse.urlencode({"api_key": key, "q": query, "engine": "google", "num": 10})
        with urllib.request.urlopen(f"https://serpapi.com/search?{params}", timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        return [
            {"title": _clean(i.get("title", "")), "url": i.get("link", ""),
             "snippet": _clean(i.get("snippet", "")), "source": "serpapi"}
            for i in data.get("organic_results", [])[:10]
        ]
    except Exception as e:
        log.debug("SerpApi failed: %s", e)
        return []


# ── DuckDuckGo (no key, always available) ────────────────────────────────────

def _ddg(query: str) -> List[dict]:
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_redirect=1&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        results = []
        if data.get("AbstractText"):
            results.append({"title": data.get("Heading", ""), "url": data.get("AbstractURL", ""),
                             "snippet": data["AbstractText"], "source": "ddg"})
        for item in data.get("RelatedTopics", []):
            if isinstance(item, dict) and item.get("Text"):
                results.append({"title": item["Text"][:80], "url": item.get("FirstURL", ""),
                                 "snippet": item["Text"], "source": "ddg"})
            for sub in item.get("Topics", []) if isinstance(item, dict) else []:
                if sub.get("Text"):
                    results.append({"title": sub["Text"][:80], "url": sub.get("FirstURL", ""),
                                     "snippet": sub["Text"], "source": "ddg"})
            if len(results) >= 8:
                break
        return results
    except Exception as e:
        log.debug("DDG failed: %s", e)
        return []


# ── SearchCascade ─────────────────────────────────────────────────────────────

class SearchCascade:
    """Free search cascade — routes automatically, never fails completely."""

    _NEWS_KW    = {"news", "today", "latest", "breaking", "headlines", "happened"}
    _VIDEO_KW   = {"video", "footage", "clip", "watch", "youtube"}
    _SCHOLAR_KW = {"paper", "research", "study", "academic", "journal", "cite"}
    _DEEP_KW    = {"deep", "everything about", "explain in detail", "comprehensive"}

    @staticmethod
    def which_engines_available() -> dict:
        return {
            "serper":     bool(os.getenv("SERPER_API_KEY")),
            "tavily":     bool(os.getenv("TAVILY_API_KEY")),
            "serpapi":    bool(os.getenv("SERPAPI_KEY")),
            "duckduckgo": True,
        }

    @classmethod
    def search(cls, query: str, mode: str = "auto") -> dict:
        low = query.lower()
        results: List[dict] = []
        engine_used = "none"

        # Auto-route by content type
        if mode == "auto":
            if any(k in low for k in cls._NEWS_KW):
                mode = "news"
            elif any(k in low for k in cls._VIDEO_KW):
                mode = "video"
            elif any(k in low for k in cls._SCHOLAR_KW):
                mode = "scholar"
            elif any(k in low for k in cls._DEEP_KW):
                mode = "deep"
            else:
                mode = "web"

        # Route to correct endpoint
        if mode == "news":
            results = _serper(query, "/news") or _ddg(query)
            engine_used = "serper-news" if results and results[0].get("source") == "serper" else "ddg"
        elif mode == "video":
            results = _serper(query, "/videos")
            engine_used = "serper-videos"
        elif mode == "scholar":
            results = _serper(query, "/scholar") or _tavily(query, "advanced")
            engine_used = "serper-scholar" if results else "tavily"
        elif mode == "deep":
            results = _tavily(query, "advanced") or _serper(query) or _ddg(query)
            engine_used = results[0].get("source", "none") if results else "none"
        else:  # web
            results = _serper(query) or _tavily(query) or _serpapi(query) or _ddg(query)
            engine_used = results[0].get("source", "none") if results else "none"

        return {
            "ok":      bool(results),
            "query":   query,
            "mode":    mode,
            "engine":  engine_used,
            "results": results,
        }

    @classmethod
    def news_search(cls, query: str, days: int = 7) -> List[dict]:
        r = _serper(f"{query} last {days} days", "/news") or _ddg(query)
        return r

    @classmethod
    def video_search(cls, query: str) -> List[dict]:
        return _serper(query, "/videos")

    @classmethod
    def scholar_search(cls, query: str) -> List[dict]:
        return _serper(query, "/scholar") or _tavily(query, "advanced")


# Module-level convenience
_cascade = SearchCascade()


def search(query: str, max_results: int = 8) -> dict:
    r = _cascade.search(query)
    r["results"] = r["results"][:max_results]
    return r


def quick_answer(query: str) -> str:
    r = search(query, max_results=5)
    if not r["ok"]:
        return ""
    lines = [f"Search results [{r['engine']}] for '{query}':"]
    for i, item in enumerate(r["results"], 1):
        if item["snippet"]:
            lines.append(f"{i}. {item['title']}\n   {item['snippet'][:300]}")
    return "\n".join(lines)
