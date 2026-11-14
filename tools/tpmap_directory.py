#!/usr/bin/env python3
"""Dump the four code-derived TPMAP2 level directories.

This replaces the former sequential pair scanner, which crossed directory
boundaries. Directory sizes come from each level descriptor's uint32 count;
entries are little-endian uint32 data-offset/data-length pairs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

from tpmap_geometry import TPMap


def scan(path: Path, include_entries: bool = False) -> dict:
    tpmap = TPMap(path)
    levels = []
    for level, descriptor in enumerate(tpmap.descriptors):
        raw = tpmap.directory_bytes(level)
        item = {
            "level": level,
            "entry_count": descriptor["count"],
            "directory_offset": descriptor["directory"],
            "directory_end": descriptor["directory"] + descriptor["count"] * 8,
            "grid_divisions_x": descriptor["configuration"][1],
            "grid_divisions_y": descriptor["configuration"][2],
            "coordinate_shift": descriptor["configuration"][3],
        }
        if include_entries:
            item["entries"] = [
                {"index": index, "data_offset": offset, "data_length": length}
                for index, (offset, length) in enumerate(struct.iter_unpack("<II", raw))
            ]
        else:
            item["first_entry"] = tpmap.entry(level, 0)
            item["last_entry"] = tpmap.entry(level, descriptor["count"] - 1)
        levels.append(item)
    return {
        "file": str(path),
        "file_size": tpmap.file_size,
        "signature_offset": tpmap.signature_offset,
        "descriptor_offset": tpmap.descriptor_offset,
        "levels": levels,
        "entries_included": include_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--entries", action="store_true", help="include every entry; may create a large JSON file")
    args = parser.parse_args()
    result = scan(args.file, args.entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"signature=0x{result['signature_offset']:x}, descriptors=0x{result['descriptor_offset']:x}")
    for level in result["levels"]:
        print(f"  L{level['level']}: directory=0x{level['directory_offset']:x}.."
              f"0x{level['directory_end']:x}, entries={level['entry_count']}")


if __name__ == "__main__":
    main()
