# Spotify Liked Songs → YouTube Playlist Sync

Automatically syncs your Spotify liked songs to a YouTube playlist by searching for each track's official music video and adding it. Runs on GitHub Actions every 6 hours — no local server required after initial setup.

## Prerequisites

- **Python 3.11+**
- **Spotify Developer account** — [developer.spotify.com](https://developer.spotify.com)
- **Google Cloud project** with YouTube Data API v3 enabled
- **GitHub Personal Access Token (PAT)** with `repo` scope

## Setup

### 1. Spotify App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create a new app
2. Set the **Redirect URI** to `http://127.0.0.1:8888/callback`
3. Copy the **Client ID** and **Client Secret**

### 2. YouTube / Google Cloud

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or use an existing one)
2. Enable the **YouTube Data API v3**
3. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
4. Select **Desktop app** as the application type
5. Download the `client_secrets.json` file
6. Base64-encode it:

   ```bash
   base64 -i client_secrets.json | tr -d '\n'
   ```

7. Copy the output — you'll need it for `bootstrap_config.json`

### 3. YouTube Playlist

1. Create a new playlist on YouTube (or use an existing one)
2. Copy the **Playlist ID** from the URL (e.g., `PLxxxxxxxxxxxxxx`)

### 4. GitHub PAT

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Generate a new token (classic) with these scopes:
   - `repo` (full control of private repositories)
3. Copy the token

### 5. Bootstrap

1. Copy `bootstrap_config.json.example` to `bootstrap_config.json`:

   ```bash
   cp bootstrap_config.json.example bootstrap_config.json
   ```

2. Fill in all the fields:

   ```json
   {
     "github_pat": "ghp_xxxxxxxxxxxx",
     "github_username": "your-username",
     "spotify_client_id": "xxxxxxxx",
     "spotify_client_secret": "xxxxxxxx",
     "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
     "youtube_client_secrets_b64": "<base64 string from step 2.6>",
     "youtube_playlist_id": "PLxxxxxxxxxxxxxx"
   }
   ```

3. Install dependencies and run the bootstrap:

   ```bash
   pip install -r requirements.txt
   python bootstrap.py
   ```

   This will:
   - Create (or update) the `spotify-yt-sync` private repo on your GitHub account
   - Upload all project files
   - Set the non-token GitHub Actions secrets

### 6. OAuth Setup

Run the one-time OAuth setup to authorize Spotify and YouTube:

```bash
python setup_auth.py
```

This will:
1. Print a Spotify authorization URL — open it in your browser and authorize
2. Print a YouTube authorization URL — open it in your browser and authorize
3. Upload both OAuth tokens as GitHub Actions secrets
4. Clean up local token files

### 7. Verify

1. Go to your repo's **Actions** tab: `https://github.com/<username>/spotify-yt-sync/actions`
2. Click **"Spotify → YouTube Sync"** in the left sidebar
3. Click **"Run workflow"** to trigger a manual run
4. Check the logs to confirm it works

## How It Works

1. The GitHub Actions workflow runs every 6 hours (or on manual trigger)
2. It decodes OAuth tokens from GitHub secrets to local files
3. `main.py` fetches all your Spotify liked songs
4. Tracks that were previously synced but are no longer liked are detected:
   - The corresponding video is removed from the YouTube playlist
   - The track is removed from the local state
5. For each new (unprocessed) track:
   - Searches YouTube for `"{track name} {artist} official music video"`
   - Adds the top result to your YouTube playlist (if not already present)
6. Updates `state.json` to track which songs have been processed and their YouTube video IDs
7. Commits `state.json` back to the repo

## Token Refresh

If your Spotify or YouTube tokens expire, re-run the setup script:

```bash
python setup_auth.py
```

The new tokens will be uploaded to GitHub Actions secrets automatically.

## Configuration

All environment variables are documented in `.env.example`. On GitHub Actions, they are injected from secrets — see the workflow file for the mapping.

## Project Structure

```
spotify-yt-sync/
├── .github/workflows/sync.yml   # GitHub Actions workflow
├── main.py                      # Orchestration / sync logic
├── spotify_client.py            # Spotify API client
├── youtube_client.py            # YouTube API client
├── state_manager.py             # Track processing state
├── config.py                    # Environment variable loading
├── bootstrap.py                 # One-time: repo + secrets setup
├── setup_auth.py                # One-time: OAuth token setup
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
├── .gitignore                   # Git ignore rules
└── README.md                    # This file
```

## Limitations / Out of Scope

- YouTube Music is not supported as a target
- Single-user only
- No web UI
- State is stored in a JSON file (DynamoDB adapter is abstracted but not implemented)
- Tracks synced before the removal feature was added lack a video mapping and cannot be automatically removed from the playlist if unliked
