"""
Integration tests for the main.py sync orchestration.

These tests wire together real StateManager/SyncState objects while
mocking the external API clients (SpotifyClient, YouTubeClient) and
I/O side-effects (load_config, setup_logging, sys.exit).
"""

from unittest.mock import MagicMock, patch

import pytest

from config import Config
from state_manager import JsonFileStateBackend, StateManager, SyncState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(state_file_path: str, log_file_path: str = "sync.log") -> Config:
    return Config(
        spotify_client_id="cid",
        spotify_client_secret="csecret",
        spotify_redirect_uri="http://localhost:8888/callback",
        spotify_token_path=".spotify_token_cache",
        youtube_client_secrets_file="client_secrets.json",
        youtube_token_path=".youtube_token_cache",
        youtube_playlist_id="PLtest",
        state_file_path=state_file_path,
        log_file_path=log_file_path,
    )


def _make_liked_song(track_id: str, name: str = None, artist: str = "Artist") -> dict:
    return {"id": track_id, "name": name or f"Song {track_id}", "artist": artist}


def _run_main(
    *,
    liked_songs: list[dict],
    initial_state: SyncState,
    video_search_map: dict[str, str | None],
    playlist_videos: set[str] | None = None,
    playlist_item_map: dict[str, str] | None = None,
    dry_run: bool = False,
    state_file_path: str,
    validate_playlist_result: bool = True,
):
    """
    Execute main.main() with fully mocked external dependencies.

    Returns the SyncState that was saved (or the final in-memory state
    for dry-run mode where save() is not called).
    """
    config = _make_config(state_file_path)

    mock_spotify = MagicMock()
    mock_spotify.get_liked_songs.return_value = liked_songs

    mock_youtube = MagicMock()
    mock_youtube.validate_playlist.return_value = validate_playlist_result

    # search_video: look up by track name (first token before space)
    def _search_video(name, artist):
        # Build a key "name - artist" the same way tests do
        key = f"{name} - {artist}"
        return video_search_map.get(key, video_search_map.get(name))

    mock_youtube.search_video.side_effect = _search_video

    # playlist item map (video_id → playlist_item_id)
    _item_map = playlist_item_map or {}
    mock_youtube.get_playlist_item_map.return_value = _item_map
    mock_youtube.get_playlist_video_ids.return_value = playlist_videos or set(_item_map.keys())

    # Capture what state is saved
    saved_state: SyncState | None = None
    real_backend = JsonFileStateBackend(state_file_path)

    original_save = real_backend.save

    def _capture_save(state):
        nonlocal saved_state
        saved_state = SyncState(
            processed_ids=set(state.processed_ids),
            track_video_map=dict(state.track_video_map),
        )
        original_save(state)

    argv = ["main.py"]
    if dry_run:
        argv.append("--dry-run")

    with (
        patch("main.load_config", return_value=config),
        patch("main.setup_logging"),
        patch("main.SpotifyClient", return_value=mock_spotify),
        patch("main.YouTubeClient", return_value=mock_youtube),
        patch("main.StateManager") as mock_mgr_cls,
    ):
        # Wire StateManager to the real JsonFileStateBackend so disk state works
        real_mgr = StateManager(real_backend)
        real_mgr.save = _capture_save  # type: ignore[method-assign]
        mock_mgr_cls.return_value = real_mgr

        with patch("sys.argv", argv):
            import main

            main.main()

    # For dry-run, save is not called → read current in-memory state instead
    if saved_state is None:
        saved_state = real_mgr.load()

    return saved_state, mock_youtube, mock_spotify


# ---------------------------------------------------------------------------
# No-op scenarios
# ---------------------------------------------------------------------------


