#!/usr/bin/env python3
"""Survey TPMAP2 feature types without assigning unproven road semantics.

The sample combines uniformly distributed directory entries with non-empty ones.
Auxiliary line payloads are retained only as bounded byte evidence; marker bytes
0xf1/0xf2 follow the branch recovered at 0xffcf2652 in map_layer_handler_243e.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct

from tpmap_block_probe import probe_block
from tpmap_geometry import TPMap


def hex_counts(values: Counter[int]) -> dict[str, int]:
    return {f"0x{key:02x}": value for key, value in sorted(values.items())}


def new_line_detail() -> dict:
    return {
        "count": 0,
        "flags": Counter(),
        "unknown0": Counter(),
        "trailing": Counter(),
        "point_counts": [],
        "auxiliary_nonzero": 0,
        "auxiliary_markers": Counter(),
        "label_candidates": [],
    }


def survey_file(path: Path, levels: list[int], samples: int) -> dict:
    tpmap = TPMap(path)
    result = {
        "file": str(path),
        "method": "uniform plus non-empty deterministic directory sample; not an exhaustive census",
        "levels": [],
    }
    for level in levels:
        selected = tpmap.selected_indices(level, samples)
        area_types = Counter()
        line_types = Counter()
        point_types = Counter()
        line_details: dict[int, dict] = {}
        errors = []
        accepted = 0
        for index in sorted(selected):
            data, file_offset = tpmap.read_block(level, index)
            parsed = probe_block(data, len(data), include_records=True)
            if not parsed["accepted"]:
                if len(errors) < 20:
                    errors.append({"index": index, "reason": parsed["reason"]})
                continue
            accepted += 1
            for record in parsed["tables"]["a"]["records"]:
                area_types[record["type"]] += 1
            for record in parsed["tables"]["c_points"]["records"]:
                point_types[record["type"]] += 1
            for record in parsed["tables"]["b_lines"]["records"]:
                feature_type = record["type"]
                line_types[feature_type] += 1
                detail = line_details.setdefault(feature_type, new_line_detail())
                detail["count"] += 1
                detail["flags"][record["flags"]] += 1
                detail["unknown0"][record["unknown0"]] += 1
                detail["trailing"][record["trailing_uint16"]] += 1
                detail["point_counts"].append(record["point_count"])
                auxiliary = record["text_offset"]
                if not auxiliary or auxiliary + 2 > len(data):
                    continue
                detail["auxiliary_nonzero"] += 1
                marker = data[auxiliary + 1]
                detail["auxiliary_markers"][marker] += 1
                if marker in (0xf1, 0xf2) and len(detail["label_candidates"]) < 12:
                    size = data[auxiliary]
                    end = auxiliary + size
                    valid = size >= 2 and end <= len(data)
                    payload = data[auxiliary + 2:end] if valid else b""
                    text = payload.split(b"\0", 1)[0]
                    detail["label_candidates"].append({
                        "index": index,
                        "file_offset": file_offset,
                        "auxiliary_offset": auxiliary,
                        "size": size,
                        "size_within_block": valid,
                        "payload_hex": payload[:160].hex(),
                        "payload_latin1": payload[:160].decode("latin-1"),
                        "text_ascii": text.decode("ascii") if all(0x20 <= b <= 0x7e for b in text) else None,
                    })
        details = {}
        for feature_type, detail in sorted(line_details.items()):
            counts = detail["point_counts"]
            details[f"0x{feature_type:02x}"] = {
                "count": detail["count"],
                "flags": hex_counts(detail["flags"]),
                "unknown0": hex_counts(detail["unknown0"]),
                "trailing": hex_counts(detail["trailing"]),
                "point_count_min": min(counts) if counts else None,
                "point_count_max": max(counts) if counts else None,
                "auxiliary_nonzero": detail["auxiliary_nonzero"],
                "auxiliary_markers": hex_counts(detail["auxiliary_markers"]),
                "label_candidates": detail["label_candidates"],
            }
        result["levels"].append({
            "level": level,
            "directory_count": tpmap.descriptors[level]["count"],
            "selected_blocks": len(selected),
            "selected_indices": sorted(selected),
            "accepted_blocks": accepted,
            "area_types": hex_counts(area_types),
            "line_types": hex_counts(line_types),
            "point_types": hex_counts(point_types),
            "line_type_details": details,
            "errors": errors,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--levels", default="3", help="comma-separated levels, default: 3")
    parser.add_argument("--samples", type=int, default=256,
                        help="maximum size of each uniform and non-empty sample per level")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    levels = [int(value, 0) for value in args.levels.split(",")]
    if any(level not in range(4) for level in levels):
        parser.error("levels must be between 0 and 3")
    results = []
    for path in args.files:
        result = survey_file(path, levels, args.samples)
        results.append(result)
        print(path)
        for level in result["levels"]:
            print(
                f"  L{level['level']}: {level['accepted_blocks']}/{level['selected_blocks']} valid; "
                f"A={level['area_types']}; B={level['line_types']}; C={level['point_types']}; "
                f"errors={len(level['errors'])}"
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
