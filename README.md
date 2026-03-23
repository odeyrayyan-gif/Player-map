# Standalone Player Map App (Live + AAR)

This app is separate from the overlay system and is intended for:

- live map viewing
- match recording
- after-action replay timeline scrubbing
- hover details for player name / role / team / K:D

## Why this is separate

CRCON team-view endpoints are often authenticated and not ideal inside lightweight stream overlays.
This standalone app uses its own local backend proxy and recording storage.

## Run locally (free)

From repo root:

```bash
python3 "player_map_app/server.py"
```

Open:

`http://localhost:3100`

## Configure

In the web UI:

- **Team view URL**: your CRCON `get_team_view` endpoint
- **Gamestate URL**: optional (or auto-derived)
- **Cookie**: copy full `Cookie` header value from CRCON request (if endpoint is closed)
- **Poll interval**: e.g. `2000`

Then click **Save Config** and **Test Live**.

## Recording & Replay

- Click **Start Recording**
- Keep app running while match is live
- Click **Stop Recording**
- Select replay from dropdown and **Load Replay**
- Use timeline slider + play/pause

Replay files are saved in:

`player_map_app/matches/*.jsonl`

## Is there a free way to use this?

Yes:

- **Best free option**: run locally on your own PC (no hosting cost).
- Optional free hosting for frontend exists (Cloudflare Pages / GitHub Pages), but this app needs a backend proxy for authenticated CRCON requests, so local/self-hosted backend is still required.
