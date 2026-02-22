import json
import logging
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import Config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2


class SpotifyClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._sp = self._authenticate()

    def _authenticate(self) -> spotipy.Spotify:
        auth_manager = SpotifyOAuth(
            client_id=self._config.spotify_client_id,
            client_secret=self._config.spotify_client_secret,
            redirect_uri=self._config.spotify_redirect_uri,
            scope="user-library-read",
            cache_path=self._config.spotify_token_path,
        )

        token_info = auth_manager.cache_handler.get_cached_token()
        if token_info is None:
            raise RuntimeError(
                f"No cached Spotify token found at {self._config.spotify_token_path}. "
                "Run setup_auth.py first."
            )

        if auth_manager.is_token_expired(token_info):
            logger.info("Spotify token expired, refreshing...")
            token_info = auth_manager.refresh_access_token(token_info["refresh_token"])

        return spotipy.Spotify(auth_manager=auth_manager)

    def get_liked_songs(self) -> list[dict]:
        tracks: list[dict] = []
        offset = 0
        limit = 50

        while True:
            results = self._request_with_retry(
                lambda o=offset: self._sp.current_user_saved_tracks(
                    limit=limit, offset=o
                )
            )
            items = results.get("items", [])
            if not items:
                break

            for item in items:
                track = item["track"]
                artists = ", ".join(a["name"] for a in track["artists"])
                tracks.append(
                    {
                        "id": track["id"],
                        "name": track["name"],
                        "artist": artists,
                    }
                )

            offset += limit
            if results.get("next") is None:
                break

        logger.info("Fetched %d liked songs from Spotify", len(tracks))
        return tracks

    def _request_with_retry(self, func, retries: int = MAX_RETRIES):
        for attempt in range(retries + 1):
            try:
                return func()
            except spotipy.SpotifyException as exc:
                if exc.http_status in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "Spotify API error %s, retrying in %ds (attempt %d/%d)",
                        exc.http_status,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(wait)
                else:
                    raise
