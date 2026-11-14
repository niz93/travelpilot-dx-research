#!/usr/bin/env python3
"""Validate every TPMAP2 catalogue range and sample code-derived block bodies.

Block header: uint32 length, then three uint16 offset/count pairs for tables
A (16-byte polygonal records), B (12-byte line records), and C (12-byte point
records). Table A/B coordinate arrays and C inline coordinates are signed16
x/y pairs; absolute positions require the hierarchical tile frame.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct

from tpmap_block_probe import probe_block
from tpmap_geometry import TPMap

SAMPLES_PER_LEVEL = 32


def cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError(f"unterminated string at {offset:#x}")
    return data[offset:end].decode("latin-1")


def parse(path: Path) -> dict:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(0x50000)
    if len(header) < 0x34:
        raise ValueError("file is too short for the indexed header")
    tpmap = TPMap(path)
    offset_table = struct.unpack_from("<H", header, 0x24)[0]
    offsets = struct.unpack_from("<7H", header, offset_table)

    descriptors = []
    for level, descriptor in enumerate(tpmap.descriptors):
        directory = descriptor["directory"]
        count = descriptor["count"]
        directory_end = directory + count * 8
        if count == 0 or directory_end > file_size:
            raise ValueError(f"level {level} catalogue lies outside the file")
        if level and directory != descriptors[-1]["directory_end"]:
            raise ValueError(f"level {level} catalogue is not contiguous with its predecessor")
        descriptors.append({
            "level": level,
            "descriptor_offset": tpmap.descriptor_offset + level * 16,
            "configuration_bytes_0_7": list(descriptor["configuration"]),
            "grid_divisions_x": descriptor["configuration"][1],
            "grid_divisions_y": descriptor["configuration"][2],
            "coordinate_shift": descriptor["configuration"][3],
            "record_count": count,
            "directory_offset": directory,
            "directory_end": directory_end,
        })
    if descriptors[0]["directory_offset"] != tpmap.descriptor_offset + 64:
        raise ValueError("level 0 catalogue does not immediately follow the four descriptors")
    data_start = tpmap.entry(0, 0)[0]
    if data_start != descriptors[-1]["directory_end"]:
        raise ValueError("last catalogue end differs from level 0's first data offset")

    level_results = []
    for level, descriptor in enumerate(descriptors):
        raw = tpmap.directory_bytes(level)
        length_counts = Counter()
        invalid_ranges = []
        invalid_range_count = 0
        zero_lengths = 0
        min_offset = None
        max_end = 0
        for index, (offset, length) in enumerate(struct.iter_unpack("<II", raw)):
            length_counts[length] += 1
            if length == 0:
                zero_lengths += 1
            if offset < data_start or offset + length > file_size or offset + length < offset:
                invalid_range_count += 1
                if len(invalid_ranges) < 20:
                    invalid_ranges.append({"index": index, "offset": offset, "length": length})
            if min_offset is None or offset < min_offset:
                min_offset = offset
            if offset + length > max_end:
                max_end = offset + length
        if invalid_range_count:
            raise ValueError(f"level {level} has {invalid_range_count} out-of-file catalogue entries")

        selected = tpmap.selected_indices(level, SAMPLES_PER_LEVEL)
        samples = []
        for index in sorted(selected):
            data, offset = tpmap.read_block(level, index)
            layout = probe_block(data, len(data), include_records=False)
            first_uint32 = struct.unpack_from("<I", data)[0] if len(data) >= 4 else None
            samples.append({
                "index": index,
                "selection_groups": selected[index],
                "offset": offset,
                "length": len(data),
                "actual_bytes_read": len(data),
                "first_uint32": first_uint32,
                "length_prefix_matches": first_uint32 == len(data),
                "block_layout": layout,
            })
        accepted = sum(item["block_layout"]["accepted"] for item in samples)
        prefix_matches = sum(item["length_prefix_matches"] for item in samples)
        level_results.append({
            **descriptor,
            "minimum_data_offset": min_offset,
            "maximum_data_end": max_end,
            "zero_length_entries": zero_lengths,
            "invalid_range_count": invalid_range_count,
            "invalid_range_examples": invalid_ranges,
            "unique_lengths": len(length_counts),
            "most_common_lengths": [
                {"length": length, "entries": count}
                for length, count in length_counts.most_common(24)
            ],
            "sample_count": len(samples),
            "sampled_length_prefix_matches": prefix_matches,
            "sampled_block_layouts_accepted": accepted,
            "samples": samples,
        })

    return {
        "file": str(path),
        "file_size": file_size,
        "declared_size": struct.unpack_from("<I", header, 4)[0],
        "format_text": cstring(header, offsets[2]),
        "project_text_first_line": cstring(header, offsets[6]).splitlines()[0],
        "signature_offset": tpmap.signature_offset,
        "descriptor_offset": tpmap.descriptor_offset,
        "global_bounds_raw": tpmap.bounds,
        "first_data_offset": data_start,
        "catalogue_model": (
            "four descriptors: uint32 count at +8, uint32 directory offset at +12; "
            "directory entries are uint32 data offset and uint32 data length"
        ),
        "block_model": (
            "uint32 length; uint16 A offset/count; uint16 B offset/count; uint16 C offset/count; "
            "offsets are block-relative and strides are 16/12/12 bytes"
        ),
        "catalogue_boundaries_valid": True,
        "levels": level_results,
        "limitations": [
            "Descriptor flag bytes 4..7 and feature-type codes are not fully classified.",
            "Accepted samples validate code-derived tables and referenced byte ranges, not every feature's semantic meaning.",
            "Coordinates are TPMAP2 signed integer map units, not WGS84.",
            "Sampling combines deterministic uniform and nonempty-block groups; it is not an exhaustive block-body parse.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    results = []
    for path in args.files:
        result = parse(path)
        results.append(result)
        print(f"{path}: catalogues valid, data start={result['first_data_offset']:#x}")
        for level in result["levels"]:
            print(f"  L{level['level']}: {level['record_count']} entries, "
                  f"length prefixes {level['sampled_length_prefix_matches']}/{level['sample_count']}, "
                  f"block layouts {level['sampled_block_layouts_accepted']}/{level['sample_count']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
