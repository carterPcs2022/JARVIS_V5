"""
JARVIS V5 - Entertainment Intelligence Service
Spotify control, movies via TMDB, YouTube search, books via Open Library.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

READING_LIST_FILE = BASE_DIR / "memory" / "reading_list.json"

# Optional imports
try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False
    spotipy = None

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    _requests = None

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    yt_dlp = None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load {path}: {e}")
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


class EntertainmentIntelligence:
    """Handles Spotify, movies, YouTube, books, and reading list management."""

    def _get_spotify(self):
        """Return authenticated Spotipy client or None if not configured."""
        if not SPOTIPY_AVAILABLE:
            return None
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8080")
        if not client_id or not client_secret:
            return None
        try:
            sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    scope=(
                        "user-read-playback-state "
                        "user-modify-playback-state "
                        "user-read-currently-playing"
                    ),
                    open_browser=False,
                )
            )
            return sp
        except Exception as e:
            logger.error(f"Spotify auth failed: {e}")
            return None

    # ─── SPOTIFY ───────────────────────────────────────────────────────────────

    def spotify_now_playing(self) -> dict:
        """Return currently playing track info or not_configured if unavailable."""
        sp = self._get_spotify()
        if not sp:
            return {
                "status": "not_configured",
                "message": "Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and SPOTIFY_REDIRECT_URI env vars.",
            }

        try:
            pb = sp.current_playback()
            if not pb or not pb.get("item"):
                return {"status": "ok", "is_playing": False, "message": "Nothing currently playing."}

            item = pb["item"]
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            album = item.get("album", {})

            return {
                "status": "ok",
                "is_playing": pb.get("is_playing", False),
                "track": item.get("name"),
                "artist": artists,
                "album": album.get("name"),
                "album_art": (album.get("images") or [{}])[0].get("url"),
                "progress_ms": pb.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
                "device": pb.get("device", {}).get("name"),
                "volume_pct": pb.get("device", {}).get("volume_percent"),
                "track_uri": item.get("uri"),
                "spotify_url": item.get("external_urls", {}).get("spotify"),
            }
        except Exception as e:
            logger.error(f"Spotify now_playing error: {e}")
            return {"status": "error", "message": str(e)}

    def spotify_control(self, action: str) -> dict:
        """
        Control Spotify playback.
        Actions: play, pause, next, previous, volume_up, volume_down
        """
        sp = self._get_spotify()
        if not sp:
            return {
                "status": "not_configured",
                "message": "Spotify not configured.",
            }

        action = action.lower().strip()
        try:
            if action == "play":
                sp.start_playback()
                return {"status": "ok", "action": "play", "message": "Playback started."}

            elif action == "pause":
                sp.pause_playback()
                return {"status": "ok", "action": "pause", "message": "Playback paused."}

            elif action == "next":
                sp.next_track()
                return {"status": "ok", "action": "next", "message": "Skipped to next track."}

            elif action == "previous":
                sp.previous_track()
                return {"status": "ok", "action": "previous", "message": "Went to previous track."}

            elif action in ("volume_up", "volume_down"):
                pb = sp.current_playback()
                current_vol = pb.get("device", {}).get("volume_percent", 50) if pb else 50
                delta = 10 if action == "volume_up" else -10
                new_vol = max(0, min(100, current_vol + delta))
                sp.volume(new_vol)
                return {
                    "status": "ok",
                    "action": action,
                    "volume": new_vol,
                    "message": f"Volume set to {new_vol}%.",
                }

            else:
                return {
                    "status": "error",
                    "message": f"Unknown action '{action}'. Valid: play, pause, next, previous, volume_up, volume_down.",
                }
        except Exception as e:
            logger.error(f"Spotify control error ({action}): {e}")
            return {"status": "error", "action": action, "message": str(e)}

    # ─── MOVIES ────────────────────────────────────────────────────────────────

    def movie_search(self, query: str) -> dict:
        """Search for movies via TMDB API. Requires TMDB_API_KEY env var."""
        api_key = os.environ.get("TMDB_API_KEY")
        if not api_key:
            return {
                "status": "not_configured",
                "message": "Set TMDB_API_KEY env var to enable movie search.",
                "results": [],
            }

        if not REQUESTS_AVAILABLE:
            return {"status": "error", "message": "requests library not installed.", "results": []}

        url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={query}&include_adult=false"
        try:
            resp = _requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for m in data.get("results", [])[:10]:
                year = ""
                release = m.get("release_date", "")
                if release and len(release) >= 4:
                    year = release[:4]
                poster = m.get("poster_path")
                results.append({
                    "title": m.get("title"),
                    "year": year,
                    "rating": m.get("vote_average"),
                    "overview": m.get("overview"),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "tmdb_id": m.get("id"),
                    "popularity": m.get("popularity"),
                })
            return {"status": "ok", "query": query, "results": results, "total": data.get("total_results", 0)}
        except Exception as e:
            logger.error(f"TMDB search error: {e}")
            return {"status": "error", "message": str(e), "results": []}

    def what_to_watch(self, mood: str = "") -> str:
        """LLM recommends something to watch based on mood and time of day."""
        from core.llm.router import think

        hour = datetime.now().hour
        if hour < 6:
            time_of_day = "late night"
        elif hour < 12:
            time_of_day = "morning"
        elif hour < 17:
            time_of_day = "afternoon"
        elif hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        mood_context = f"Mood: {mood}" if mood else "No specific mood specified."
        prompt = (
            f"You are JARVIS, an AI assistant. Recommend 3 things to watch right now. "
            f"Time of day: {time_of_day}. {mood_context}. "
            f"Include a mix of genres appropriate for the time/mood. "
            f"For each, give title, type (movie/series), and a one-sentence reason. "
            f"Keep it under 150 words, JARVIS style."
        )
        return think(prompt)

    def movie_info(self, title: str) -> dict:
        """Search for movie and return full details via TMDB."""
        api_key = os.environ.get("TMDB_API_KEY")
        if not api_key:
            return {
                "status": "not_configured",
                "message": "Set TMDB_API_KEY env var.",
                "title": title,
            }

        if not REQUESTS_AVAILABLE:
            return {"status": "error", "message": "requests library not installed."}

        # First search for the movie
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={title}"
        try:
            resp = _requests.get(search_url, timeout=10)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return {"status": "not_found", "title": title, "message": "No movie found with that title."}

            movie_id = results[0]["id"]
            # Fetch full details
            detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={api_key}&append_to_response=credits,videos"
            resp2 = _requests.get(detail_url, timeout=10)
            resp2.raise_for_status()
            m = resp2.json()

            poster = m.get("poster_path")
            backdrop = m.get("backdrop_path")
            director = next(
                (c["name"] for c in m.get("credits", {}).get("crew", []) if c.get("job") == "Director"),
                None,
            )
            cast = [c["name"] for c in m.get("credits", {}).get("cast", [])[:5]]
            trailer = next(
                (v for v in m.get("videos", {}).get("results", []) if v.get("type") == "Trailer"),
                None,
            )

            return {
                "status": "ok",
                "tmdb_id": m.get("id"),
                "title": m.get("title"),
                "original_title": m.get("original_title"),
                "year": (m.get("release_date") or "")[:4],
                "rating": m.get("vote_average"),
                "vote_count": m.get("vote_count"),
                "runtime_minutes": m.get("runtime"),
                "overview": m.get("overview"),
                "genres": [g["name"] for g in m.get("genres", [])],
                "director": director,
                "cast": cast,
                "budget": m.get("budget"),
                "revenue": m.get("revenue"),
                "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                "backdrop_url": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                "trailer_url": (
                    f"https://www.youtube.com/watch?v={trailer['key']}" if trailer else None
                ),
                "imdb_id": m.get("imdb_id"),
            }
        except Exception as e:
            logger.error(f"TMDB movie_info error for '{title}': {e}")
            return {"status": "error", "title": title, "message": str(e)}

    # ─── YOUTUBE ───────────────────────────────────────────────────────────────

    def youtube_search(self, query: str) -> Union[list, dict]:
        """
        Search YouTube for top 5 results using yt-dlp.
        Returns list of {title, url, duration, views} or error dict.
        """
        if not YTDLP_AVAILABLE:
            return {
                "status": "yt-dlp not installed",
                "query": query,
                "message": "Install yt-dlp: pip install yt-dlp",
            }

        try:
            ydl_opts = {
                "extract_flat": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_url = f"ytsearch5:{query}"
                info = ydl.extract_info(search_url, download=False)

            if not info or "entries" not in info:
                return []

            results = []
            for entry in info["entries"]:
                if not entry:
                    continue
                duration = entry.get("duration")
                if duration:
                    mins, secs = divmod(int(duration), 60)
                    duration_str = f"{mins}:{secs:02d}"
                else:
                    duration_str = None
                results.append({
                    "title": entry.get("title"),
                    "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                    "duration": duration_str,
                    "views": entry.get("view_count"),
                    "uploader": entry.get("uploader"),
                    "thumbnail": entry.get("thumbnail"),
                })
            return results

        except Exception as e:
            logger.error(f"YouTube search error for '{query}': {e}")
            return {"status": "error", "query": query, "message": str(e)}

    # ─── BOOKS ─────────────────────────────────────────────────────────────────

    def book_search(self, query: str) -> list:
        """
        Search Open Library (free, no key needed).
        Returns list of {title, author, year, isbn, subjects}.
        """
        if not REQUESTS_AVAILABLE:
            return [{"error": "requests library not installed"}]

        import urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://openlibrary.org/search.json?q={encoded}&limit=5"

        try:
            resp = _requests.get(url, timeout=10, headers={"User-Agent": "JARVIS/5.0"})
            resp.raise_for_status()
            data = resp.json()

            results = []
            for doc in data.get("docs", []):
                isbn_list = doc.get("isbn", [])
                isbn = isbn_list[0] if isbn_list else None
                subjects = doc.get("subject", [])[:5]
                authors = doc.get("author_name", [])
                results.append({
                    "title": doc.get("title"),
                    "author": ", ".join(authors[:3]) if authors else None,
                    "year": doc.get("first_publish_year"),
                    "isbn": isbn,
                    "subjects": subjects,
                    "edition_count": doc.get("edition_count"),
                    "open_library_key": doc.get("key"),
                })
            return results

        except Exception as e:
            logger.error(f"Open Library search error for '{query}': {e}")
            return [{"error": str(e), "query": query}]

    def book_summary(self, title: str) -> str:
        """Generate a book summary using LLM knowledge."""
        from core.llm.router import think

        prompt = (
            f"You are JARVIS, an AI assistant. Provide a concise, informative summary of the book "
            f"'{title}'. Include: author, publication year, main themes, key takeaways, and who "
            f"should read it. Keep it under 200 words in JARVIS's professional style."
        )
        return think(prompt)

    # ─── READING LIST ──────────────────────────────────────────────────────────

    def reading_list_add(self, book: Union[dict, str]) -> list:
        """Add a book to the reading list. Accepts dict or string title."""
        reading_list = _load_json(READING_LIST_FILE, [])

        if isinstance(book, str):
            book_entry = {
                "title": book,
                "added": datetime.now().isoformat(),
                "status": "to_read",
            }
        elif isinstance(book, dict):
            book_entry = {**book, "added": book.get("added", datetime.now().isoformat()), "status": "to_read"}
        else:
            book_entry = {"raw": str(book), "added": datetime.now().isoformat(), "status": "to_read"}

        reading_list.append(book_entry)
        _save_json(READING_LIST_FILE, reading_list)
        return reading_list

    def reading_list_get(self) -> list:
        """Return current reading list from memory/reading_list.json."""
        return _load_json(READING_LIST_FILE, [])


entertainment = EntertainmentIntelligence()
