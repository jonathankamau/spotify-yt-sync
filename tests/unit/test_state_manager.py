"""Unit tests for state_manager.py."""

import json

from state_manager import JsonFileStateBackend, StateManager, SyncState

# ---------------------------------------------------------------------------
# SyncState dataclass
# ---------------------------------------------------------------------------


class TestSyncState:
    def test_default_processed_ids_is_empty_set(self):
        state = SyncState()
        assert state.processed_ids == set()

    def test_default_track_video_map_is_empty_dict(self):
        state = SyncState()
        assert state.track_video_map == {}

    def test_defaults_are_independent_instances(self):
        """Two SyncState instances must not share the same mutable defaults."""
        s1 = SyncState()
        s2 = SyncState()
        s1.processed_ids.add("track_001")
        assert "track_001" not in s2.processed_ids

    def test_can_set_custom_values(self):
        state = SyncState(
            processed_ids={"a", "b"},
            track_video_map={"a": "vid_a"},
        )
        assert "a" in state.processed_ids
        assert state.track_video_map["a"] == "vid_a"


# ---------------------------------------------------------------------------
# JsonFileStateBackend.load()
# ---------------------------------------------------------------------------


class TestJsonFileStateBackendLoad:
    def test_returns_empty_state_when_file_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        backend = JsonFileStateBackend(path)
        state = backend.load()
        assert state.processed_ids == set()
        assert state.track_video_map == {}

    def test_loads_processed_ids(self, tmp_path):
        path = tmp_path / "state.json"
        data = {"processed_track_ids": ["id_1", "id_2"], "track_video_map": {}}
        path.write_text(json.dumps(data))
        backend = JsonFileStateBackend(str(path))
        state = backend.load()
        assert state.processed_ids == {"id_1", "id_2"}

    def test_loads_track_video_map(self, tmp_path):
        path = tmp_path / "state.json"
        data = {
            "processed_track_ids": ["id_1"],
            "track_video_map": {"id_1": "yt_vid_abc"},
        }
        path.write_text(json.dumps(data))
        state = JsonFileStateBackend(str(path)).load()
        assert state.track_video_map == {"id_1": "yt_vid_abc"}

    def test_missing_processed_track_ids_key_defaults_to_empty(self, tmp_path):
        """State file without 'processed_track_ids' key loads gracefully."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"track_video_map": {"x": "y"}}))
        state = JsonFileStateBackend(str(path)).load()
        assert state.processed_ids == set()
        assert state.track_video_map == {"x": "y"}

    def test_missing_track_video_map_key_defaults_to_empty(self, tmp_path):
        """State file without 'track_video_map' key loads gracefully."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"processed_track_ids": ["a"]}))
        state = JsonFileStateBackend(str(path)).load()
        assert state.processed_ids == {"a"}
        assert state.track_video_map == {}

    def test_processed_ids_returned_as_set(self, tmp_path):
        path = tmp_path / "state.json"
        data = {"processed_track_ids": ["id_1", "id_1", "id_2"], "track_video_map": {}}
        path.write_text(json.dumps(data))
        state = JsonFileStateBackend(str(path)).load()
        # Duplicates in JSON list are collapsed into a set
        assert state.processed_ids == {"id_1", "id_2"}


# ---------------------------------------------------------------------------
# JsonFileStateBackend.save()
# ---------------------------------------------------------------------------


class TestJsonFileStateBackendSave:
    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        backend.save(SyncState(processed_ids={"t1"}, track_video_map={"t1": "v1"}))
        assert path.exists()

    def test_save_writes_correct_processed_ids(self, tmp_path):
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        backend.save(SyncState(processed_ids={"t1", "t2"}))
        data = json.loads(path.read_text())
        assert set(data["processed_track_ids"]) == {"t1", "t2"}

    def test_save_writes_correct_track_video_map(self, tmp_path):
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        state = SyncState(
            processed_ids={"t1"},
            track_video_map={"t1": "vid_xyz"},
        )
        backend.save(state)
        data = json.loads(path.read_text())
        assert data["track_video_map"] == {"t1": "vid_xyz"}

    def test_save_sorts_processed_ids(self, tmp_path):
        """processed_track_ids in saved file must be in sorted order."""
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        backend.save(SyncState(processed_ids={"zzz", "aaa", "mmm"}))
        data = json.loads(path.read_text())
        assert data["processed_track_ids"] == sorted(["zzz", "aaa", "mmm"])

    def test_save_sorts_track_video_map_keys(self, tmp_path):
        """track_video_map in saved file must have sorted keys."""
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        backend.save(
            SyncState(
                processed_ids=set(),
                track_video_map={"zzz": "v3", "aaa": "v1", "mmm": "v2"},
            )
        )
        data = json.loads(path.read_text())
        assert list(data["track_video_map"].keys()) == ["aaa", "mmm", "zzz"]

    def test_save_then_load_roundtrip(self, tmp_path):
        """Saving then loading must reproduce the exact same state."""
        path = str(tmp_path / "state.json")
        backend = JsonFileStateBackend(path)
        original = SyncState(
            processed_ids={"id_a", "id_b"},
            track_video_map={"id_a": "vid_1", "id_b": "vid_2"},
        )
        backend.save(original)
        loaded = backend.load()
        assert loaded.processed_ids == original.processed_ids
        assert loaded.track_video_map == original.track_video_map

    def test_save_empty_state(self, tmp_path):
        path = tmp_path / "state.json"
        JsonFileStateBackend(str(path)).save(SyncState())
        data = json.loads(path.read_text())
        assert data["processed_track_ids"] == []
        assert data["track_video_map"] == {}

    def test_save_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "state.json"
        backend = JsonFileStateBackend(str(path))
        backend.save(SyncState(processed_ids={"old_track"}))
        backend.save(SyncState(processed_ids={"new_track"}))
        data = json.loads(path.read_text())
        assert data["processed_track_ids"] == ["new_track"]


# ---------------------------------------------------------------------------
# StateManager (delegate wrapper)
# ---------------------------------------------------------------------------


class TestStateManager:
    def test_load_delegates_to_backend(self, tmp_path):
        path = tmp_path / "state.json"
        data = {"processed_track_ids": ["x"], "track_video_map": {"x": "v"}}
        path.write_text(json.dumps(data))
        mgr = StateManager(JsonFileStateBackend(str(path)))
        state = mgr.load()
        assert "x" in state.processed_ids

    def test_save_delegates_to_backend(self, tmp_path):
        path = tmp_path / "state.json"
        mgr = StateManager(JsonFileStateBackend(str(path)))
        mgr.save(SyncState(processed_ids={"saved_track"}))
        data = json.loads(path.read_text())
        assert "saved_track" in data["processed_track_ids"]

    def test_manager_uses_custom_backend(self, mocker):
        """StateManager calls backend.load() and backend.save() exactly once."""
        mock_backend = mocker.MagicMock()
        mock_backend.load.return_value = SyncState()
        mgr = StateManager(mock_backend)

        mgr.load()
        mock_backend.load.assert_called_once()

        state = SyncState()
        mgr.save(state)
        mock_backend.save.assert_called_once_with(state)
