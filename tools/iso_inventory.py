#!/usr/bin/env python3
"""Inventory every ISO 9660 file, including byte length and extent LBA."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

import pycdlib  # noqa: E402


def text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def inventory(source: Path) -> dict:
    iso = pycdlib.PyCdlib()
    iso.open(str(source))
    try:
        files = []
        for dirname, _dirlist, filelist in iso.walk(iso_path="/"):
            directory = text(dirname)
            for name in filelist:
                path = (directory.rstrip("/") + "/" + name).replace("//", "/")
                record = iso.get_record(iso_path=path)
                files.append(
                    {
                        "path": path,
                        "size": record.data_length,
                        "lba": record.extent_location(),
                    }
                )
        files.sort(key=lambda item: item["path"])
        return {
            "image": str(source),
            "volume_id": text(iso.pvd.volume_identifier).strip(),
            "volume_space_size": source.stat().st_size // 2048,
            "file_count": len(files),
            "total_file_bytes": sum(item["size"] for item in files),
            "files": files,
        }
    finally:
        iso.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = []
    for source in args.images:
        result = inventory(source)
        target = args.output / f"{source.stem}.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({key: value for key, value in result.items() if key != "files"})
        print(
            f"{source.name}: volume={result['volume_id']!r}, "
            f"files={result['file_count']}, data={result['total_file_bytes']} bytes"
        )
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
