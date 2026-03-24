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
    "map_bounds": {},
    "projection": {
        "flip_x": False,
        "flip_y": False,
        "swap_xy": False,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
    },
    "map_view": {
        "flip_x": False,
        "flip_y": False,
    },
    "player_view": {
        "mirror_x": False,
        "mirror_y": False,
    },
    "player_colors": {
        "allies": "#58a6ff",
        "axis": "#ff5f5f",
    },
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
        raw_parts = [p for p in parsed.path.split("/") if p]
        parts = list(raw_parts)
        target = str(target_name or "").lstrip("/").lower()
        idx = next((i for i, p in enumerate(parts) if p.lower() == "get_live_game_stats"), -1)
        if idx >= 0:
            parts[idx] = target
        elif len(parts) >= 1:
            parts[-1] = target
        else:
            return ""
        new_path = "/" + "/".join(parts)
        return urllib.parse.urlunparse(parsed._replace(path=new_path))
    except Exception:
        return ""


def add_trailing_slash_variant(url):
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or "/"
        alt_path = path[:-1] if path.endswith("/") else f"{path}/"
        if alt_path == path:
            return ""
        return urllib.parse.urlunparse(parsed._replace(path=alt_path))
    except Exception:
        return ""


def build_variant_candidates(endpoint_seed, targets):
    variants = [build_api_variant_url(endpoint_seed, t) for t in targets]
    base = [endpoint_seed] + variants if endpoint_seed else variants
    expanded = []
    for candidate in base:
        if not candidate:
            continue
        expanded.append(candidate)
        expanded.append(add_trailing_slash_variant(candidate))
    return dedupe_keep_order(expanded)


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
    failures = []
    for raw in url_candidates:
        if not raw:
            continue
        try:
            return fetch_json_url(raw, cookie_header)
        except urllib.error.HTTPError as e:
            failures.append(f"HTTP {e.code} ({raw})")
        except urllib.error.URLError as e:
            failures.append(f"{e.reason} ({raw})")
        except Exception as e:
            failures.append(f"{str(e)} ({raw})")
    if not failures:
        raise RuntimeError("no candidate url")
    raise RuntimeError("; ".join(failures[:8]))


