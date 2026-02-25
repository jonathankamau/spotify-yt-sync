"""Unit tests for youtube_client.py."""

from unittest.mock import MagicMock, mock_open, patch

import pytest
from googleapiclient.errors import HttpError

from config import Config
from youtube_client import BACKOFF_BASE, MAX_RETRIES, YouTubeClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    defaults = {
        "spotify_client_id": "cid",
        "spotify_client_secret": "csecret",
        "spotify_redirect_uri": "http://localhost:8888/callback",
        "spotify_token_path": ".spotify_token_cache",
        "youtube_client_secrets_file": "client_secrets.json",
        "youtube_token_path": ".youtube_token_cache",
        "youtube_playlist_id": "PLtest",
        "state_file_path": "state.json",
        "log_file_path": "sync.log",
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b"error")


def _make_client_with_mock_yt(mock_yt):
    """Create a YouTubeClient whose internal _youtube is already mocked."""
    config = _make_config()
    with patch("youtube_client.Credentials") as mock_creds_cls:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.refresh_token = "refresh_tok"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        with patch("youtube_client.build", return_value=mock_yt):
            client = YouTubeClient(config)
    return client


def _make_playlist_page(video_ids, page_token=None, next_page_token=None):
    items = [{"contentDetails": {"videoId": vid}, "id": f"item_{vid}"} for vid in video_ids]
    response = {"items": items}
    if next_page_token:
        response["nextPageToken"] = next_page_token
    return response


def _make_search_response(video_ids):
    items = [{"id": {"videoId": vid}} for vid in video_ids]
    return {"items": items}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestYouTubeClientAuthentication:
    def test_raises_when_token_file_not_found(self, tmp_path):
        config = _make_config(youtube_token_path=str(tmp_path / "missing.json"))
        with patch("youtube_client.Credentials") as mock_creds_cls:
            mock_creds_cls.from_authorized_user_file.side_effect = FileNotFoundError

            with pytest.raises(RuntimeError, match="No cached YouTube token"):
                YouTubeClient(config)

    def test_raises_when_token_file_invalid(self, tmp_path):
        config = _make_config(youtube_token_path=str(tmp_path / "bad.json"))
        with patch("youtube_client.Credentials") as mock_creds_cls:
            mock_creds_cls.from_authorized_user_file.side_effect = ValueError

            with pytest.raises(RuntimeError, match="No cached YouTube token"):
                YouTubeClient(config)

    def test_raises_when_credentials_invalid_and_no_refresh_token(self):
        config = _make_config()
        with patch("youtube_client.Credentials") as mock_creds_cls:
            mock_creds = MagicMock()
            mock_creds.valid = False
            mock_creds.expired = True
            mock_creds.refresh_token = None
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds

            with pytest.raises(RuntimeError, match="invalid and cannot be refreshed"):
                YouTubeClient(config)

    def test_refreshes_expired_token(self, tmp_path):
        token_path = str(tmp_path / "token.json")
        config = _make_config(youtube_token_path=token_path)

        with patch("youtube_client.Credentials") as mock_creds_cls:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_creds.expired = True
            mock_creds.refresh_token = "rtok"
            mock_creds.to_json.return_value = '{"token": "refreshed"}'
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds

            with patch("youtube_client.Request"):
                with patch("youtube_client.build"):
                    with patch("builtins.open", mock_open()):
                        YouTubeClient(config)

            mock_creds.refresh.assert_called_once()

    def test_builds_youtube_service(self):
        config = _make_config()
        with patch("youtube_client.Credentials") as mock_creds_cls:
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_creds.expired = False
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds

            with patch("youtube_client.build") as mock_build:
                mock_build.return_value = MagicMock()
                YouTubeClient(config)

            mock_build.assert_called_once_with("youtube", "v3", credentials=mock_creds)


# ---------------------------------------------------------------------------
# search_video()
# ---------------------------------------------------------------------------


