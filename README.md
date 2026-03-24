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
python3 "server.py"
```

Open:

`http://localhost:3100`

## Restore map images quickly (if `maps/` is empty)

If your `maps/` folder was deleted or is empty, run:

```bash
python3 "download_maps.py"
```

This restores the same high-quality base map pack used earlier into `maps/`
with canonical filenames (for example: `carentan.webp`, `remagen.webp`,
`sme.webp`, `smdm.webp`, `utah.webp`, `omaha.webp`).
The downloader now validates each file (format, minimum size, checksum) and
auto-repairs invalid/corrupted files.

Optional flags:

```bash
python3 "download_maps.py" --dry-run
python3 "download_maps.py" --force
python3 "download_maps.py" --no-verify
```

## Configure

In the web UI:

- **Team view URL**: your CRCON `get_team_view` endpoint
- **Gamestate URL**: optional (or auto-derived)
- **Cookie**: copy full `Cookie` header value from CRCON request (if endpoint is closed)
- **Poll interval**: e.g. `2000`
- **Map bounds** (`xMin/xMax/yMin/yMax`): optional but recommended for fixed map scale
  - If left blank, app tries to read map bounds from gamestate/team-view payload
  - If payload has no bounds, app falls back to auto-bounds from observed player positions
- **Map visuals**: optional auto-load from gamestate map identifiers
  - Put images in `maps/` (repo root)
  - File naming is auto-resolved from gamestate in this order:
    1) `map.image_name` (or `result.image_name`)
    2) `map.shortname` (or `result.shortname`)
    3) normalized `pretty_name`
  - Supported extensions: `.webp`, `.png`, `.jpg`, `.jpeg`
  - Example: if gamestate says `image_name: "foy"`, save `maps/foy.png`

Then click **Save Config** and **Test Live**.

## Recording & Replay

- Click **Start Recording**
- Keep app running while match is live
- Click **Stop Recording**
- Select replay from dropdown and **Load Replay**
- Use timeline slider + play/pause

Replay files are saved in:

`matches/*.jsonl`

## Is there a free way to use this?

Yes:

- **Best free option**: run locally on your own PC (no hosting cost).
- Optional free hosting for frontend exists (Cloudflare Pages / GitHub Pages), but this app needs a backend proxy for authenticated CRCON requests, so local/self-hosted backend is still required.
