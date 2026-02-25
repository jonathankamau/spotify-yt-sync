import argparse
import logging
import sys

from config import load_config
from spotify_client import SpotifyClient
from state_manager import JsonFileStateBackend, StateManager
from youtube_client import YouTubeClient


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


MAX_TRACKS_PER_RUN = 15
MAX_REMOVALS_PER_RUN = 15


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Spotify liked songs to YouTube playlist")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without modifying the YouTube playlist",
    )
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.log_file_path)
    logger = logging.getLogger(__name__)

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no changes will be made ===")

    logger.info("Starting Spotify → YouTube sync")

    state_mgr = StateManager(JsonFileStateBackend(config.state_file_path))
    state = state_mgr.load()

    spotify = SpotifyClient(config)
    liked_songs = spotify.get_liked_songs()
    liked_ids = {t["id"] for t in liked_songs}

    # Detect unliked tracks (previously processed but no longer in liked songs)
    unliked_ids = state.processed_ids - liked_ids

    # Detect new tracks
    new_tracks = [t for t in liked_songs if t["id"] not in state.processed_ids]
    logger.info(
        "%d new tracks to add, %d unliked tracks to remove (out of %d total liked songs)",
        len(new_tracks),
        len(unliked_ids),
        len(liked_songs),
    )

    if len(new_tracks) > MAX_TRACKS_PER_RUN:
        logger.info(
            "Limiting additions to %d tracks this run to stay within YouTube API quota",
            MAX_TRACKS_PER_RUN,
        )
        new_tracks = new_tracks[:MAX_TRACKS_PER_RUN]

    unliked_list = sorted(unliked_ids)
    if len(unliked_list) > MAX_REMOVALS_PER_RUN:
        logger.info(
            "Limiting removals to %d tracks this run to stay within YouTube API quota",
            MAX_REMOVALS_PER_RUN,
        )
        unliked_list = unliked_list[:MAX_REMOVALS_PER_RUN]

    if not new_tracks and not unliked_list:
        logger.info("No changes to sync. Done.")
        return

    youtube = YouTubeClient(config)

    if not youtube.validate_playlist(config.youtube_playlist_id):
        logger.error("Cannot access YouTube playlist %s. Aborting.", config.youtube_playlist_id)
        sys.exit(1)

    # --- Remove unliked tracks ---
    removed_count = 0
    removal_failed_count = 0
    playlist_item_map: dict[str, str] | None = None

    if unliked_list:
        playlist_item_map = youtube.get_playlist_item_map(config.youtube_playlist_id)

    for track_id in unliked_list:
        video_id = state.track_video_map.get(track_id)

        if video_id is None:
            logger.warning(
                "No video mapping for track %s — removing from state without playlist change",
                track_id,
            )
            state.processed_ids.discard(track_id)
            continue

        assert playlist_item_map is not None
        playlist_item_id = playlist_item_map.get(video_id)

        if playlist_item_id is None:
            logger.info(
                "Video %s not found in playlist (may have been removed manually)"
                " — cleaning up state",
                video_id,
            )
            state.processed_ids.discard(track_id)
            state.track_video_map.pop(track_id, None)
            continue

        try:
            if args.dry_run:
                logger.info(
                    "[DRY RUN] Would remove video %s for unliked track %s",
                    video_id,
                    track_id,
                )
            else:
                youtube.remove_playlist_item(playlist_item_id)
                removed_count += 1

            state.processed_ids.discard(track_id)
            state.track_video_map.pop(track_id, None)

        except Exception:
            logger.exception(
                "Error removing video %s for track %s — continuing", video_id, track_id
            )
            removal_failed_count += 1

    # --- Add new tracks ---
    added_count = 0
    skipped_count = 0
    not_found_count = 0

    if new_tracks:
        if playlist_item_map is not None:
            existing_video_ids = set(playlist_item_map.keys())
        else:
            existing_video_ids = youtube.get_playlist_video_ids(config.youtube_playlist_id)

        for track in new_tracks:
            track_label = f"'{track['name']}' by {track['artist']}"
            try:
                video_id = youtube.search_video(track["name"], track["artist"])

                if video_id is None:
                    logger.warning("No video found for %s — skipping permanently", track_label)
                    not_found_count += 1
                    state.processed_ids.add(track["id"])
                    continue

                if video_id in existing_video_ids:
                    logger.info("Video %s already in playlist — skipping %s", video_id, track_label)
                    skipped_count += 1
                    state.processed_ids.add(track["id"])
                    state.track_video_map[track["id"]] = video_id
                    continue

                if args.dry_run:
                    logger.info("[DRY RUN] Would add video %s for %s", video_id, track_label)
                    added_count += 1
                else:
                    youtube.add_video_to_playlist(config.youtube_playlist_id, video_id)
                    existing_video_ids.add(video_id)
                    added_count += 1

                state.processed_ids.add(track["id"])
                state.track_video_map[track["id"]] = video_id

            except Exception:
                logger.exception("Error processing %s — continuing with next track", track_label)

    if not args.dry_run:
        state_mgr.save(state)

    logger.info(
        "Sync complete: %d added, %d already in playlist, %d not found on YouTube,"
        " %d removed, %d removal failures",
        added_count,
        skipped_count,
        not_found_count,
        removed_count,
        removal_failed_count,
    )


if __name__ == "__main__":
    main()
