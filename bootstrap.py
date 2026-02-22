#!/usr/bin/env python3
"""
One-time bootstrap script.

Reads bootstrap_config.json, creates (or reuses) a private GitHub repo,
commits all project files, and uploads non-token secrets to GitHub Actions.

Usage:
    python bootstrap.py
"""

import base64
import json
import os
import sys

import requests
from nacl import encoding, public

REPO_NAME = "spotify-yt-sync"

PROJECT_FILES = [
    ".github/workflows/sync.yml",
    "main.py",
    "spotify_client.py",
    "youtube_client.py",
    "state_manager.py",
    "config.py",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "README.md",
]

CONFIG_FILE = "bootstrap_config.json"


def load_bootstrap_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: {CONFIG_FILE} not found. Create it first — see README.md")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        cfg = json.load(f)
    required = [
        "github_pat",
        "github_username",
        "spotify_client_id",
        "spotify_client_secret",
        "spotify_redirect_uri",
        "youtube_client_secrets_b64",
        "youtube_playlist_id",
    ]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"ERROR: Missing keys in {CONFIG_FILE}: {', '.join(missing)}")
        sys.exit(1)
    return cfg


def github_headers(pat: str) -> dict:
    return {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_repo(cfg: dict) -> bool:
    headers = github_headers(cfg["github_pat"])
    resp = requests.get(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}",
        headers=headers,
    )
    if resp.status_code == 200:
        print(f"Repo {REPO_NAME} already exists — will push files to it.")
        return True

    print(f"Creating private repo {REPO_NAME}...")
    resp = requests.post(
        "https://api.github.com/user/repos",
        headers=headers,
        json={"name": REPO_NAME, "private": True, "auto_init": True},
    )
    if resp.status_code == 201:
        print(f"Repo {REPO_NAME} created successfully.")
        return True

    print(f"ERROR creating repo: {resp.status_code} {resp.text}")
    return False


def get_file_sha(cfg: dict, path: str) -> str | None:
    headers = github_headers(cfg["github_pat"])
    resp = requests.get(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/contents/{path}",
        headers=headers,
    )
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None


def upload_file(cfg: dict, path: str) -> bool:
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(local_path):
        print(f"  SKIP: {path} (file not found locally)")
        return False

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    headers = github_headers(cfg["github_pat"])
    sha = get_file_sha(cfg, path)

    payload: dict = {
        "message": f"feat: add {path}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/contents/{path}",
        headers=headers,
        json=payload,
    )

    if resp.status_code in (200, 201):
        action = "updated" if sha else "created"
        print(f"  OK: {path} ({action})")
        return True

    print(f"  ERROR: {path} — {resp.status_code} {resp.text}")
    return False


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")


def set_secret(cfg: dict, key_id: str, public_key_b64: str, name: str, value: str) -> bool:
    encrypted = encrypt_secret(public_key_b64, value)
    headers = github_headers(cfg["github_pat"])
    resp = requests.put(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_id},
    )
    if resp.status_code in (201, 204):
        print(f"  OK: secret {name}")
        return True
    print(f"  ERROR: secret {name} — {resp.status_code} {resp.text}")
    return False


def upload_secrets(cfg: dict) -> None:
    headers = github_headers(cfg["github_pat"])
    resp = requests.get(
        f"https://api.github.com/repos/{cfg['github_username']}/{REPO_NAME}/actions/secrets/public-key",
        headers=headers,
    )
    if resp.status_code != 200:
        print(f"ERROR: Could not retrieve repo public key: {resp.status_code} {resp.text}")
        return

    pk_data = resp.json()
    key_id = pk_data["key_id"]
    public_key_b64 = pk_data["key"]

    secrets = {
        "SPOTIFY_CLIENT_ID": cfg["spotify_client_id"],
        "SPOTIFY_CLIENT_SECRET": cfg["spotify_client_secret"],
        "SPOTIFY_REDIRECT_URI": cfg["spotify_redirect_uri"],
        "YOUTUBE_CLIENT_SECRETS_B64": cfg["youtube_client_secrets_b64"],
        "YOUTUBE_PLAYLIST_ID": cfg["youtube_playlist_id"],
    }

    print("\nUploading GitHub Actions secrets...")
    for name, value in secrets.items():
        set_secret(cfg, key_id, public_key_b64, name, value)


def main() -> None:
    print("=" * 60)
    print("  Spotify → YouTube Sync — Bootstrap")
    print("=" * 60)

    cfg = load_bootstrap_config()

    if not create_repo(cfg):
        sys.exit(1)

    print(f"\nUploading project files to {cfg['github_username']}/{REPO_NAME}...")
    for path in PROJECT_FILES:
        upload_file(cfg, path)

    upload_secrets(cfg)

    print("\n" + "=" * 60)
    print("  Bootstrap complete!")
    print("=" * 60)
    print(f"\nNext step: run  python setup_auth.py  to complete OAuth setup.")
    print(f"Repo URL: https://github.com/{cfg['github_username']}/{REPO_NAME}")


if __name__ == "__main__":
    main()