class TestNoChanges:
    def test_no_sync_needed_when_no_songs(self, tmp_path):
        """When Spotify returns 0 songs and state is empty, nothing happens."""
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        _, mock_yt, _ = _run_main(
            liked_songs=[],
            initial_state=SyncState(),
            video_search_map={},
            state_file_path=state_path,
        )

        mock_yt.add_video_to_playlist.assert_not_called()
        mock_yt.remove_playlist_item.assert_not_called()

    def test_no_sync_needed_when_all_already_processed(self, tmp_path):
        """All liked songs already processed → no API calls for add/remove."""
        state_path = str(tmp_path / "state.json")
        songs = [_make_liked_song("t1"), _make_liked_song("t2")]
        initial = SyncState(
            processed_ids={"t1", "t2"},
            track_video_map={"t1": "v1", "t2": "v2"},
        )
        JsonFileStateBackend(state_path).save(initial)

        _, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=initial,
            video_search_map={},
            state_file_path=state_path,
        )

        mock_yt.validate_playlist.assert_not_called()
        mock_yt.add_video_to_playlist.assert_not_called()
        mock_yt.remove_playlist_item.assert_not_called()


# ---------------------------------------------------------------------------
# Addition scenarios
# ---------------------------------------------------------------------------


class TestAddNewTracks:
    def test_adds_single_new_track(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Song One", "Band")]
        final_state, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={"Song One - Band": "vid_001"},
            state_file_path=state_path,
        )

        mock_yt.add_video_to_playlist.assert_called_once_with("PLtest", "vid_001")
        assert "t1" in final_state.processed_ids
        assert final_state.track_video_map["t1"] == "vid_001"

    def test_adds_multiple_new_tracks(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [
            _make_liked_song("t1", "Alpha", "Ar"),
            _make_liked_song("t2", "Beta", "Ar"),
        ]
        final_state, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={"Alpha - Ar": "v1", "Beta - Ar": "v2"},
            state_file_path=state_path,
        )

        assert mock_yt.add_video_to_playlist.call_count == 2
        assert final_state.processed_ids == {"t1", "t2"}

    def test_marks_processed_when_video_not_found(self, tmp_path):
        """Track with no YouTube result is still marked processed (skipped permanently)."""
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Obscure Song", "Niche")]
        final_state, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={},  # no video found
            state_file_path=state_path,
        )

        mock_yt.add_video_to_playlist.assert_not_called()
        assert "t1" in final_state.processed_ids

    def test_skips_adding_video_already_in_playlist(self, tmp_path):
        """Video found in playlist → mark processed, skip add, update map."""
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Existing", "Band")]
        final_state, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={"Existing - Band": "vid_already"},
            playlist_item_map={"vid_already": "item_123"},
            state_file_path=state_path,
        )

        mock_yt.add_video_to_playlist.assert_not_called()
        assert "t1" in final_state.processed_ids
        assert final_state.track_video_map["t1"] == "vid_already"

    def test_does_not_add_already_processed_tracks(self, tmp_path):
        """Already-processed tracks are ignored even if liked again."""
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t1"},
            track_video_map={"t1": "vid_old"},
        )
        JsonFileStateBackend(state_path).save(initial)

        songs = [_make_liked_song("t1", "Already Done", "Band")]
        _, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=initial,
            video_search_map={"Already Done - Band": "vid_old"},
            state_file_path=state_path,
        )

        mock_yt.add_video_to_playlist.assert_not_called()

    def test_limits_additions_to_max_tracks_per_run(self, tmp_path):
        """Only MAX_TRACKS_PER_RUN (15) tracks are added per run."""
        from main import MAX_TRACKS_PER_RUN

        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        # Create more songs than the limit
        n = MAX_TRACKS_PER_RUN + 5
        songs = [_make_liked_song(f"t{i}", f"Song {i}", "Band") for i in range(n)]
        search_map = {f"Song {i} - Band": f"vid_{i}" for i in range(n)}

        _, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map=search_map,
            state_file_path=state_path,
        )

        assert mock_yt.add_video_to_playlist.call_count <= MAX_TRACKS_PER_RUN

    def test_continues_after_individual_track_add_failure(self, tmp_path):
        """Exception on one track's add does not stop subsequent tracks."""
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [
            _make_liked_song("t1", "Song One", "Band"),
            _make_liked_song("t2", "Song Two", "Band"),
        ]

        def _search_side_effect(name, artist):
            if name == "Song One":
                raise Exception("transient error")
            return "vid_two"

        config = _make_config(state_path)
        mock_spotify = MagicMock()
        mock_spotify.get_liked_songs.return_value = songs
        mock_youtube = MagicMock()
        mock_youtube.validate_playlist.return_value = True
        mock_youtube.search_video.side_effect = _search_side_effect
        mock_youtube.get_playlist_video_ids.return_value = set()
        mock_youtube.get_playlist_item_map.return_value = {}

        real_backend = JsonFileStateBackend(state_path)

        with (
            patch("main.load_config", return_value=config),
            patch("main.setup_logging"),
            patch("main.SpotifyClient", return_value=mock_spotify),
            patch("main.YouTubeClient", return_value=mock_youtube),
            patch("main.StateManager", return_value=StateManager(real_backend)),
            patch("sys.argv", ["main.py"]),
        ):
            import main

            main.main()

        # t2 must still be added despite t1 failing
        mock_youtube.add_video_to_playlist.assert_called_once_with("PLtest", "vid_two")


