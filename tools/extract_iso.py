#!/usr/bin/env python3
"""Extract an ISO 9660 image without mounting it and hash extracted files."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
import pycdlib  # noqa: E402


def safe_relative(iso_path: str) -> Path:
    clean = re.sub(r";\d+$", "", iso_path)
    parts = [part for part in PurePosixPath(clean).parts if part not in ("/", "")]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe ISO path: {iso_path}")
    return Path(*parts)


def extract(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    iso = pycdlib.PyCdlib()
    iso.open(str(source))
    manifest = []
    try:
        for dirname, _dirlist, filelist in iso.walk(iso_path="/"):
            for name in filelist:
                iso_path = str(dirname).rstrip("/") + "/" + name
                relative = safe_relative(iso_path)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with iso.open_file_from_iso(iso_path=iso_path) as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                manifest.append(
                    {
                        "iso_path": iso_path,
                        "file": str(relative).replace("\\", "/"),
                        "size": size,
                        "sha256": digest.hexdigest(),
                    }
                )
        (destination / "_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Extracted {len(manifest)} files to {destination}")
    finally:
        iso.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    extract(args.source, args.destination)


if __name__ == "__main__":
    main()