class TestSearchVideo:
    def test_returns_video_id_when_found(self):
        mock_yt = MagicMock()
        mock_yt.search().list().execute.return_value = _make_search_response(["vid_abc"])
        client = _make_client_with_mock_yt(mock_yt)

        result = client.search_video("Song Name", "Artist")
        assert result == "vid_abc"

    def test_returns_none_when_no_results(self):
        mock_yt = MagicMock()
        mock_yt.search().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        result = client.search_video("Unknown Song", "Unknown Artist")
        assert result is None

    def test_query_format_includes_official_music_video(self):
        """Search query must follow the expected format."""
        mock_yt = MagicMock()
        mock_yt.search().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        client.search_video("My Song", "My Artist")

        list_call_kwargs = mock_yt.search().list.call_args.kwargs
        assert list_call_kwargs["q"] == "My Song My Artist official music video"
        assert list_call_kwargs["type"] == "video"
        assert list_call_kwargs["maxResults"] == 1

    def test_returns_none_on_http_error(self):
        mock_yt = MagicMock()
        mock_yt.search().list().execute.side_effect = _make_http_error(403)
        client = _make_client_with_mock_yt(mock_yt)

        result = client.search_video("Song", "Artist")
        assert result is None


# ---------------------------------------------------------------------------
# get_playlist_item_map()
# ---------------------------------------------------------------------------