# ---------------------------------------------------------------------------
# Removal scenarios
# ---------------------------------------------------------------------------


class TestRemoveUnlikedTracks:
    def test_removes_unliked_track_from_playlist(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_unliked"},
            track_video_map={"t_unliked": "vid_unliked"},
        )
        JsonFileStateBackend(state_path).save(initial)

        # Spotify returns empty (all songs unliked)
        final_state, mock_yt, _ = _run_main(
            liked_songs=[],
            initial_state=initial,
            video_search_map={},
            playlist_item_map={"vid_unliked": "item_001"},
            state_file_path=state_path,
        )

        mock_yt.remove_playlist_item.assert_called_once_with("item_001")
        assert "t_unliked" not in final_state.processed_ids
        assert "t_unliked" not in final_state.track_video_map

    def test_cleans_state_when_video_not_in_playlist(self, tmp_path):
        """Video mapped but already removed from playlist → state cleaned, no API call."""
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t1"},
            track_video_map={"t1": "vid_gone"},
        )
        JsonFileStateBackend(state_path).save(initial)

        final_state, mock_yt, _ = _run_main(
            liked_songs=[],
            initial_state=initial,
            video_search_map={},
            playlist_item_map={},  # video not in playlist
            state_file_path=state_path,
        )

        mock_yt.remove_playlist_item.assert_not_called()
        assert "t1" not in final_state.processed_ids

    def test_cleans_state_when_no_video_mapping(self, tmp_path):
        """Track in processed_ids but no video mapping → removed from state, no API call."""
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_no_map"},
            track_video_map={},  # no mapping for this track
        )
        JsonFileStateBackend(state_path).save(initial)

        final_state, mock_yt, _ = _run_main(
            liked_songs=[],
            initial_state=initial,
            video_search_map={},
            playlist_item_map={},
            state_file_path=state_path,
        )

        mock_yt.remove_playlist_item.assert_not_called()
        assert "t_no_map" not in final_state.processed_ids

    def test_limits_removals_to_max_per_run(self, tmp_path):
        """Only MAX_REMOVALS_PER_RUN (15) removals happen per run."""
        from main import MAX_REMOVALS_PER_RUN

        state_path = str(tmp_path / "state.json")
        track_ids = [f"t{i}" for i in range(MAX_REMOVALS_PER_RUN + 5)]
        track_video = {tid: f"vid_{tid}" for tid in track_ids}
        item_map = {f"vid_{tid}": f"item_{tid}" for tid in track_ids}

        initial = SyncState(
            processed_ids=set(track_ids),
            track_video_map=track_video,
        )
        JsonFileStateBackend(state_path).save(initial)

        _, mock_yt, _ = _run_main(
            liked_songs=[],  # all unliked
            initial_state=initial,
            video_search_map={},
            playlist_item_map=item_map,
            state_file_path=state_path,
        )

        assert mock_yt.remove_playlist_item.call_count <= MAX_REMOVALS_PER_RUN

    def test_continues_after_removal_failure(self, tmp_path):
        """Exception on one removal does not abort the rest."""
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t1", "t2"},
            track_video_map={"t1": "vid_1", "t2": "vid_2"},
        )
        JsonFileStateBackend(state_path).save(initial)

        config = _make_config(state_path)
        mock_spotify = MagicMock()
        mock_spotify.get_liked_songs.return_value = []  # all unliked

        call_count = 0

        def _remove_side_effect(item_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("removal failure")

        mock_youtube = MagicMock()
        mock_youtube.validate_playlist.return_value = True
        mock_youtube.get_playlist_item_map.return_value = {
            "vid_1": "item_1",
            "vid_2": "item_2",
        }
        mock_youtube.remove_playlist_item.side_effect = _remove_side_effect

        real_backend = JsonFileStateBackend(state_path)

        with (
            patch("main.load_config", return_value=config),
            patch("main.setup_logging"),
            patch("main.SpotifyClient", return_value=mock_spotify),
            patch("main.YouTubeClient", return_value=mock_youtube),
            patch("main.StateManager", return_value=StateManager(real_backend)),
            patch("sys.argv", ["main.py"]),
        ):
            import main

            main.main()

        # Both removals were attempted
        assert mock_youtube.remove_playlist_item.call_count == 2


# ---------------------------------------------------------------------------
# Mixed add + remove
# ---------------------------------------------------------------------------


class TestMixedAddAndRemove:
    def test_adds_new_and_removes_unliked_in_same_run(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_old"},
            track_video_map={"t_old": "vid_old"},
        )
        JsonFileStateBackend(state_path).save(initial)

        songs = [_make_liked_song("t_new", "New Song", "Band")]
        final_state, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=initial,
            video_search_map={"New Song - Band": "vid_new"},
            playlist_item_map={"vid_old": "item_old"},
            state_file_path=state_path,
        )

        mock_yt.remove_playlist_item.assert_called_once_with("item_old")
        mock_yt.add_video_to_playlist.assert_called_once_with("PLtest", "vid_new")
        assert "t_old" not in final_state.processed_ids
        assert "t_new" in final_state.processed_ids


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


