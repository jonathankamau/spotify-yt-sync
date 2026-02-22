import logging
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube"]
MAX_RETRIES = 3
BACKOFF_BASE = 2


class YouTubeClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._youtube = self._authenticate()

    def _authenticate(self):
        creds = None
        token_path = self._config.youtube_token_path

        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except (FileNotFoundError, ValueError):
            raise RuntimeError(
                f"No cached YouTube token found at {token_path}. "
                "Run setup_auth.py first."
            )

        if creds and creds.expired and creds.refresh_token:
            logger.info("YouTube token expired, refreshing...")
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        if not creds or not creds.valid:
            raise RuntimeError(
                "YouTube credentials are invalid and cannot be refreshed. "
                "Re-run setup_auth.py."
            )

        return build("youtube", "v3", credentials=creds)

    def search_video(self, track_name: str, artist: str) -> str | None:
        query = f"{track_name} {artist} official music video"
        try:
            response = self._request_with_retry(
                lambda: self._youtube.search()
                .list(part="snippet", q=query, type="video", maxResults=1)
                .execute()
            )
            items = response.get("items", [])
            if items:
                video_id = items[0]["id"]["videoId"]
                logger.debug("Found video %s for '%s - %s'", video_id, artist, track_name)
                return video_id
            logger.warning("No YouTube result for '%s - %s'", artist, track_name)
            return None
        except HttpError as exc:
            logger.error("YouTube search failed for '%s - %s': %s", artist, track_name, exc)
            return None

    def get_playlist_video_ids(self, playlist_id: str) -> set[str]:
        video_ids: set[str] = set()
        page_token = None

        while True:
            response = self._request_with_retry(
                lambda pt=page_token: self._youtube.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=pt,
                )
                .execute()
            )

            for item in response.get("items", []):
                video_ids.add(item["contentDetails"]["videoId"])

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d existing videos in playlist %s", len(video_ids), playlist_id)
        return video_ids

    def add_video_to_playlist(self, playlist_id: str, video_id: str) -> None:
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id,
                },
            }
        }
        self._request_with_retry(
            lambda: self._youtube.playlistItems()
            .insert(part="snippet", body=body)
            .execute()
        )
        logger.info("Added video %s to playlist %s", video_id, playlist_id)

    def validate_playlist(self, playlist_id: str) -> bool:
        try:
            self._youtube.playlists().list(
                part="snippet", id=playlist_id
            ).execute()
            return True
        except HttpError as exc:
            logger.error("Cannot access playlist %s: %s", playlist_id, exc)
            return False

    def _request_with_retry(self, func, retries: int = MAX_RETRIES):
        for attempt in range(retries + 1):
            try:
                return func()
            except HttpError as exc:
                status = exc.resp.status if exc.resp else 0
                if status in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "YouTube API error %s, retrying in %ds (attempt %d/%d)",
                        status,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(wait)
                else:
                    raise
