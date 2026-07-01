"""core/tools/web.py — Web search, weather, URL fetch."""
import httpx, re

TIMEOUT = 12
_LIVE_KW = ["today","now","current","latest","weather","news","price",
            "score","time","live","right now","this week","breaking","search","look up"]


def search(query: str, max_results: int = 5) -> list[dict]:
    try:
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get("https://api.duckduckgo.com/", params=params,
                      headers={"User-Agent": "JARVIS/5.0"})
            data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append({"title": data.get("Heading",""), "url": data.get("AbstractURL",""),
                            "snippet": data["AbstractText"][:400]})
        for t in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if "Text" in t and "FirstURL" in t:
                results.append({"title": t["Text"][:80], "url": t["FirstURL"],
                                "snippet": t["Text"][:400]})
        return results[:max_results]
    except Exception as e:
        return [{"error": str(e)}]


def fetch(url: str, max_chars: int = 3000) -> str:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": "JARVIS/5.0"})
            text = r.text
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception as e:
        return f"[Fetch error: {e}]"


_GEO_CACHE: dict = {}

def get_weather(city: str) -> dict:
    if city not in _GEO_CACHE:
        try:
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.get("https://geocoding-api.open-meteo.com/v1/search",
                          params={"name": city, "count": 1})
                res = r.json().get("results", [])
                if res:
                    _GEO_CACHE[city] = (res[0]["latitude"], res[0]["longitude"])
        except Exception:
            return {"error": f"Could not geocode '{city}'"}
    if city not in _GEO_CACHE:
        return {"error": f"City not found: {city}"}
    lat, lon = _GEO_CACHE[city]
    try:
        params = {"latitude": lat, "longitude": lon,
                  "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,apparent_temperature",
                  "temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get("https://api.open-meteo.com/v1/forecast", params=params)
            cur = r.json()["current"]
        return {"city": city, "temp_f": cur["temperature_2m"],
                "feels_like_f": cur["apparent_temperature"],
                "humidity_pct": cur["relative_humidity_2m"],
                "wind_mph": cur["wind_speed_10m"]}
    except Exception as e:
        return {"error": str(e)}


def needs_web(query: str) -> bool:
    return any(kw in query.lower() for kw in _LIVE_KW)


def auto_search_context(query: str) -> str:
    if not needs_web(query):
        return ""
    m = re.search(r"weather (?:in |for |at )?([a-zA-Z\s]{3,30})", query, re.I)
    if m:
        w = get_weather(m.group(1).strip())
        if "error" not in w:
            return (f"[Live weather for {w['city']}]: "
                    f"{w['temp_f']}°F (feels {w['feels_like_f']}°F), "
                    f"humidity {w['humidity_pct']}%, wind {w['wind_mph']} mph")
    results = search(query, max_results=3)
    if not results or "error" in results[0]:
        return ""
    lines = ["[Live web results:]"]
    for r in results:
        if "snippet" in r:
            lines.append(f"  • {r['title']}: {r['snippet'][:200]}")
    return "\n".join(lines)
