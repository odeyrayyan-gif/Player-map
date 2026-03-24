#!/usr/bin/env python3
"""
Download canonical HLL map images into ./maps for this app.

Sources:
- no-grid:     https://github.com/mattwright324/maps-let-loose (assets/no-grid)
- accessible:  https://github.com/mattwright324/maps-let-loose (assets/accessibility)
"""

from __future__ import annotations

import argparse
import os
import time
import urllib.request


APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAPS_DIR = os.path.join(APP_DIR, "maps")
BASE_ROOT = "https://raw.githubusercontent.com/mattwright324/maps-let-loose/main/assets"

SOURCES = {
    # canonical local filename -> upstream filename
    "no-grid": {
        "base": "no-grid",
        "files": {
            "carentan.webp": "Carentan_NoGrid.webp",
            "driel.webp": "Driel_NoGrid.webp",
            "el_alamein.webp": "ElAlamein_NoGrid.webp",
            "elsenborn_ridge.webp": "Elsenborn_NoGrid.webp",
            "foy.webp": "Foy_NoGrid.webp",
            "hill400.webp": "Hill400_NoGrid.webp",
            "hurtgen.webp": "HurtgenV2_NoGrid.webp",
            "kharkov.webp": "Kharkov_NoGrid.webp",
            "kursk.webp": "Kursk_NoGrid.webp",
            "mortain.webp": "Mortain_NoGrid.webp",
            "omaha.webp": "Omaha_NoGrid.webp",
            "phl.webp": "PHL_NoGrid.webp",
            "remagen.webp": "Remagen_NoGrid.webp",
            "smdm.webp": "SMDMV2_NoGrid.webp",
            "sme.webp": "SME_NoGrid.webp",
            "smolensk.webp": "Smolensk_NoGrid.webp",
            "stalingrad.webp": "Stalingrad_NoGrid.webp",
            "tobruk.webp": "Tobruk_NoGrid.webp",
            "utah.webp": "Utah_NoGrid.webp",
        },
    },
    "accessible": {
        "base": "accessibility",
        "files": {
            "carentan.png": "Carentan_Accessible.png",
            "driel.png": "Driel_Accessible.png",
            "el_alamein.png": "ElAlamein_Accessible.png",
            "elsenborn_ridge.png": "Elsenborn_Accessible.png",
            "foy.png": "Foy_Accessible.png",
            "hill400.png": "Hill400_Accessible.png",
            "hurtgen.png": "HurtgenV2_Accessible.png",
            "kharkov.png": "Kharkov_Accessible.png",
            "kursk.png": "Kursk_Accessible.png",
            "mortain.png": "Mortain_Accessible.png",
            "omaha.png": "Omaha_Accessible.png",
            "phl.png": "PHL_Accessible.png",
            "remagen.png": "Remagen_Accessible.png",
            "smdm.png": "SMDMV2_Accessible.png",
            "sme.png": "SME_Accessible.png",
            "smolensk.png": "Smolensk_Accessible.png",
            "stalingrad.png": "Stalingrad_Accessible.png",
            "tobruk.png": "Tobruk_Accessible.png",
            "utah.png": "Utah_Accessible.png",
        },
    },
}


def download(url: str, dest: str, retries: int = 3) -> None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Player-map bootstrap)",
        "Accept": "*/*",
    }
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Failed download: {url} ({last_exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download HLL map images into ./maps")
    parser.add_argument(
        "--variant",
        choices=sorted(SOURCES.keys()),
        default="no-grid",
        help="asset set to download (default: no-grid)",
    )
    parser.add_argument(
        "--with-points",
        action="store_true",
        help="shortcut for --variant accessible",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--dry-run", action="store_true", help="print actions only")
    args = parser.parse_args()

    variant = "accessible" if args.with_points else args.variant
    source = SOURCES[variant]
    base_url = f"{BASE_ROOT}/{source['base']}"
    map_files = source["files"]

    os.makedirs(MAPS_DIR, exist_ok=True)
    ok = 0
    skipped = 0
    failed = 0

    for local_name, upstream_name in map_files.items():
        src = f"{base_url}/{upstream_name}"
        dst = os.path.join(MAPS_DIR, local_name)
        if os.path.exists(dst) and not args.force:
            skipped += 1
            print(f"[skip] {local_name} (exists)")
            continue
        if args.dry_run:
            print(f"[plan] {src} -> maps/{local_name}")
            continue
        try:
            download(src, dst)
            ok += 1
            print(f"[ok]   maps/{local_name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[fail] maps/{local_name}: {exc}")

    if args.dry_run:
        print(f"\nPlanned {len(map_files)} file(s) from variant='{variant}'.")
        return 0

    print(f"\nDone. downloaded={ok} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
