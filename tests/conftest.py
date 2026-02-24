"""Shared pytest fixtures for spotify-yt-sync tests."""

import json
import os
import pytest


# ---------------------------------------------------------------------------
# Minimal valid environment for load_config()
# ---------------------------------------------------------------------------

VALID_ENV = {
    "SPOTIFY_CLIENT_ID": "test_spotify_client_id",
    "SPOTIFY_CLIENT_SECRET": "test_spotify_client_secret",
    "SPOTIFY_REDIRECT_URI": "http://localhost:8888/callback",
    "SPOTIFY_TOKEN_PATH": ".spotify_token_cache",
    "YOUTUBE_CLIENT_SECRETS_FILE": "client_secrets.json",
    "YOUTUBE_TOKEN_PATH": ".youtube_token_cache",
    "YOUTUBE_PLAYLIST_ID": "PLtestPlaylistId",
    "STATE_FILE_PATH": "state.json",
    "LOG_FILE_PATH": "sync.log",
}


@pytest.fixture
def valid_env(monkeypatch):
    """Set all required environment variables for load_config()."""
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    return VALID_ENV


@pytest.fixture
def sample_liked_songs():
    """Return a representative list of Spotify liked-song dicts."""
    return [
        {"id": "track_001", "name": "Song Alpha", "artist": "Artist A"},
        {"id": "track_002", "name": "Song Beta", "artist": "Artist B"},
        {"id": "track_003", "name": "Song Gamma", "artist": "Artist C"},
    ]


@pytest.fixture
def state_file(tmp_path):
    """Provide a temporary directory + helper to write state JSON."""

    def _write(processed_ids, track_video_map=None):
        path = tmp_path / "state.json"
        data = {
            "processed_track_ids": sorted(processed_ids),
            "track_video_map": track_video_map or {},
        }
        path.write_text(json.dumps(data, indent=2))
        return str(path)

    return _write
