"""
JARVIS Deep Search — Perplexity-style: search + fetch + synthesize.

Flow:
  1. Fire searches across multiple sources in parallel
  2. Fetch the top result pages concurrently (full text extraction)
  3. Synthesize into a direct answer using the LLM, with citations
"""
from __future__ import annotations
import os, re, html, logging, concurrent.futures, urllib.request, urllib.parse
from typing import List
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_TIMEOUT = 8
_MAX_PAGE_CHARS = 4000  # chars per fetched page sent to LLM


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    title:   str
    url:     str
    snippet: str
    source:  str = ""
    content: str = ""   # fetched page text (populated later)


@dataclass
class DeepAnswer:
    query:      str
    answer:     str
    citations:  List[dict] = field(default_factory=list)
    sources:    List[str]  = field(default_factory=list)
    search_ms:  float = 0.0
    fetch_ms:   float = 0.0
    synth_ms:   float = 0.0

    @property
    def total_ms(self) -> float:
        return self.search_ms + self.fetch_ms + self.synth_ms


# ── Text extraction ────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{3,}", "\n", text)
    return text.strip()


def _fetch_page(url: str) -> str:
    """Fetch a URL and return clean plaintext (best-effort)."""
    if not url or url.startswith("javascript:"):
        return ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            raw = r.read(131072).decode("utf-8", errors="ignore")  # max 128 KB
        text = _clean(raw)
        return text[:_MAX_PAGE_CHARS]
    except Exception as e:
        log.debug("Fetch failed %s: %s", url, e)
        return ""


# ── Search backends ────────────────────────────────────────────────────────────

def _search_brave(query: str, n: int) -> List[SearchResult]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if not key:
        return []
    url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={n}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": key,
    })
    try:
        import json
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        return [
            SearchResult(
                title=item.get("title",""), url=item.get("url",""),
                snippet=_clean(item.get("description","")), source="brave"
            )
            for item in data.get("web",{}).get("results",[])[:n]
        ]
    except Exception as e:
        log.debug("Brave search: %s", e)
        return []


def _search_google(query: str, n: int) -> List[SearchResult]:
    key = os.getenv("GOOGLE_SEARCH_API_KEY","")
    cx  = os.getenv("GOOGLE_SEARCH_CX","")
    if not key or not cx:
        return []
    import json
    url = f"https://www.googleapis.com/customsearch/v1?key={key}&cx={cx}&q={urllib.parse.quote(query)}&num={min(n,10)}"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        return [
            SearchResult(
                title=item.get("title",""), url=item.get("link",""),
                snippet=_clean(item.get("snippet","")), source="google"
            )
            for item in data.get("items",[])[:n]
        ]
    except Exception as e:
        log.debug("Google search: %s", e)
        return []


def _search_ddg(query: str, n: int) -> List[SearchResult]:
    import json
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_redirect=1&no_html=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        results = []
        if data.get("AbstractText"):
            results.append(SearchResult(data.get("Heading",""), data.get("AbstractURL",""), data["AbstractText"], "ddg"))
        for item in data.get("RelatedTopics",[]):
            if isinstance(item, dict) and item.get("Text"):
                results.append(SearchResult(item["Text"][:80], item.get("FirstURL",""), item["Text"], "ddg"))
                if len(results) >= n: break
        return results[:n]
    except Exception as e:
        log.debug("DDG: %s", e)
        return []


# ── Synthesis ──────────────────────────────────────────────────────────────────

def _build_synthesis_prompt(query: str, results: List[SearchResult]) -> str:
    sources_text = ""
    for i, r in enumerate(results, 1):
        content = r.content or r.snippet
        if content:
            sources_text += f"\n[Source {i}] {r.title}\nURL: {r.url}\n{content[:1500]}\n"

    return f"""You are JARVIS, an advanced AI assistant. Answer the following question using the provided search results.

QUESTION: {query}

SEARCH RESULTS:
{sources_text}

Instructions:
- Give a direct, comprehensive answer synthesized from the sources
- Be specific — include numbers, dates, names when relevant
- Cite sources inline as [1], [2], etc.
- If the sources don't fully answer the question, say so clearly
- Keep it conversational but precise — like a brilliant assistant briefing their boss
- End with a "Sources:" section listing the URLs used"""


def _synthesize(query: str, results: List[SearchResult]) -> str:
    prompt = _build_synthesis_prompt(query, results)
    try:
        from core.llm.router import think
        return think(prompt, max_tokens=1024)
    except Exception as e:
        log.warning("Synthesis failed: %s", e)
        # Fallback: return formatted snippets
        lines = [f"Here's what I found about '{query}':\n"]
        for i, r in enumerate(results[:4], 1):
            lines.append(f"[{i}] **{r.title}**\n{r.snippet}\n")
        return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def deep_search(query: str, fetch_pages: bool = True, max_results: int = 6) -> DeepAnswer:
    """Full Perplexity-style search: multi-source search + page fetch + LLM synthesis."""
    import time

    # 1. Search multiple sources in parallel
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_brave  = pool.submit(_search_brave,  query, max_results)
        f_google = pool.submit(_search_google, query, max_results)
        f_ddg    = pool.submit(_search_ddg,    query, 3)
        brave_r  = f_brave.result()
        google_r = f_google.result()
        ddg_r    = f_ddg.result()

    # Merge and deduplicate by URL
    seen: set[str] = set()
    merged: List[SearchResult] = []
    for r in (brave_r + google_r + ddg_r):
        if r.url and r.url not in seen:
            seen.add(r.url)
            merged.append(r)
        if len(merged) >= max_results:
            break

    search_ms = (time.perf_counter() - t0) * 1000
    log.info("Search: %d results in %.0f ms (brave=%d, google=%d, ddg=%d)",
             len(merged), search_ms, len(brave_r), len(google_r), len(ddg_r))

    # 2. Fetch top pages in parallel
    fetch_ms = 0.0
    if fetch_pages and merged:
        t0 = time.perf_counter()
        urls = [r.url for r in merged[:4] if r.url]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            page_texts = list(pool.map(_fetch_page, urls))
        for r, text in zip(merged[:4], page_texts):
            if text:
                r.content = text
        fetch_ms = (time.perf_counter() - t0) * 1000
        log.info("Page fetch: %.0f ms", fetch_ms)

    # 3. Synthesize answer
    t0 = time.perf_counter()
    if not merged:
        answer = f"I couldn't find any web results for '{query}'. Please check your search API key configuration."
    else:
        answer = _synthesize(query, merged)
    synth_ms = (time.perf_counter() - t0) * 1000

    return DeepAnswer(
        query=query,
        answer=answer,
        citations=[{"index": i+1, "title": r.title, "url": r.url} for i, r in enumerate(merged)],
        sources=[r.source for r in merged],
        search_ms=round(search_ms),
        fetch_ms=round(fetch_ms),
        synth_ms=round(synth_ms),
    )


def quick_deep(query: str) -> str:
    """Return just the synthesized answer string — for brain/context integration."""
    result = deep_search(query, fetch_pages=True)
    log.info("Deep search total: %d ms (search=%d, fetch=%d, synth=%d)",
             result.total_ms, result.search_ms, result.fetch_ms, result.synth_ms)
    return result.answer