class TestGetPlaylistItemMap:
    def test_single_page_returns_mapping(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.return_value = _make_playlist_page(
            ["vid_1", "vid_2"]
        )
        client = _make_client_with_mock_yt(mock_yt)

        result = client.get_playlist_item_map("PLtest")
        assert result == {"vid_1": "item_vid_1", "vid_2": "item_vid_2"}

    def test_multiple_pages_combined(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.side_effect = [
            _make_playlist_page(["vid_1"], next_page_token="tok2"),
            _make_playlist_page(["vid_2"]),
        ]
        client = _make_client_with_mock_yt(mock_yt)

        result = client.get_playlist_item_map("PLtest")
        assert result == {"vid_1": "item_vid_1", "vid_2": "item_vid_2"}

    def test_empty_playlist_returns_empty_dict(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        result = client.get_playlist_item_map("PLtest")
        assert result == {}

    def test_passes_correct_playlist_id(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        client.get_playlist_item_map("PLmyList")
        list_call_kwargs = mock_yt.playlistItems().list.call_args.kwargs
        assert list_call_kwargs["playlistId"] == "PLmyList"


# ---------------------------------------------------------------------------
# get_playlist_video_ids()
# ---------------------------------------------------------------------------


class TestGetPlaylistVideoIds:
    def test_returns_set_of_video_ids(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.return_value = _make_playlist_page(
            ["vid_a", "vid_b", "vid_c"]
        )
        client = _make_client_with_mock_yt(mock_yt)

        result = client.get_playlist_video_ids("PLtest")
        assert result == {"vid_a", "vid_b", "vid_c"}

    def test_returns_empty_set_for_empty_playlist(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        result = client.get_playlist_video_ids("PLtest")
        assert result == set()


# ---------------------------------------------------------------------------
# add_video_to_playlist()
# ---------------------------------------------------------------------------


class TestAddVideoToPlaylist:
    def test_calls_insert_with_correct_body(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().insert().execute.return_value = {}
        client = _make_client_with_mock_yt(mock_yt)

        client.add_video_to_playlist("PLtest", "vid_xyz")

        insert_call_kwargs = mock_yt.playlistItems().insert.call_args.kwargs
        body = insert_call_kwargs["body"]
        assert body["snippet"]["playlistId"] == "PLtest"
        assert body["snippet"]["resourceId"]["videoId"] == "vid_xyz"
        assert body["snippet"]["resourceId"]["kind"] == "youtube#video"

    def test_executes_the_request(self):
        mock_yt = MagicMock()
        client = _make_client_with_mock_yt(mock_yt)

        client.add_video_to_playlist("PLtest", "vid_abc")
        mock_yt.playlistItems().insert().execute.assert_called()


# ---------------------------------------------------------------------------
# remove_playlist_item()
# ---------------------------------------------------------------------------


class TestRemovePlaylistItem:
    def test_calls_delete_with_correct_item_id(self):
        mock_yt = MagicMock()
        mock_yt.playlistItems().delete().execute.return_value = {}
        client = _make_client_with_mock_yt(mock_yt)

        client.remove_playlist_item("item_id_123")

        delete_call_kwargs = mock_yt.playlistItems().delete.call_args.kwargs
        assert delete_call_kwargs["id"] == "item_id_123"

    def test_executes_the_request(self):
        mock_yt = MagicMock()
        client = _make_client_with_mock_yt(mock_yt)

        client.remove_playlist_item("item_id_456")
        mock_yt.playlistItems().delete().execute.assert_called()


# ---------------------------------------------------------------------------
# validate_playlist()
# ---------------------------------------------------------------------------


class TestValidatePlaylist:
    def test_returns_true_when_playlist_found(self):
        mock_yt = MagicMock()
        mock_yt.playlists().list().execute.return_value = {"items": [{"id": "PLtest"}]}
        client = _make_client_with_mock_yt(mock_yt)

        assert client.validate_playlist("PLtest") is True

    def test_returns_false_when_no_items(self):
        mock_yt = MagicMock()
        mock_yt.playlists().list().execute.return_value = {"items": []}
        client = _make_client_with_mock_yt(mock_yt)

        assert client.validate_playlist("PLtest") is False

    def test_returns_false_on_http_error(self):
        mock_yt = MagicMock()
        mock_yt.playlists().list().execute.side_effect = _make_http_error(403)
        client = _make_client_with_mock_yt(mock_yt)

        assert client.validate_playlist("PLtest") is False


# ---------------------------------------------------------------------------
# _request_with_retry()
# ---------------------------------------------------------------------------


class TestYouTubeRequestWithRetry:
    def _get_client(self):
        return _make_client_with_mock_yt(MagicMock())

    def test_returns_result_on_first_success(self):
        client = self._get_client()
        func = MagicMock(return_value="response")
        assert client._request_with_retry(func) == "response"
        func.assert_called_once()

    def test_retries_on_429(self):
        client = self._get_client()
        err = _make_http_error(429)
        func = MagicMock(side_effect=[err, err, "ok"])

        with patch("youtube_client.time.sleep"):
            result = client._request_with_retry(func)

        assert result == "ok"
        assert func.call_count == 3

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_server_errors(self, status):
        client = self._get_client()
        err = _make_http_error(status)
        func = MagicMock(side_effect=[err, "ok"])

        with patch("youtube_client.time.sleep"):
            result = client._request_with_retry(func)

        assert result == "ok"

    def test_raises_after_max_retries_exhausted(self):
        client = self._get_client()
        err = _make_http_error(500)
        func = MagicMock(side_effect=[err] * (MAX_RETRIES + 1))

        with patch("youtube_client.time.sleep"):
            with pytest.raises(HttpError):
                client._request_with_retry(func)

        assert func.call_count == MAX_RETRIES + 1

    def test_does_not_retry_non_retryable_status(self):
        client = self._get_client()
        err = _make_http_error(403)
        func = MagicMock(side_effect=err)

        with pytest.raises(HttpError):
            client._request_with_retry(func)

        func.assert_called_once()

    def test_sleep_uses_exponential_backoff(self):
        client = self._get_client()
        err = _make_http_error(429)
        func = MagicMock(side_effect=[err, err, "ok"])

        with patch("youtube_client.time.sleep") as mock_sleep:
            client._request_with_retry(func)

        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [BACKOFF_BASE**1, BACKOFF_BASE**2]

    def test_handles_none_resp_on_http_error(self):
        """HttpError with resp.status=None (0) should not retry and should re-raise."""
        client = self._get_client()
        # Simulate an HttpError whose resp attribute is falsy (status evaluates to 0)
        err = _make_http_error(200)  # 200 is not in the retry list
        err.resp = None  # override after construction so status → 0 in _request_with_retry
        func = MagicMock(side_effect=err)

        with pytest.raises(HttpError):
            client._request_with_retry(func)

        func.assert_called_once()
