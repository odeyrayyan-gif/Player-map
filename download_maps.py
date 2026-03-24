#!/usr/bin/env python3
"""
Download canonical HLL map images into ./maps for this app.

Source:
https://github.com/mattwright324/maps-let-loose (assets/no-grid)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time
import urllib.request


APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAPS_DIR = os.path.join(APP_DIR, "maps")
SOURCE_BASE_URLS = [
    "https://raw.githubusercontent.com/mattwright324/maps-let-loose/main/assets/no-grid",
    "https://cdn.jsdelivr.net/gh/mattwright324/maps-let-loose@main/assets/no-grid",
]

# canonical local filename -> upstream no-grid filename
MAP_FILES = {
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
}

# Known-good checksums for official no-grid maps.
MAP_SHA256 = {
    "carentan.webp": "097f69792150666fef00261a88ded5bc8c95bcaefc6bb8368b29223f582b4cb5",
    "driel.webp": "bacb88cb6a761ff66ff358e7101b154f06a6d3b030920e89cba9e6986c923734",
    "el_alamein.webp": "c123334de3e8850cde273c05f940b556e5c987de0b5fe07ed5d1922a787211c1",
    "elsenborn_ridge.webp": "7b91d20cc6eee5fbb68653ed713ee8041de2c980431d979ce3f2e353c352ebfe",
    "foy.webp": "d3b9df44be942f020babfe39a3fb399fc80bc67b3efc963423b090cd97cc6fe4",
    "hill400.webp": "cc302385b94b29b3c106550708b3df6a3233b3d6c82a40821887b05c8904fdd9",
    "hurtgen.webp": "ec11566b803dceb7372886823bed9e57f9e6062abd5ff9a961953970212ad92b",
    "kharkov.webp": "77560e5de03447655825b89b4e9e706d14b79a2b890ea6f96442384719c2c8f8",
    "kursk.webp": "ea042b1bee1b1f2226ee37331e70b031fddb1da5868c0e93131f64f9c07b735d",
    "mortain.webp": "91e85cc1768d5567280d8a7e62768c12e99f003bda3a95e195db2d90ba5c80a3",
    "omaha.webp": "11095df2fe28ffd94975a961dff7bb5da63af35e8b4ec36a4a0eae78ed1ad784",
    "phl.webp": "6bdf758263ae64f9ffa90fcd5a2414f8d7926a24b39c5f9a9d72e2b0f4b09253",
    "remagen.webp": "8a81156f2f2599119716fab75025f5889ab01cb1f12c3db64fb9779a75ce27d1",
    "smdm.webp": "84a29fd73bf546f857ee58c582ea1fc5611708a9ee7b566bc18c22c6c4aaaecd",
    "sme.webp": "4ca97195677f81dbdad821fd73c6e7f6f60e670e4e78ab273612100be99d6a56",
    "smolensk.webp": "7ddef9c0479668140def9d4162dacdefac3f6b9636b1729b1f61b6a80f0bae2b",
    "stalingrad.webp": "9ccd06488174533d5da61c14572853b6681437350ffff64ec2965bb700a1895e",
    "tobruk.webp": "bcbd4e93fb501b8c7862f16db55c59bda51bfdc48e40c00a37a3e276b8cd7375",
    "utah.webp": "d34e6ae80d8c125ed7399fd16fa85311220acf0376304864e30addf1ce34100c",
}

MIN_VALID_BYTES = 1_000_000


def looks_like_webp(data: bytes) -> bool:
    return (
        len(data) >= 12
        and data[0:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )


def checksum_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_map_bytes(local_name: str, data: bytes, verify_checksum: bool = True) -> str:
    if len(data) < MIN_VALID_BYTES:
        raise RuntimeError(f"download too small ({len(data)} bytes)")
    if not looks_like_webp(data):
        raise RuntimeError("payload is not a WEBP image")
    digest = checksum_hex(data)
    if verify_checksum:
        expected = MAP_SHA256.get(local_name)
        if expected and digest != expected:
            raise RuntimeError(f"checksum mismatch (got {digest}, expected {expected})")
    return digest


def fetch_bytes(url: str, retries: int = 3) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Player-map bootstrap)",
        "Accept": "*/*",
    }
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Failed download: {url} ({last_exc})")


def file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def download_verified(local_name: str, upstream_name: str, verify_checksum: bool = True) -> tuple[bytes, str]:
    failures = []
    for base_url in SOURCE_BASE_URLS:
        src = f"{base_url}/{upstream_name}"
        try:
            data = fetch_bytes(src)
            digest = validate_map_bytes(local_name, data, verify_checksum=verify_checksum)
            return data, digest
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{src}: {exc}")
    raise RuntimeError(" ; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download HLL map images into ./maps")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--dry-run", action="store_true", help="print actions only")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip checksum verification (not recommended)",
    )
    args = parser.parse_args()

    os.makedirs(MAPS_DIR, exist_ok=True)
    ok = 0
    skipped = 0
    failed = 0
    verify_checksum = not args.no_verify

    for local_name, upstream_name in MAP_FILES.items():
        dst = os.path.join(MAPS_DIR, local_name)
        existing_valid = False
        if os.path.exists(dst):
            if args.force:
                existing_valid = False
            else:
                try:
                    digest = validate_map_bytes(local_name, file_bytes(dst), verify_checksum=verify_checksum)
                    existing_valid = True
                    skipped += 1
                    print(f"[skip] {local_name} (exists, verified {digest[:12]})")
                except Exception as exc:  # noqa: BLE001
                    print(f"[fix]  {local_name} invalid existing file: {exc}")
                    existing_valid = False
        if existing_valid:
            continue
        if args.dry_run:
            src = f"{SOURCE_BASE_URLS[0]}/{upstream_name}"
            print(f"[plan] {src} -> maps/{local_name}")
            continue
        try:
            data, digest = download_verified(local_name, upstream_name, verify_checksum=verify_checksum)
            write_bytes(dst, data)
            ok += 1
            print(f"[ok]   maps/{local_name} ({digest[:12]})")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[fail] maps/{local_name}: {exc}")

    if args.dry_run:
        print(f"\nPlanned {len(MAP_FILES)} file(s).")
        return 0

    print(f"\nDone. downloaded={ok} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
