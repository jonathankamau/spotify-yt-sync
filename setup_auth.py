#!/usr/bin/env python3
"""
One-time OAuth setup script.

Starts a local HTTP server on port 8888 to complete Spotify and YouTube
OAuth flows, then uploads the resulting tokens as GitHub Actions secrets.

Usage:
    python setup_auth.py
"""

import base64
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse

import requests
from google_auth_oauthlib.flow import Flow
from nacl import encoding, public

CONFIG_FILE = "bootstrap_config.json"
REPO_NAME = "spotify-yt-sync"
LOCAL_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{LOCAL_PORT}/callback"

SPOTIFY_SCOPE = "user-library-read"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

SPOTIFY_TOKEN_FILE = ".spotify_token_cache"
YOUTUBE_TOKEN_FILE = ".youtube_token_cache"


class OAuthCallbackServer(http.server.HTTPServer):
    allow_reuse_address = True


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures a single OAuth callback and stores the full URL."""

    captured_url: str | None = None
    shutdown_event: threading.Event

    def do_GET(self):
        if not self.path.startswith("/callback"):
            self.send_response(204)
            self.end_headers()
            return
        OAuthCallbackHandler.captured_url = self.path
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h2>Authorization received! You can close this tab.</h2></body></html>")
        OAuthCallbackHandler.shutdown_event.set()

    def log_message(self, format, *args):
        pass


_shared_server: OAuthCallbackServer | None = None


def get_server() -> OAuthCallbackServer:
    global _shared_server
    if _shared_server is None:
        _shared_server = OAuthCallbackServer(("127.0.0.1", LOCAL_PORT), OAuthCallbackHandler)
        _shared_server.timeout = 1
    return _shared_server


def wait_for_callback() -> str:
    OAuthCallbackHandler.captured_url = None
    OAuthCallbackHandler.shutdown_event = threading.Event()

    server = get_server()

    while not OAuthCallbackHandler.shutdown_event.is_set():
        server.handle_request()

    if OAuthCallbackHandler.captured_url is None:
        print("ERROR: Timed out waiting for OAuth callback.")
        sys.exit(1)

    return OAuthCallbackHandler.captured_url


def do_spotify_auth(cfg: dict) -> None:
    print("\n--- Spotify OAuth ---", flush=True)

    params = urllib.parse.urlencode({
        "client_id": cfg["spotify_client_id"],
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SPOTIFY_SCOPE,
    })
    auth_url = f"https://accounts.spotify.com/authorize?{params}"
    print(f"\nOpen this URL in your browser to authorize Spotify:\n\n  {auth_url}\n", flush=True)

    callback_path = wait_for_callback()
    parsed = urllib.parse.urlparse(callback_path)
    query_params = urllib.parse.parse_qs(parsed.query)
    code = query_params.get("code", [None])[0]

    if not code:
        print("ERROR: No authorization code received from Spotify.")
        sys.exit(1)

    auth_b64 = base64.b64encode(f"{cfg['spotify_client_id']}:{cfg['spotify_client_secret']}".encode()).decode()
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"ERROR: Spotify token exchange failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    token_data["expires_at"] = int(time.time()) + token_data.get("expires_in", 3600)
    with open(SPOTIFY_TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    print(f"Spotify token saved to {SPOTIFY_TOKEN_FILE}", flush=True)


def do_youtube_auth(cfg: dict) -> None:
    print("\n--- YouTube OAuth ---")

    secrets_json = base64.b64decode(cfg["youtube_client_secrets_b64"]).decode("utf-8")
    secrets_path = "client_secrets.json"
    with open(secrets_path, "w") as f:
        f.write(secrets_json)

    yt_redirect = f"http://localhost:{LOCAL_PORT}/callback"
    flow = Flow.from_client_secrets_file(
        secrets_path,
        scopes=YOUTUBE_SCOPES,
        redirect_uri=yt_redirect,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    print(f"\nOpen this URL in your browser to authorize YouTube:\n\n  {auth_url}\n")

    callback_path = wait_for_callback()
    parsed = urllib.parse.urlparse(callback_path)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]

    if not code:
        error = params.get("error", ["unknown"])[0]
        error_desc = params.get("error_description", [""])[0]
        print(f"ERROR: No authorization code received from YouTube.")
        print(f"  Google returned error: {error}")
        if error_desc:
            print(f"  Description: {error_desc}")
        sys.exit(1)

    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(YOUTUBE_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"YouTube token saved to {YOUTUBE_TOKEN_FILE}")

    os.remove(secrets_path)


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")


def upload_token_secrets(cfg: dict) -> None:
    print("\n--- Uploading token secrets to GitHub Actions ---")
    headers = {
        "Authorization": f"token {cfg['github_pat']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    resp = requests.get(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/actions/secrets/public-key",
        headers=headers,
    )
    if resp.status_code != 200:
        print(f"ERROR: Could not retrieve repo public key: {resp.status_code} {resp.text}")
        sys.exit(1)

    pk_data = resp.json()
    key_id = pk_data["key_id"]
    public_key_b64 = pk_data["key"]

    token_files = {
        "SPOTIFY_TOKEN_CACHE_B64": SPOTIFY_TOKEN_FILE,
        "YOUTUBE_TOKEN_CACHE_B64": YOUTUBE_TOKEN_FILE,
    }

    for secret_name, file_path in token_files.items():
        with open(file_path, "rb") as f:
            b64_value = base64.b64encode(f.read()).decode("utf-8")

        encrypted = encrypt_secret(public_key_b64, b64_value)
        resp = requests.put(
            f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/actions/secrets/{secret_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id},
        )
        if resp.status_code in (201, 204):
            print(f"  OK: {secret_name}")
        else:
            print(f"  ERROR: {secret_name} — {resp.status_code} {resp.text}")


def cleanup_local_tokens() -> None:
    for f in [SPOTIFY_TOKEN_FILE, YOUTUBE_TOKEN_FILE]:
        if os.path.exists(f):
            os.remove(f)
            print(f"  Deleted local {f}")


def main() -> None:
    print("=" * 60)
    print("  Spotify → YouTube Sync — OAuth Setup")
    print("=" * 60)

    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: {CONFIG_FILE} not found. Run bootstrap.py first.")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        cfg = json.load(f)

    do_spotify_auth(cfg)
    do_youtube_auth(cfg)
    upload_token_secrets(cfg)

    print("\nCleaning up local token files...")
    cleanup_local_tokens()

    print("\n" + "=" * 60)
    print("  OAuth setup complete!")
    print("=" * 60)
    print("\nAll token secrets have been uploaded to GitHub Actions.")
    print("You can now trigger a sync from the Actions tab:")
    print(f"  https://github.com/{cfg['github_username']}/{REPO_NAME}/actions")
    print("\nIf tokens expire later, re-run:  python setup_auth.py")


if __name__ == "__main__":
    main()
