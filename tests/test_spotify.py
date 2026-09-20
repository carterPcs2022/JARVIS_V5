"""tests/test_spotify.py — regression tests for the Spotify token
persistence gap: TOKEN_FILE lives on Render's ephemeral filesystem, so
SPOTIFY_REFRESH_TOKEN exists as a durable fallback seed (same pattern as
GOOGLE_CALENDAR_REFRESH_TOKEN in server/routes/calendar_auth.py)."""
from unittest import mock
import services.spotify as spotify_mod


def test_load_token_seeds_from_env_var_when_file_missing(tmp_path):
    fake_file = tmp_path / "spotify_token.json"
    with mock.patch.object(spotify_mod, "TOKEN_FILE", fake_file), \
         mock.patch.object(spotify_mod, "SPOTIFY_REFRESH_TOKEN", "env-seeded-refresh-token"):
        token = spotify_mod.SpotifyService()._load_token()
        assert token["refresh_token"] == "env-seeded-refresh-token"
        assert token["expires_at"] == 0  # forces an immediate refresh


def test_load_token_prefers_file_over_env_var(tmp_path):
    fake_file = tmp_path / "spotify_token.json"
    fake_file.write_text('{"refresh_token": "from-disk", "access_token": "x", "expires_at": 9999999999}')
    with mock.patch.object(spotify_mod, "TOKEN_FILE", fake_file), \
         mock.patch.object(spotify_mod, "SPOTIFY_REFRESH_TOKEN", "env-seeded-refresh-token"):
        token = spotify_mod.SpotifyService()._load_token()
        assert token["refresh_token"] == "from-disk"


def test_load_token_empty_when_neither_file_nor_env_var(tmp_path):
    fake_file = tmp_path / "spotify_token.json"
    with mock.patch.object(spotify_mod, "TOKEN_FILE", fake_file), \
         mock.patch.object(spotify_mod, "SPOTIFY_REFRESH_TOKEN", ""):
        assert spotify_mod.SpotifyService()._load_token() == {}


def test_exchange_code_returns_refresh_token_not_bool(tmp_path):
    fake_file = tmp_path / "spotify_token.json"
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "access_token": "at", "refresh_token": "new-refresh-token", "expires_in": 3600,
    }
    with mock.patch.object(spotify_mod, "TOKEN_FILE", fake_file), \
         mock.patch("httpx.post", return_value=fake_response):
        result = spotify_mod.SpotifyService().exchange_code("some-code")
        assert result == "new-refresh-token"


def test_exchange_code_returns_none_on_failure(tmp_path):
    fake_file = tmp_path / "spotify_token.json"
    fake_response = mock.Mock()
    fake_response.json.return_value = {"error": "invalid_grant"}
    with mock.patch.object(spotify_mod, "TOKEN_FILE", fake_file), \
         mock.patch("httpx.post", return_value=fake_response):
        result = spotify_mod.SpotifyService().exchange_code("bad-code")
        assert result is None


def test_find_playlist_prefers_exact_user_playlist():
    service = spotify_mod.SpotifyService()
    playlists = [
        {"id": "1", "name": "Gaming", "uri": "spotify:playlist:1"},
        {"id": "2", "name": "Gaming Mix", "uri": "spotify:playlist:2"},
    ]
    with mock.patch.object(service, "get_playlists", return_value=playlists):
        assert service.find_playlist("gaming") == playlists[0]


def test_play_playlist_uses_playlist_context_uri():
    service = spotify_mod.SpotifyService()
    playlist = {"id": "1", "name": "Gaming", "uri": "spotify:playlist:1"}
    with mock.patch.object(service, "_get_access_token", return_value="token"),          mock.patch.object(service, "find_playlist", return_value=playlist),          mock.patch.object(service, "_get_devices", return_value=[{"id": "device-1", "name": "iPhone"}]),          mock.patch.object(service, "_api", return_value={"ok": True}) as api:
        result = service.play_playlist("gaming")
        assert result["playing"] is True
        assert result["playlist"] == "Gaming"
        api.assert_called_once_with(
            "PUT",
            "/me/player/play",
            data={"context_uri": "spotify:playlist:1"},
            params={"device_id": "device-1"},
        )


def test_parse_spotify_playlist_command():
    assert spotify_mod.parse_spotify_command("play my gaming playlist") == {
        "action": "playlist",
        "query": "my gaming",
    }
