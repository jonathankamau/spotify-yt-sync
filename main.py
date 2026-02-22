import argparse
import logging
import sys

from config import load_config
from spotify_client import SpotifyClient
from youtube_client import YouTubeClient
from state_manager import StateManager, JsonFileStateBackend


def setup_logging(log_file_path: str) -> None:
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Spotify liked songs to YouTube playlist")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without modifying the YouTube playlist")
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.log_file_path)
    logger = logging.getLogger(__name__)

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no changes will be made ===")

    logger.info("Starting Spotify → YouTube sync")

    state_mgr = StateManager(JsonFileStateBackend(config.state_file_path))
    processed_ids = state_mgr.load()

    spotify = SpotifyClient(config)
    liked_songs = spotify.get_liked_songs()

    new_tracks = [t for t in liked_songs if t["id"] not in processed_ids]
    logger.info("%d new tracks to process (out of %d total liked songs)", len(new_tracks), len(liked_songs))

    if not new_tracks:
        logger.info("No new tracks to sync. Done.")
        return

    youtube = YouTubeClient(config)

    if not youtube.validate_playlist(config.youtube_playlist_id):
        logger.error("Cannot access YouTube playlist %s. Aborting.", config.youtube_playlist_id)
        sys.exit(1)

    existing_video_ids = youtube.get_playlist_video_ids(config.youtube_playlist_id)

    added_count = 0
    skipped_count = 0
    not_found_count = 0

    for track in new_tracks:
        track_label = f"'{track['name']}' by {track['artist']}"
        try:
            video_id = youtube.search_video(track["name"], track["artist"])

            if video_id is None:
                logger.warning("No video found for %s — skipping permanently", track_label)
                not_found_count += 1
                processed_ids.add(track["id"])
                continue

            if video_id in existing_video_ids:
                logger.info("Video %s already in playlist — skipping %s", video_id, track_label)
                skipped_count += 1
                processed_ids.add(track["id"])
                continue

            if args.dry_run:
                logger.info("[DRY RUN] Would add video %s for %s", video_id, track_label)
            else:
                youtube.add_video_to_playlist(config.youtube_playlist_id, video_id)
                existing_video_ids.add(video_id)
                added_count += 1

            processed_ids.add(track["id"])

        except Exception:
            logger.exception("Error processing %s — continuing with next track", track_label)

    if not args.dry_run:
        state_mgr.save(processed_ids)

    logger.info(
        "Sync complete: %d added, %d already in playlist, %d not found on YouTube",
        added_count,
        skipped_count,
        not_found_count,
    )


if __name__ == "__main__":
    main()