def normalize_map_key(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def extract_map_meta(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return {"map_name": "UNKNOWN MAP", "map_shortname": "", "map_image_name": ""}

    sources = []
    if isinstance(result.get("map"), dict):
        sources.append(result["map"])
    if isinstance(result.get("current_map"), dict):
        sources.append(result["current_map"])
    sources.append(result)

    pretty_name = ""
    shortname = ""
    image_name = ""

    for src in sources:
        if not isinstance(src, dict):
            continue
        if not pretty_name and src.get("pretty_name"):
            pretty_name = str(src.get("pretty_name")).strip()
        if not shortname and src.get("shortname"):
            shortname = normalize_map_key(src.get("shortname"))
        if not image_name and src.get("image_name"):
            image_name = normalize_map_key(src.get("image_name"))

    if not shortname and image_name:
        shortname = image_name

    map_name = pretty_name.upper() if pretty_name else "UNKNOWN MAP"
    return {
        "map_name": map_name,
        "map_shortname": shortname,
        "map_image_name": image_name,
    }


def extract_score_time_meta(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return {"allies_score": None, "axis_score": None, "time_remaining_sec": None}

    sources = []
    if isinstance(result.get("map"), dict):
        sources.append(result["map"])
    if isinstance(result.get("current_map"), dict):
        sources.append(result["current_map"])
    if isinstance(result.get("score"), dict):
        sources.append(result["score"])
    if isinstance(result.get("scores"), dict):
        sources.append(result["scores"])
    sources.append(result)

    def get_num(keys):
        for src in sources:
            if not isinstance(src, dict):
                continue
            for key in keys:
                if key in src:
                    value = to_float_or_none(src.get(key))
                    if value is not None:
                        return int(value)
        return None

    allies_score = get_num(("allies_score", "allied_score", "allies", "us_score", "friendly_score"))
    axis_score = get_num(("axis_score", "enemy_score", "axis", "ger_score"))
    time_remaining_sec = get_num(
        (
            "time_remaining",
            "time_remaining_sec",
            "remaining_time",
            "remaining_seconds",
            "seconds_remaining",
            "time_left",
            "match_time_remaining",
        )
    )
    return {
        "allies_score": allies_score,
        "axis_score": axis_score,
        "time_remaining_sec": time_remaining_sec,
    }


def to_float_or_none(value):
    try:
        out = float(value)
        if out != out:  # NaN
            return None
        return out
    except Exception:
        return None


def normalize_bounds(raw):
    if not isinstance(raw, dict):
        return None

    aliases = {
        "x_min": ["x_min", "xmin", "min_x", "left"],
        "x_max": ["x_max", "xmax", "max_x", "right"],
        "y_min": ["y_min", "ymin", "min_y", "bottom"],
        "y_max": ["y_max", "ymax", "max_y", "top"],
    }
    out = {}
    for canon, keys in aliases.items():
        value = None
        for key in keys:
            if key in raw:
                value = to_float_or_none(raw.get(key))
                if value is not None:
                    break
        out[canon] = value

    x_min = out["x_min"]
    x_max = out["x_max"]
    y_min = out["y_min"]
    y_max = out["y_max"]

    if None in (x_min, x_max, y_min, y_max):
        return None
    if x_max <= x_min or y_max <= y_min:
        return None

    return {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max}


def normalize_projection(raw):
    base = {
        "flip_x": False,
        "flip_y": False,
        "swap_xy": False,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    if not isinstance(raw, dict):
        return dict(base)

    out = dict(base)
    out["flip_x"] = bool(raw.get("flip_x", base["flip_x"]))
    out["flip_y"] = bool(raw.get("flip_y", base["flip_y"]))
    out["swap_xy"] = bool(raw.get("swap_xy", base["swap_xy"]))
    out["scale_x"] = to_float_or_none(raw.get("scale_x"))
    out["scale_y"] = to_float_or_none(raw.get("scale_y"))
    out["offset_x"] = to_float_or_none(raw.get("offset_x"))
    out["offset_y"] = to_float_or_none(raw.get("offset_y"))

    if out["scale_x"] is None or abs(out["scale_x"]) < 1e-9:
        out["scale_x"] = base["scale_x"]
    if out["scale_y"] is None or abs(out["scale_y"]) < 1e-9:
        out["scale_y"] = base["scale_y"]
    if out["offset_x"] is None:
        out["offset_x"] = base["offset_x"]
    if out["offset_y"] is None:
        out["offset_y"] = base["offset_y"]
    return out


def normalize_map_view(raw):
    base = {"flip_x": False, "flip_y": False}
    if not isinstance(raw, dict):
        return dict(base)
    return {
        "flip_x": bool(raw.get("flip_x", base["flip_x"])),
        "flip_y": bool(raw.get("flip_y", base["flip_y"])),
    }


def normalize_player_view(raw):
    base = {"mirror_x": False, "mirror_y": False}
    if not isinstance(raw, dict):
        return dict(base)
    return {
        "mirror_x": bool(raw.get("mirror_x", base["mirror_x"])),
        "mirror_y": bool(raw.get("mirror_y", base["mirror_y"])),
    }


def normalize_player_colors(raw):
    base = {"allies": "#58a6ff", "axis": "#ff5f5f"}
    if not isinstance(raw, dict):
        return dict(base)

    def clean_hex(value, fallback):
        text = str(value or "").strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}", text):
            return text
        return fallback

    return {
        "allies": clean_hex(raw.get("allies"), base["allies"]),
        "axis": clean_hex(raw.get("axis"), base["axis"]),
    }


def extract_map_bounds(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return None

    candidates = [
        result,
        result.get("map"),
        result.get("current_map"),
    ]
    nested_keys = (
        "bounds",
        "map_bounds",
        "world_bounds",
        "playable_bounds",
        "extent",
        "extents",
    )

    for source in list(candidates):
        if isinstance(source, dict):
            for key in nested_keys:
                candidates.append(source.get(key))

    for candidate in candidates:
        bounds = normalize_bounds(candidate)
        if bounds:
            return bounds
    return None


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

    def player_identity_set(p):
        ids = set()
        for key in ("player_id", "id", "steam_id", "steamid", "name", "player"):
            value = p.get(key)
            if value is None:
                continue
            ids.add(str(value).strip().lower())
        return {v for v in ids if v}

    def match_player_ref(player_ids, ref):
        if ref is None:
            return False
        if isinstance(ref, dict):
            for key in ("player_id", "id", "steam_id", "steamid", "name", "player"):
                if match_player_ref(player_ids, ref.get(key)):
                    return True
            return False
        value = str(ref).strip().lower()
        return bool(value) and value in player_ids

    def infer_squad_leader(squad, p):
        if bool(
            p.get("is_squad_leader")
            or p.get("is_leader")
            or p.get("leader")
            or p.get("squad_leader")
        ):
            return True

        player_ids = player_identity_set(p)
        if not player_ids:
            return False

        for key in ("leader", "squad_leader", "officer", "squadlead"):
            if match_player_ref(player_ids, squad.get(key)):
                return True

        role = re.sub(r"[^a-z0-9]+", "", str(p.get("role") or "").strip().lower())
        if "officer" in role or role in {"tankcommander", "spotter", "reconspotter"}:
            return True
        return False

    def infer_tank_role(role):
        text = re.sub(r"[^a-z0-9]+", "", str(role or "").strip().lower())
        return text in {"tankcommander", "crewman"}

    def extract_vehicle_label(p):
        for key in (
            "vehicle",
            "vehicle_name",
            "vehicle_type",
            "current_vehicle",
            "active_vehicle",
        ):
            value = p.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

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
                    role = p.get("role") or ""
                    out.append(
                        {
                            "name": p.get("name") or p.get("player") or "Unknown",
                            "player_id": p.get("player_id"),
                            "role": role,
                            "kills": p.get("kills") or 0,
                            "deaths": p.get("deaths") or 0,
                            "squad": squad_name,
                            "team": team_name,
                            "world_position": p.get("world_position"),
                            "is_squad_leader": infer_squad_leader(squad, p),
                            "is_tank_role": infer_tank_role(role),
                            "vehicle": extract_vehicle_label(p),
                        }
                    )

        commander = team_data.get("commander")
        if isinstance(commander, dict) and isinstance(commander.get("player"), dict):
            p = commander["player"]
            role = p.get("role") or "armycommander"
            out.append(
                {
                    "name": p.get("name") or p.get("player") or "Commander",
                    "player_id": p.get("player_id"),
                    "role": role,
                    "kills": p.get("kills") or 0,
                    "deaths": p.get("deaths") or 0,
                    "squad": "COMMAND",
                    "team": team_name,
                    "world_position": p.get("world_position"),
                    "is_squad_leader": True,
                    "is_tank_role": infer_tank_role(role),
                    "vehicle": extract_vehicle_label(p),
                }
            )

    push_team(allied_data, "allies")
    push_team(axis_data, "axis")
    return out


def build_frame(cfg):
    cookie = (cfg.get("cookie") or "").strip()
    team_view_url = (cfg.get("team_view_url") or "").strip()
    gamestate_url = (cfg.get("gamestate_url") or "").strip()
    live_stats_url = (cfg.get("live_stats_url") or "").strip()

    seeds = dedupe_keep_order([team_view_url, gamestate_url, live_stats_url])
    if not any(seeds):
        raise RuntimeError("NO_ENDPOINT_CONFIGURED")

    team_targets = ["get_team_view", "get_teamview", "team_view"]
    if team_view_url:
        # If the user explicitly provided team_view_url, honor it exactly.
        tv_candidates = dedupe_keep_order([team_view_url, add_trailing_slash_variant(team_view_url)])
    else:
        tv_candidates = []
        for seed in seeds:
            tv_candidates.extend(build_variant_candidates(seed, team_targets))
        tv_candidates = dedupe_keep_order(tv_candidates)
    tv_data = fetch_first_ok_json(tv_candidates, cookie)

    allied_data, axis_data = extract_teams(tv_data)
    players = flatten_players(allied_data, axis_data)

    game_targets = ["get_gamestate", "get_game_state", "gamestate"]
    if gamestate_url:
        # If the user explicitly provided gamestate_url, honor it exactly.
        gs_candidates = dedupe_keep_order([gamestate_url, add_trailing_slash_variant(gamestate_url)])
    else:
        gs_candidates = []
        for seed in seeds:
            gs_candidates.extend(build_variant_candidates(seed, game_targets))
        gs_candidates = dedupe_keep_order(gs_candidates)

    tv_meta = extract_map_meta(tv_data)
    tv_score = extract_score_time_meta(tv_data)
    map_name = tv_meta["map_name"]
    map_shortname = tv_meta["map_shortname"]
    map_image_name = tv_meta["map_image_name"]
    allies_score = tv_score["allies_score"]
    axis_score = tv_score["axis_score"]
    time_remaining_sec = tv_score["time_remaining_sec"]
    map_bounds = normalize_bounds(cfg.get("map_bounds")) or None
    map_bounds_source = "config" if map_bounds else "auto"
    projection = normalize_projection(cfg.get("projection"))
    map_view = normalize_map_view(cfg.get("map_view"))
    player_view = normalize_player_view(cfg.get("player_view"))
    player_colors = normalize_player_colors(cfg.get("player_colors"))

    if not map_bounds:
        tv_bounds = extract_map_bounds(tv_data)
        if tv_bounds:
            map_bounds = tv_bounds
            map_bounds_source = "team_view"

    try:
        gs_data = fetch_first_ok_json(gs_candidates, cookie)
        gs_meta = extract_map_meta(gs_data)
        gs_score = extract_score_time_meta(gs_data)
        if gs_meta["map_name"] != "UNKNOWN MAP":
            map_name = gs_meta["map_name"]
        if gs_meta["map_shortname"]:
            map_shortname = gs_meta["map_shortname"]
        if gs_meta["map_image_name"]:
            map_image_name = gs_meta["map_image_name"]
        if gs_score["allies_score"] is not None:
            allies_score = gs_score["allies_score"]
        if gs_score["axis_score"] is not None:
            axis_score = gs_score["axis_score"]
        if gs_score["time_remaining_sec"] is not None:
            time_remaining_sec = gs_score["time_remaining_sec"]
        if not map_bounds:
            gs_bounds = extract_map_bounds(gs_data)
            if gs_bounds:
                map_bounds = gs_bounds
                map_bounds_source = "gamestate"
    except Exception:
        pass

    if not map_name:
        map_name = "UNKNOWN MAP"

    return {
        "ts_unix": time.time(),
        "ts_iso": now_iso(),
        "map_name": map_name,
        "map_shortname": map_shortname,
        "map_image_name": map_image_name,
        "allies_score": allies_score,
        "axis_score": axis_score,
        "time_remaining_sec": time_remaining_sec,
        "map_bounds": map_bounds,
        "map_bounds_source": map_bounds_source,
        "projection": projection,
        "map_view": map_view,
        "player_view": player_view,
        "player_colors": player_colors,
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
            allowed = {
                "live_stats_url",
                "team_view_url",
                "gamestate_url",
                "cookie",
                "poll_interval_ms",
                "map_bounds",
                "projection",
                "map_view",
                "player_view",
                "player_colors",
            }
            update = {k: v for k, v in data.items() if k in allowed}
            if "map_bounds" in update:
                update["map_bounds"] = normalize_bounds(update.get("map_bounds")) or {}
            if "projection" in update:
                update["projection"] = normalize_projection(update.get("projection"))
            if "map_view" in update:
                update["map_view"] = normalize_map_view(update.get("map_view"))
            if "player_view" in update:
                update["player_view"] = normalize_player_view(update.get("player_view"))
            if "player_colors" in update:
                update["player_colors"] = normalize_player_colors(update.get("player_colors"))
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
