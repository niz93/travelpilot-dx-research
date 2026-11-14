#!/usr/bin/env python3
"""Extract TPMAP2 metadata and the code-derived level catalogue layout.

The four level descriptors and directory entries are decoded according to the
NEC V810 reader. Coordinates remain signed TPMAP2 map units, not WGS84. Use
tpmap_geometry.py to decode and render table-A/B/C geometry.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from tpmap_geometry import TPMap


def cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError(f"Text offset outside file: {offset:#x}")
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError(f"Unterminated text at {offset:#x}")
    return data[offset:end].decode("latin-1")


def parse(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as stream:
        prefix = stream.read(0x50000)
    if len(prefix) < 0x34:
        raise ValueError("File is too short for a TPMAP2 header")
    tpmap = TPMap(path)
    declared_size = struct.unpack_from("<I", prefix, 4)[0]
    offset_table = struct.unpack_from("<H", prefix, 0x24)[0]
    offsets = struct.unpack_from("<7H", prefix, offset_table)
    copyright_offset, created_offset, format_offset, signature_offset, size_offset, flags_offset, project_offset = offsets
    if size_offset != 4:
        raise ValueError(f"Unexpected size-field address: {size_offset:#x}")
    descriptor_raw = struct.unpack_from("<I", prefix, 0x18)[0]
    if (descriptor_raw & 0xFFFF) != tpmap.descriptor_offset:
        raise ValueError("Descriptor pointer low16 differs from the signature-relative address")

    descriptors = []
    for level, descriptor in enumerate(tpmap.descriptors):
        configuration = descriptor["configuration"]
        descriptors.append({
            "level": level,
            "descriptor_offset": tpmap.descriptor_offset + level * 16,
            "configuration_bytes_0_7": list(configuration),
            "grid_divisions_x": configuration[1],
            "grid_divisions_y": configuration[2],
            "coordinate_shift": configuration[3],
            "entry_count": descriptor["count"],
            "directory_offset": descriptor["directory"],
            "directory_end": descriptor["directory"] + descriptor["count"] * 8,
        })

    first_offset, first_length = tpmap.entry(0, 0)
    first_block, _ = tpmap.read_block(0, 0)
    return {
        "file": str(path),
        "actual_size": size,
        "declared_size": declared_size,
        "size_matches": declared_size == size,
        "offset_table": offset_table,
        "indexed_offsets": {
            "copyright": copyright_offset,
            "created": created_offset,
            "format": format_offset,
            "signature": signature_offset,
            "declared_size": size_offset,
            "global_bounds": flags_offset,
            "project": project_offset,
        },
        "signature": "TPMAP2",
        "descriptor_pointer_raw": descriptor_raw,
        "descriptor_offset_low16": tpmap.descriptor_offset,
        "copyright": cstring(prefix, copyright_offset),
        "created": cstring(prefix, created_offset),
        "format": cstring(prefix, format_offset),
        "project_and_build_text": cstring(prefix, project_offset),
        "global_bounds_raw": {
            "min_x": tpmap.bounds[0], "min_y": tpmap.bounds[1],
            "max_x": tpmap.bounds[2], "max_y": tpmap.bounds[3],
        },
        "coordinate_system": "TPMAP2 signed integer map units; WGS84 transform not established",
        "catalogue_model": (
            "four 16-byte level descriptors; uint32 entry count at +8 and directory offset at +12; "
            "each directory entry is uint32 data offset plus uint32 data length"
        ),
        "descriptors": descriptors,
        "level0_first_entry": {
            "data_offset": first_offset,
            "data_length": first_length,
            "block_length_prefix": struct.unpack_from("<I", first_block)[0],
            "length_prefix_matches": struct.unpack_from("<I", first_block)[0] == first_length,
        },
        "limitations": [
            "Descriptor bytes 4..7 and all feature-type semantics are not fully classified.",
            "Raw TPMAP2 coordinates are not automatically longitude/latitude and are not exported as WGS84.",
            "MAP rendering geometry does not by itself recover the TPNAV2 routing graph or search indices.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    results = [parse(path) for path in args.files]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(f"{result['file']}: {result['actual_size']} bytes, signature at "
              f"0x{result['indexed_offsets']['signature']:x}, size match={result['size_matches']}")
        print(f"  {result['format']}")
        print(f"  {result['project_and_build_text'].splitlines()[0]}")
        for descriptor in result["descriptors"]:
            print(f"  L{descriptor['level']}: {descriptor['entry_count']} entries, "
                  f"grid={descriptor['grid_divisions_x']}x{descriptor['grid_divisions_y']}, "
                  f"shift={descriptor['coordinate_shift']}")


if __name__ == "__main__":
    main()
