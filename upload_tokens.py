#!/usr/bin/env python3
"""
Post-sync helper: re-uploads refreshed token files as GitHub Actions secrets.
Called by the workflow after main.py runs, so that refreshed tokens persist.
"""

import base64
import os
import sys

import requests
from nacl import encoding, public


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")


def main() -> None:
    pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GH_REPO")
    if not pat or not repo:
        print("GH_PAT and GH_REPO env vars required")
        sys.exit(1)

    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    resp = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
    )
    if resp.status_code != 200:
        print(f"Could not get repo public key: {resp.status_code}")
        sys.exit(1)

    pk_data = resp.json()
    key_id = pk_data["key_id"]
    public_key_b64 = pk_data["key"]

    token_files = {
        "SPOTIFY_TOKEN_CACHE_B64": ".spotify_token_cache",
        "YOUTUBE_TOKEN_CACHE_B64": ".youtube_token_cache",
    }

    for secret_name, file_path in token_files.items():
        if not os.path.exists(file_path):
            continue
        with open(file_path, "rb") as f:
            b64_value = base64.b64encode(f.read()).decode("utf-8")

        encrypted = encrypt_secret(public_key_b64, b64_value)
        resp = requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id},
        )
        status = "OK" if resp.status_code in (201, 204) else f"FAILED ({resp.status_code})"
        print(f"  {secret_name}: {status}")


if __name__ == "__main__":
    main()
