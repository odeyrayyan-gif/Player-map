"""
Standalone Player Map + After Action Review web app.
Runs independently from the overlay server.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MATCH_DIR = os.path.join(APP_DIR, "matches")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
PORT = int(os.environ.get("PLAYER_MAP_APP_PORT", "3100"))

DEFAULT_CONFIG = {
    "live_stats_url": "",
    "team_view_url": "",
    "gamestate_url": "",
    "cookie": "",
    "poll_interval_ms": 2000,
}

STATE_LOCK = threading.Lock()
STATE = {
    "recording_id": None,
}


def ensure_dirs():
    os.makedirs(MATCH_DIR, exist_ok=True)


def read_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def write_config(update):
    cfg = read_config()
    cfg.update(update)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def dedupe_keep_order(items):
    out = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def with_cache_buster(url):
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("t", str(time.time())))
    new_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def endpoint_looks_like(endpoint, targets):
    try:
        path = urllib.parse.urlparse(endpoint).path.lower()
        return any(t.lower() in path for t in targets)
    except Exception:
        return False


def build_api_variant_url(endpoint, target_name):
    try:
        parsed = urllib.parse.urlparse(endpoint)
        parts = parsed.path.split("/")
        target = str(target_name or "").lstrip("/").lower()
        idx = next((i for i, p in enumerate(parts) if p.lower() == "get_live_game_stats"), -1)
        if idx >= 0:
            parts[idx] = target
        elif len(parts) > 1:
            parts[-1] = target
        else:
            return ""
        new_path = "/".join(parts)
        return urllib.parse.urlunparse(parsed._replace(path=new_path))
    except Exception:
        return ""


def build_variant_candidates(endpoint_seed, targets):
    variants = [build_api_variant_url(endpoint_seed, t) for t in targets]
    if endpoint_looks_like(endpoint_seed, targets):
        return dedupe_keep_order([endpoint_seed] + variants)
    return dedupe_keep_order(variants)


def fetch_json_url(url, cookie_header):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    req = urllib.request.Request(with_cache_buster(url), headers=headers)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def fetch_first_ok_json(url_candidates, cookie_header):
    last_error = "no candidate url"
    for raw in url_candidates:
        if not raw:
            continue
        try:
            return fetch_json_url(raw, cookie_header)
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
        except Exception as e:
            last_error = str(e)
    raise RuntimeError(last_error)


def extract_map_name(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return "UNKNOWN MAP"
    if isinstance(result.get("map"), dict) and result["map"].get("pretty_name"):
        return str(result["map"]["pretty_name"]).upper()
    if isinstance(result.get("current_map"), dict) and result["current_map"].get("pretty_name"):
        return str(result["current_map"]["pretty_name"]).upper()
    if result.get("pretty_name"):
        return str(result["pretty_name"]).upper()
    return "UNKNOWN MAP"


def extract_teams(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return {}, {}
    teams = result.get("teams", result)
    if not isinstance(teams, dict):
        return {}, {}
    allied = teams.get("allies") or teams.get("allied") or teams.get("us") or {}
    axis = teams.get("axis") or teams.get("germany") or teams.get("ger") or {}
    if not isinstance(allied, dict):
        allied = {}
    if not isinstance(axis, dict):
        axis = {}
    return allied, axis


def flatten_players(allied_data, axis_data):
    out = []

    def push_team(team_data, team_name):
        squads = team_data.get("squads", team_data)
        if isinstance(squads, dict):
            for squad_name, squad in squads.items():
                if not isinstance(squad, dict):
                    continue
                players = squad.get("players", [])
                if not isinstance(players, list):
                    continue
                for p in players:
                    if not isinstance(p, dict):
                        continue
                    out.append(
                        {
                            "name": p.get("name") or p.get("player") or "Unknown",
                            "player_id": p.get("player_id"),
                            "role": p.get("role") or "",
                            "kills": p.get("kills") or 0,
                            "deaths": p.get("deaths") or 0,
                            "squad": squad_name,
                            "team": team_name,
                            "world_position": p.get("world_position"),
                        }
                    )

        commander = team_data.get("commander")
        if isinstance(commander, dict) and isinstance(commander.get("player"), dict):
            p = commander["player"]
            out.append(
                {
                    "name": p.get("name") or p.get("player") or "Commander",
                    "player_id": p.get("player_id"),
                    "role": p.get("role") or "armycommander",
                    "kills": p.get("kills") or 0,
                    "deaths": p.get("deaths") or 0,
                    "squad": "COMMAND",
                    "team": team_name,
                    "world_position": p.get("world_position"),
                }
            )

    push_team(allied_data, "allies")
    push_team(axis_data, "axis")
    return out


def build_frame(cfg):
    cookie = (cfg.get("cookie") or "").strip()
    seeds = dedupe_keep_order(
        [cfg.get("team_view_url"), cfg.get("gamestate_url"), cfg.get("live_stats_url")]
    )
    if not seeds:
        raise RuntimeError("NO_ENDPOINT_CONFIGURED")

    team_targets = ["get_team_view", "get_teamview", "team_view"]
    tv_candidates = []
    for seed in seeds:
        tv_candidates.extend(build_variant_candidates(seed, team_targets))
    tv_candidates = dedupe_keep_order(tv_candidates)
    tv_data = fetch_first_ok_json(tv_candidates, cookie)

    allied_data, axis_data = extract_teams(tv_data)
    players = flatten_players(allied_data, axis_data)

    game_targets = ["get_gamestate", "get_game_state", "gamestate"]
    gs_candidates = []
    for seed in seeds:
        gs_candidates.extend(build_variant_candidates(seed, game_targets))
    gs_candidates = dedupe_keep_order(gs_candidates)

    map_name = "UNKNOWN MAP"
    try:
        gs_data = fetch_first_ok_json(gs_candidates, cookie)
        map_name = extract_map_name(gs_data)
    except Exception:
        pass

    return {
        "ts_unix": time.time(),
        "ts_iso": now_iso(),
        "map_name": map_name,
        "allied": allied_data,
        "axis": axis_data,
        "players": players,
    }


def sanitize_match_id(raw):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", raw or "")


def current_recording_path():
    with STATE_LOCK:
        rid = STATE["recording_id"]
    if not rid:
        return None
    return os.path.join(MATCH_DIR, f"{rid}.jsonl")


def append_frame_if_recording(frame):
    path = current_recording_path()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(frame) + "\n")


def list_replays():
    ensure_dirs()
    entries = []
    for name in os.listdir(MATCH_DIR):
        if not name.endswith(".jsonl"):
            continue
        full = os.path.join(MATCH_DIR, name)
        rid = name[:-6]
        frame_count = 0
        try:
            with open(full, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        frame_count += 1
        except Exception:
            continue
        entries.append(
            {
                "id": rid,
                "frames": frame_count,
                "modified_unix": os.path.getmtime(full),
            }
        )
    entries.sort(key=lambda x: x["modified_unix"], reverse=True)
    return entries


def load_replay(match_id):
    rid = sanitize_match_id(match_id)
    if not rid:
        raise RuntimeError("INVALID_MATCH_ID")
    full = os.path.join(MATCH_DIR, f"{rid}.jsonl")
    if not os.path.exists(full):
        raise RuntimeError("REPLAY_NOT_FOUND")
    frames = []
    with open(full, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except Exception:
                continue
    return frames


class PlayerMapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/config":
            self.send_json({"ok": True, "config": read_config()})
            return

        if path == "/api/live":
            try:
                cfg = read_config()
                frame = build_frame(cfg)
                append_frame_if_recording(frame)
                self.send_json({"ok": True, "frame": frame})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 502)
            return

        if path == "/api/replays":
            self.send_json({"ok": True, "replays": list_replays()})
            return

        if path == "/api/replay":
            match_id = (query.get("id") or [""])[0]
            try:
                frames = load_replay(match_id)
                self.send_json({"ok": True, "id": match_id, "frames": frames})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 404)
            return

        if path == "/api/record/status":
            with STATE_LOCK:
                rid = STATE["recording_id"]
            self.send_json({"ok": True, "recording": bool(rid), "id": rid})
            return

        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = b""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""
        except Exception:
            body = b""
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        if path == "/api/config":
            allowed = {"live_stats_url", "team_view_url", "gamestate_url", "cookie", "poll_interval_ms"}
            update = {k: v for k, v in data.items() if k in allowed}
            cfg = write_config(update)
            self.send_json({"ok": True, "config": cfg})
            return

        if path == "/api/record/start":
            label = sanitize_match_id((data.get("label") or "").strip()) if isinstance(data.get("label"), str) else ""
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            rid = f"{stamp}-{label}" if label else stamp
            with STATE_LOCK:
                STATE["recording_id"] = rid
            replay_path = os.path.join(MATCH_DIR, f"{rid}.jsonl")
            with open(replay_path, "w", encoding="utf-8"):
                pass
            self.send_json({"ok": True, "id": rid})
            return

        if path == "/api/record/stop":
            with STATE_LOCK:
                rid = STATE["recording_id"]
                STATE["recording_id"] = None
            self.send_json({"ok": True, "id": rid})
            return

        self.send_json({"ok": False, "error": "NOT_FOUND"}, 404)


if __name__ == "__main__":
    ensure_dirs()
    if not os.path.exists(CONFIG_FILE):
        write_config(dict(DEFAULT_CONFIG))

    server = ThreadingHTTPServer(("", PORT), PlayerMapHandler)
    print("=" * 70)
    print("  HLL PLAYER MAP APP — RUNNING")
    print("=" * 70)
    print(f"  URL: http://localhost:{PORT}")
    print("  This app is standalone from stream overlays.")
    print("=" * 70)
    server.serve_forever()
