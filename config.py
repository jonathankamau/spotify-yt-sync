import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    spotify_token_path: str

    youtube_client_secrets_file: str
    youtube_token_path: str
    youtube_playlist_id: str

    state_file_path: str
    log_file_path: str

    # Email notification settings (all optional — leave unset to disable notifications)
    email_smtp_host: str | None = None
    email_smtp_port: int = 587
    email_smtp_user: str | None = None
    email_smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None

    @property
    def email_enabled(self) -> bool:
        return all(
            [
                self.email_smtp_host,
                self.email_smtp_user,
                self.email_smtp_password,
                self.email_from,
                self.email_to,
            ]
        )


_REQUIRED_VARS = {
    "SPOTIFY_CLIENT_ID": "Spotify Developer Dashboard → Client ID",
    "SPOTIFY_CLIENT_SECRET": "Spotify Developer Dashboard → Client Secret",
    "SPOTIFY_REDIRECT_URI": "Should be http://localhost:8888/callback",
    "SPOTIFY_TOKEN_PATH": "Path to cached Spotify token file",
    "YOUTUBE_CLIENT_SECRETS_FILE": "Path to Google OAuth client_secrets.json",
    "YOUTUBE_TOKEN_PATH": "Path to cached YouTube token file",
    "YOUTUBE_PLAYLIST_ID": "Target YouTube playlist ID",
    "STATE_FILE_PATH": "Path to state.json for tracking processed tracks",
    "LOG_FILE_PATH": "Path to sync log file",
}


def load_config() -> Config:
    load_dotenv()

    missing = [f"  - {var}: {desc}" for var, desc in _REQUIRED_VARS.items() if not os.getenv(var)]
    if missing:
        raise OSError("Missing required environment variables:\n" + "\n".join(missing))

    smtp_port_raw = os.getenv("EMAIL_SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
    except ValueError:
        smtp_port = 587

    return Config(
        spotify_client_id=os.environ["SPOTIFY_CLIENT_ID"],
        spotify_client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        spotify_redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
        spotify_token_path=os.environ["SPOTIFY_TOKEN_PATH"],
        youtube_client_secrets_file=os.environ["YOUTUBE_CLIENT_SECRETS_FILE"],
        youtube_token_path=os.environ["YOUTUBE_TOKEN_PATH"],
        youtube_playlist_id=os.environ["YOUTUBE_PLAYLIST_ID"],
        state_file_path=os.environ["STATE_FILE_PATH"],
        log_file_path=os.environ["LOG_FILE_PATH"],
        email_smtp_host=os.getenv("EMAIL_SMTP_HOST") or None,
        email_smtp_port=smtp_port,
        email_smtp_user=os.getenv("EMAIL_SMTP_USER") or None,
        email_smtp_password=os.getenv("EMAIL_SMTP_PASSWORD") or None,
        email_from=os.getenv("EMAIL_FROM") or None,
        email_to=os.getenv("EMAIL_TO") or None,
    )
