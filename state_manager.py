import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    processed_ids: set[str] = field(default_factory=set)
    track_video_map: dict[str, str] = field(default_factory=dict)
    # Maps track_id -> {"name": ..., "artist": ...} for reporting removals by name
    track_name_map: dict[str, dict[str, str]] = field(default_factory=dict)


class StateBackend(ABC):
    @abstractmethod
    def load(self) -> SyncState: ...

    @abstractmethod
    def save(self, state: SyncState) -> None: ...


class JsonFileStateBackend(StateBackend):
    def __init__(self, path: str) -> None:
        self._path = path

    def load(self) -> SyncState:
        if not os.path.exists(self._path):
            logger.info("No state file found at %s, starting fresh", self._path)
            return SyncState()

        with open(self._path) as f:
            data = json.load(f)

        processed_ids = set(data.get("processed_track_ids", []))
        track_video_map = data.get("track_video_map", {})
        track_name_map = data.get("track_name_map", {})
        logger.info("Loaded %d processed track IDs from state", len(processed_ids))
        return SyncState(
            processed_ids=processed_ids,
            track_video_map=track_video_map,
            track_name_map=track_name_map,
        )

    def save(self, state: SyncState) -> None:
        data = {
            "processed_track_ids": sorted(state.processed_ids),
            "track_video_map": dict(sorted(state.track_video_map.items())),
            "track_name_map": dict(sorted(state.track_name_map.items())),
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved %d processed track IDs to state", len(state.processed_ids))


class StateManager:
    def __init__(self, backend: StateBackend) -> None:
        self._backend = backend

    def load(self) -> SyncState:
        return self._backend.load()

    def save(self, state: SyncState) -> None:
        self._backend.save(state)
