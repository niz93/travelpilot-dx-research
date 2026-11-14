#!/usr/bin/env python3
"""Extract only MAP00001.MAP from an ISO 9660 image and record its SHA-256."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

import pycdlib


def safe_name(iso_path: str) -> str:
    name = re.sub(r";\d+$", "", PurePosixPath(iso_path).name)
    if not name or name in (".", ".."):
        raise ValueError(f"Unsafe ISO filename: {iso_path}")
    return name


def extract_map(source: Path, destination: Path) -> dict:
    iso = pycdlib.PyCdlib()
    iso.open(str(source))
    matches: list[str] = []
    try:
        for dirname, _dirlist, filelist in iso.walk(iso_path="/"):
            for name in filelist:
                if safe_name(name).upper() == "MAP00001.MAP":
                    matches.append(str(dirname).rstrip("/") + "/" + name)
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one MAP00001.MAP, found {len(matches)}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with iso.open_file_from_iso(iso_path=matches[0]) as src, destination.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    finally:
        iso.close()

    result = {
        "source_iso": str(source),
        "iso_path": matches[0],
        "output": str(destination),
        "size": size,
        "sha256": digest.hexdigest(),
    }
    destination.with_suffix(destination.suffix + ".json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="source ISO 9660 image")
    parser.add_argument("destination", type=Path, help="destination MAP00001.MAP")
    args = parser.parse_args()
    result = extract_map(args.source, args.destination)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