class TestDryRunMode:
    def test_dry_run_does_not_add_to_playlist(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Song A", "Band")]
        _, mock_yt, _ = _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={"Song A - Band": "vid_001"},
            state_file_path=state_path,
            dry_run=True,
        )

        mock_yt.add_video_to_playlist.assert_not_called()

    def test_dry_run_does_not_remove_from_playlist(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_unliked"},
            track_video_map={"t_unliked": "vid_gone"},
        )
        JsonFileStateBackend(state_path).save(initial)

        _, mock_yt, _ = _run_main(
            liked_songs=[],
            initial_state=initial,
            video_search_map={},
            playlist_item_map={"vid_gone": "item_001"},
            state_file_path=state_path,
            dry_run=True,
        )

        mock_yt.remove_playlist_item.assert_not_called()

    def test_dry_run_does_not_save_state(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Song A", "Band")]

        config = _make_config(state_path)
        mock_spotify = MagicMock()
        mock_spotify.get_liked_songs.return_value = songs
        mock_youtube = MagicMock()
        mock_youtube.validate_playlist.return_value = True
        mock_youtube.search_video.return_value = "vid_001"
        mock_youtube.get_playlist_item_map.return_value = {}
        mock_youtube.get_playlist_video_ids.return_value = set()

        real_backend = JsonFileStateBackend(state_path)
        mock_mgr = MagicMock(wraps=StateManager(real_backend))

        with (
            patch("main.load_config", return_value=config),
            patch("main.setup_logging"),
            patch("main.SpotifyClient", return_value=mock_spotify),
            patch("main.YouTubeClient", return_value=mock_youtube),
            patch("main.StateManager", return_value=mock_mgr),
            patch("sys.argv", ["main.py", "--dry-run"]),
        ):
            import main

            main.main()

        mock_mgr.save.assert_not_called()


# ---------------------------------------------------------------------------
# Playlist validation
# ---------------------------------------------------------------------------


class TestPlaylistValidation:
    def test_aborts_when_playlist_not_accessible(self, tmp_path):
        """sys.exit(1) is called when validate_playlist() returns False."""
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Song", "Band")]

        config = _make_config(state_path)
        mock_spotify = MagicMock()
        mock_spotify.get_liked_songs.return_value = songs
        mock_youtube = MagicMock()
        mock_youtube.validate_playlist.return_value = False

        real_backend = JsonFileStateBackend(state_path)

        with (
            patch("main.load_config", return_value=config),
            patch("main.setup_logging"),
            patch("main.SpotifyClient", return_value=mock_spotify),
            patch("main.YouTubeClient", return_value=mock_youtube),
            patch("main.StateManager", return_value=StateManager(real_backend)),
            patch("sys.argv", ["main.py"]),
        ):
            import main

            with pytest.raises(SystemExit) as exc_info:
                main.main()

        assert exc_info.value.code == 1
        mock_youtube.add_video_to_playlist.assert_not_called()

    def test_youtube_client_not_instantiated_when_no_changes(self, tmp_path):
        """YouTubeClient is not created when nothing needs to sync."""
        state_path = str(tmp_path / "state.json")
        songs = [_make_liked_song("t1")]
        initial = SyncState(processed_ids={"t1"}, track_video_map={"t1": "v1"})
        JsonFileStateBackend(state_path).save(initial)

        config = _make_config(state_path)
        mock_spotify = MagicMock()
        mock_spotify.get_liked_songs.return_value = songs

        with (
            patch("main.load_config", return_value=config),
            patch("main.setup_logging"),
            patch("main.SpotifyClient", return_value=mock_spotify),
            patch("main.YouTubeClient") as mock_yt_cls,
            patch(
                "main.StateManager",
                return_value=StateManager(JsonFileStateBackend(state_path)),
            ),
            patch("sys.argv", ["main.py"]),
        ):
            import main

            main.main()

        mock_yt_cls.assert_not_called()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_state_persisted_after_successful_add(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        JsonFileStateBackend(state_path).save(SyncState())

        songs = [_make_liked_song("t1", "Track One", "Band")]
        _run_main(
            liked_songs=songs,
            initial_state=SyncState(),
            video_search_map={"Track One - Band": "vid_001"},
            state_file_path=state_path,
        )

        saved = JsonFileStateBackend(state_path).load()
        assert "t1" in saved.processed_ids
        assert saved.track_video_map["t1"] == "vid_001"

    def test_state_persisted_after_successful_remove(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_old"},
            track_video_map={"t_old": "vid_old"},
        )
        JsonFileStateBackend(state_path).save(initial)

        _run_main(
            liked_songs=[],
            initial_state=initial,
            video_search_map={},
            playlist_item_map={"vid_old": "item_001"},
            state_file_path=state_path,
        )

        saved = JsonFileStateBackend(state_path).load()
        assert "t_old" not in saved.processed_ids
        assert "t_old" not in saved.track_video_map

    def test_existing_processed_ids_preserved_on_incremental_add(self, tmp_path):
        """Pre-existing processed tracks remain in state after a new track is added."""
        state_path = str(tmp_path / "state.json")
        initial = SyncState(
            processed_ids={"t_existing"},
            track_video_map={"t_existing": "vid_existing"},
        )
        JsonFileStateBackend(state_path).save(initial)

        songs = [
            _make_liked_song("t_existing", "Old Song", "Band"),
            _make_liked_song("t_new", "New Song", "Band"),
        ]

        _run_main(
            liked_songs=songs,
            initial_state=initial,
            video_search_map={"New Song - Band": "vid_new"},
            playlist_item_map={},
            state_file_path=state_path,
        )

        saved = JsonFileStateBackend(state_path).load()
        assert "t_existing" in saved.processed_ids
        assert "t_new" in saved.processed_ids
