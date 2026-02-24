"""Unit tests for spotify_client.py."""

import time
import pytest
import spotipy

from unittest.mock import MagicMock, patch, call
from spotify_client import SpotifyClient, MAX_RETRIES, BACKOFF_BASE
from config import Config


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    defaults = dict(
        spotify_client_id="cid",
        spotify_client_secret="csecret",
        spotify_redirect_uri="http://localhost:8888/callback",
        spotify_token_path=".spotify_token_cache",
        youtube_client_secrets_file="client_secrets.json",
        youtube_token_path=".youtube_token_cache",
        youtube_playlist_id="PLtest",
        state_file_path="state.json",
        log_file_path="sync.log",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_spotify_page(track_ids, next_url=None):
    """Build a fake Spotify saved-tracks response page."""
    items = []
    for tid in track_ids:
        items.append({
            "track": {
                "id": tid,
                "name": f"Song {tid}",
                "artists": [{"name": "Artist A"}],
            }
        })
    return {"items": items, "next": next_url}


def _make_spotify_exception(status):
    exc = spotipy.SpotifyException(http_status=status, code=-1, msg="error")
    return exc


def _make_client_with_mock_sp(mock_sp):
    """Create a SpotifyClient whose internal _sp is already mocked."""
    config = _make_config()
    with patch("spotify_client.SpotifyOAuth") as mock_oauth_cls:
        mock_auth = MagicMock()
        mock_auth.cache_handler.get_cached_token.return_value = {"access_token": "tok"}
        mock_auth.is_token_expired.return_value = False
        mock_oauth_cls.return_value = mock_auth

        with patch("spotify_client.spotipy.Spotify", return_value=mock_sp):
            client = SpotifyClient(config)
    return client


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestSpotifyClientAuthentication:
    def test_raises_when_no_cached_token(self, tmp_path):
        """RuntimeError when no token is in cache."""
        config = _make_config(spotify_token_path=str(tmp_path / ".cache"))
        with patch("spotify_client.SpotifyOAuth") as mock_oauth_cls:
            mock_auth = MagicMock()
            mock_auth.cache_handler.get_cached_token.return_value = None
            mock_oauth_cls.return_value = mock_auth

            with pytest.raises(RuntimeError, match="No cached Spotify token"):
                SpotifyClient(config)

    def test_refreshes_expired_token(self, tmp_path):
        """Calls refresh_access_token when the cached token is expired."""
        config = _make_config(spotify_token_path=str(tmp_path / ".cache"))
        with patch("spotify_client.SpotifyOAuth") as mock_oauth_cls:
            mock_auth = MagicMock()
            mock_auth.cache_handler.get_cached_token.return_value = {
                "access_token": "old",
                "refresh_token": "refresh_tok",
            }
            mock_auth.is_token_expired.return_value = True
            mock_oauth_cls.return_value = mock_auth

            with patch("spotify_client.spotipy.Spotify"):
                SpotifyClient(config)

            mock_auth.refresh_access_token.assert_called_once_with("refresh_tok")

    def test_does_not_refresh_valid_token(self, tmp_path):
        """Does not call refresh_access_token when token is still valid."""
        config = _make_config(spotify_token_path=str(tmp_path / ".cache"))
        with patch("spotify_client.SpotifyOAuth") as mock_oauth_cls:
            mock_auth = MagicMock()
            mock_auth.cache_handler.get_cached_token.return_value = {"access_token": "valid"}
            mock_auth.is_token_expired.return_value = False
            mock_oauth_cls.return_value = mock_auth

            with patch("spotify_client.spotipy.Spotify"):
                SpotifyClient(config)

            mock_auth.refresh_access_token.assert_not_called()


# ---------------------------------------------------------------------------
# get_liked_songs()
# ---------------------------------------------------------------------------

class TestGetLikedSongs:
    def test_returns_empty_list_when_no_songs(self):
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.return_value = {"items": [], "next": None}
        client = _make_client_with_mock_sp(mock_sp)

        result = client.get_liked_songs()
        assert result == []

    def test_single_page_single_track(self):
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.return_value = _make_spotify_page(
            ["track_001"], next_url=None
        )
        client = _make_client_with_mock_sp(mock_sp)

        result = client.get_liked_songs()
        assert len(result) == 1
        assert result[0]["id"] == "track_001"
        assert result[0]["name"] == "Song track_001"
        assert result[0]["artist"] == "Artist A"

    def test_single_page_multiple_tracks(self):
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.return_value = _make_spotify_page(
            ["t1", "t2", "t3"], next_url=None
        )
        client = _make_client_with_mock_sp(mock_sp)

        result = client.get_liked_songs()
        assert len(result) == 3
        assert {r["id"] for r in result} == {"t1", "t2", "t3"}

    def test_pagination_fetches_all_pages(self):
        """Two pages: first with next URL, second with next=None."""
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.side_effect = [
            _make_spotify_page(["t1", "t2"], next_url="https://api.spotify.com/page2"),
            _make_spotify_page(["t3"], next_url=None),
        ]
        client = _make_client_with_mock_sp(mock_sp)

        result = client.get_liked_songs()
        assert len(result) == 3
        assert [r["id"] for r in result] == ["t1", "t2", "t3"]

    def test_multiple_artists_joined_with_comma(self):
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.return_value = {
            "items": [
                {
                    "track": {
                        "id": "multi",
                        "name": "Collab",
                        "artists": [
                            {"name": "Artist X"},
                            {"name": "Artist Y"},
                            {"name": "Artist Z"},
                        ],
                    }
                }
            ],
            "next": None,
        }
        client = _make_client_with_mock_sp(mock_sp)

        result = client.get_liked_songs()
        assert result[0]["artist"] == "Artist X, Artist Y, Artist Z"

    def test_uses_limit_50_per_page(self):
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.return_value = {"items": [], "next": None}
        client = _make_client_with_mock_sp(mock_sp)

        client.get_liked_songs()
        mock_sp.current_user_saved_tracks.assert_called_once_with(limit=50, offset=0)

    def test_offset_increments_per_page(self):
        """Second page call must use offset=50."""
        mock_sp = MagicMock()
        mock_sp.current_user_saved_tracks.side_effect = [
            _make_spotify_page(["t1"], next_url="next"),
            _make_spotify_page([], next_url=None),
        ]
        client = _make_client_with_mock_sp(mock_sp)

        client.get_liked_songs()
        calls = mock_sp.current_user_saved_tracks.call_args_list
        assert calls[0] == call(limit=50, offset=0)
        assert calls[1] == call(limit=50, offset=50)


# ---------------------------------------------------------------------------
# _request_with_retry()
# ---------------------------------------------------------------------------

class TestRequestWithRetry:
    def _get_client(self):
        mock_sp = MagicMock()
        return _make_client_with_mock_sp(mock_sp)

    def test_returns_result_on_first_success(self):
        client = self._get_client()
        func = MagicMock(return_value="ok")
        assert client._request_with_retry(func) == "ok"
        func.assert_called_once()

    def test_retries_on_429(self):
        client = self._get_client()
        err = _make_spotify_exception(429)
        func = MagicMock(side_effect=[err, err, "ok"])

        with patch("spotify_client.time.sleep"):
            result = client._request_with_retry(func)

        assert result == "ok"
        assert func.call_count == 3

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_server_errors(self, status):
        client = self._get_client()
        err = _make_spotify_exception(status)
        func = MagicMock(side_effect=[err, "ok"])

        with patch("spotify_client.time.sleep"):
            result = client._request_with_retry(func)

        assert result == "ok"

    def test_raises_after_max_retries_exhausted(self):
        client = self._get_client()
        err = _make_spotify_exception(429)
        # Fail MAX_RETRIES+1 times so all attempts are exhausted
        func = MagicMock(side_effect=[err] * (MAX_RETRIES + 1))

        with patch("spotify_client.time.sleep"):
            with pytest.raises(spotipy.SpotifyException):
                client._request_with_retry(func)

        assert func.call_count == MAX_RETRIES + 1

    def test_does_not_retry_non_retryable_status(self):
        client = self._get_client()
        err = _make_spotify_exception(403)
        func = MagicMock(side_effect=err)

        with pytest.raises(spotipy.SpotifyException):
            client._request_with_retry(func)

        func.assert_called_once()

    def test_sleep_uses_exponential_backoff(self):
        client = self._get_client()
        err = _make_spotify_exception(429)
        func = MagicMock(side_effect=[err, err, "ok"])

        with patch("spotify_client.time.sleep") as mock_sleep:
            client._request_with_retry(func)

        # Attempt 0 fails → wait BACKOFF_BASE^1; attempt 1 fails → wait BACKOFF_BASE^2
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [BACKOFF_BASE**1, BACKOFF_BASE**2]
