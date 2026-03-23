# Player Map (Standalone)

Standalone HLL Player Map + After Action Review tool.

This is intentionally separate from overlay files.

## Features

- Live map polling from CRCON endpoints
- Cookie-auth support for closed endpoints
- Player hover details (name, role, squad, team, K/D)
- Timeline replay mode
- Recording to local `.jsonl` files

## Run (Windows)

Double-click:

`start_player_map_app.bat`

Or run manually:

```bash
python3 player_map_app/server.py
