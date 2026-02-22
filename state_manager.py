import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class StateBackend(ABC):
    @abstractmethod
    def load(self) -> set[str]:
        ...

    @abstractmethod
    def save(self, ids: set[str]) -> None:
        ...


class JsonFileStateBackend(StateBackend):
    def __init__(self, path: str) -> None:
        self._path = path

    def load(self) -> set[str]:
        if not os.path.exists(self._path):
            logger.info("No state file found at %s, starting fresh", self._path)
            return set()

        with open(self._path, "r") as f:
            data = json.load(f)

        ids = set(data.get("processed_track_ids", []))
        logger.info("Loaded %d processed track IDs from state", len(ids))
        return ids

    def save(self, ids: set[str]) -> None:
        data = {"processed_track_ids": sorted(ids)}
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved %d processed track IDs to state", len(ids))


class StateManager:
    def __init__(self, backend: StateBackend) -> None:
        self._backend = backend

    def load(self) -> set[str]:
        return self._backend.load()

    def save(self, ids: set[str]) -> None:
        self._backend.save(ids)
