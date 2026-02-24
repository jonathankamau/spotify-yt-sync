"""Unit tests for config.py."""

import os
import pytest

from config import Config, load_config, _REQUIRED_VARS


class TestConfig:
    def test_config_is_frozen(self, valid_env):
        """Config dataclass must be immutable (frozen=True)."""
        config = load_config()
        with pytest.raises((AttributeError, TypeError)):
            config.spotify_client_id = "mutated"  # type: ignore[misc]

    def test_config_fields_match_env(self, valid_env):
        """load_config() maps each env var to the correct Config field."""
        config = load_config()
        assert config.spotify_client_id == valid_env["SPOTIFY_CLIENT_ID"]
        assert config.spotify_client_secret == valid_env["SPOTIFY_CLIENT_SECRET"]
        assert config.spotify_redirect_uri == valid_env["SPOTIFY_REDIRECT_URI"]
        assert config.spotify_token_path == valid_env["SPOTIFY_TOKEN_PATH"]
        assert config.youtube_client_secrets_file == valid_env["YOUTUBE_CLIENT_SECRETS_FILE"]
        assert config.youtube_token_path == valid_env["YOUTUBE_TOKEN_PATH"]
        assert config.youtube_playlist_id == valid_env["YOUTUBE_PLAYLIST_ID"]
        assert config.state_file_path == valid_env["STATE_FILE_PATH"]
        assert config.log_file_path == valid_env["LOG_FILE_PATH"]


class TestLoadConfigMissingVars:
    def test_raises_when_all_vars_missing(self, monkeypatch):
        """EnvironmentError raised when no required vars are set."""
        for var in _REQUIRED_VARS:
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(EnvironmentError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        assert "Missing required environment variables" in error_msg

    def test_error_lists_all_missing_vars(self, monkeypatch):
        """Error message lists every missing variable name."""
        for var in _REQUIRED_VARS:
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(EnvironmentError) as exc_info:
            load_config()
        error_msg = str(exc_info.value)
        for var in _REQUIRED_VARS:
            assert var in error_msg

    def test_raises_when_single_var_missing(self, valid_env, monkeypatch):
        """EnvironmentError raised even when only one var is absent."""
        monkeypatch.delenv("YOUTUBE_PLAYLIST_ID")
        with pytest.raises(EnvironmentError) as exc_info:
            load_config()
        assert "YOUTUBE_PLAYLIST_ID" in str(exc_info.value)

    def test_raises_when_var_is_empty_string(self, valid_env, monkeypatch):
        """An empty string is treated the same as missing."""
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "")
        with pytest.raises(EnvironmentError) as exc_info:
            load_config()
        assert "SPOTIFY_CLIENT_ID" in str(exc_info.value)

    @pytest.mark.parametrize("missing_var", list(_REQUIRED_VARS.keys()))
    def test_each_required_var_individually(self, valid_env, monkeypatch, missing_var):
        """Removing any single required var causes an EnvironmentError."""
        monkeypatch.delenv(missing_var)
        with pytest.raises(EnvironmentError):
            load_config()

    def test_no_error_when_all_vars_present(self, valid_env):
        """No exception raised when all required vars are provided."""
        config = load_config()
        assert isinstance(config, Config)

    def test_error_message_includes_hints(self, valid_env, monkeypatch):
        """Error message includes the human-readable hint for the missing var."""
        monkeypatch.delenv("SPOTIFY_CLIENT_ID")
        with pytest.raises(EnvironmentError) as exc_info:
            load_config()
        # The hint text from _REQUIRED_VARS is included
        assert "Spotify Developer Dashboard" in str(exc_info.value)
