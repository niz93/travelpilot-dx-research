#!/usr/bin/env python3
"""Decode TPMAP2 rendering geometry using the recovered NEC V810 algorithms.

Coordinates produced here are signed TPMAP2 map units, not yet WGS84. The
module deliberately calls table-B objects "lines" until their feature types
are classified; their geometry alone does not prove that they are roads.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct
from typing import Iterator

from tpmap_block_probe import probe_block

CHUNK = 256 * 1024


def sample_indices(count: int, limit: int) -> set[int]:
    if count <= 0 or limit <= 0:
        return set()
    if count <= limit:
        return set(range(count))
    return {index * (count - 1) // (limit - 1) for index in range(limit)}


def snap_coordinate(value: int, minimum: int, maximum: int) -> int:
    # FUN_ram_ffcf3d38 snaps coordinates within 64 map units of a tile edge.
    if abs(value - minimum) <= 64:
        return minimum
    if abs(value - maximum) <= 64:
        return maximum
    return value


class TPMap:
    def __init__(self, path: Path):
        self.path = path
        self.file_size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(0x1000)
        if len(header) < 0x34:
            raise ValueError("file is too short for the indexed header")
        offset_table = struct.unpack_from("<H", header, 0x24)[0]
        offsets = struct.unpack_from("<7H", header, offset_table)
        signature_offset = offsets[3]
        if header[signature_offset:signature_offset + 8] != b"TPMAP2\0\0":
            raise ValueError("TPMAP2 signature is absent at its indexed address")
        self.signature_offset = signature_offset
        self.descriptor_offset = signature_offset + 8
        self.bounds = struct.unpack_from("<4i", header, 8)
        self.descriptors = []
        for level in range(4):
            position = self.descriptor_offset + level * 16
            configuration = header[position:position + 8]
            count, directory = struct.unpack_from("<II", header, position + 8)
            self.descriptors.append({
                "level": level,
                "configuration": configuration,
                "count": count,
                "directory": directory,
            })
        expected_count = 1
        for level, descriptor in enumerate(self.descriptors):
            # The count at L is the product of subdivision factors through L.
            if level:
                expected_count *= descriptor["configuration"][1] * descriptor["configuration"][2]
            if descriptor["count"] != expected_count:
                raise ValueError(
                    f"level {level} count {descriptor['count']} differs from grid product {expected_count}"
                )

    def entry(self, level: int, index: int) -> tuple[int, int]:
        descriptor = self.descriptors[level]
        if not 0 <= index < descriptor["count"]:
            raise IndexError((level, index))
        with self.path.open("rb") as stream:
            stream.seek(descriptor["directory"] + index * 8)
            raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("truncated directory entry")
        return struct.unpack("<II", raw)

    def directory_bytes(self, level: int) -> bytes:
        descriptor = self.descriptors[level]
        with self.path.open("rb") as stream:
            stream.seek(descriptor["directory"])
            raw = stream.read(descriptor["count"] * 8)
        if len(raw) != descriptor["count"] * 8:
            raise ValueError(f"truncated level {level} directory")
        return raw

    def read_block(self, level: int, index: int) -> tuple[bytes, int]:
        offset, length = self.entry(level, index)
        if offset < 0 or length < 0 or offset + length > self.file_size:
            raise ValueError(f"out-of-file block at L{level}[{index}]")
        with self.path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        if len(data) != length:
            raise ValueError(f"truncated block at L{level}[{index}]")
        return data, offset

    def grid_size(self, level: int) -> tuple[int, int]:
        """Return the cumulative global grid dimensions at a hierarchy level."""
        if not 0 <= level < len(self.descriptors):
            raise IndexError(level)
        width = height = 1
        for current in range(1, level + 1):
            configuration = self.descriptors[current]["configuration"]
            width *= configuration[1]
            height *= configuration[2]
        return width, height

    def tile_xy(self, level: int, index: int) -> tuple[int, int]:
        """Convert a hierarchical tile index to its global grid coordinate."""
        cells = self.tile_frame(level, index)["cells"]
        x = y = 0
        for current in range(1, level + 1):
            configuration = self.descriptors[current]["configuration"]
            div_x, div_y = configuration[1], configuration[2]
            cell = cells[current]
            x = x * div_x + cell % div_x
            y = y * div_y + cell // div_x
        return x, y

    def index_at_xy(self, level: int, x: int, y: int) -> int:
        """Convert a global grid coordinate back to the hierarchical tile index."""
        width, height = self.grid_size(level)
        if not 0 <= x < width or not 0 <= y < height:
            raise IndexError((level, x, y))
        cells = [0] * 4
        remaining_x, remaining_y = x, y
        for current in range(level, 0, -1):
            configuration = self.descriptors[current]["configuration"]
            div_x, div_y = configuration[1], configuration[2]
            cell_x, cell_y = remaining_x % div_x, remaining_y % div_y
            cells[current] = cell_y * div_x + cell_x
            remaining_x //= div_x
            remaining_y //= div_y
        if remaining_x or remaining_y:
            raise ValueError("grid coordinate does not fit the hierarchy")
        index = 0
        for current in range(1, level + 1):
            configuration = self.descriptors[current]["configuration"]
            index = index * configuration[1] * configuration[2] + cells[current]
        return index

    def tile_frame(self, level: int, index: int) -> dict:
        if not 0 <= index < self.descriptors[level]["count"]:
            raise IndexError((level, index))
        cells = [0] * 4
        remainder = index
        for current in range(level, 0, -1):
            configuration = self.descriptors[current]["configuration"]
            divisions = configuration[1] * configuration[2]
            if divisions == 0:
                raise ValueError(f"level {current} has zero grid divisions")
            cells[current] = remainder % divisions
            remainder //= divisions
        if remainder:
            raise ValueError("tile index does not fit the hierarchical grid")

        min_x, min_y, max_x, max_y = self.bounds
        for current in range(1, level + 1):
            configuration = self.descriptors[current]["configuration"]
            div_x, div_y = configuration[1], configuration[2]
            cell = cells[current]
            cell_x, cell_y = cell % div_x, cell // div_x
            step_x = (max_x - min_x) // div_x
            step_y = (max_y - min_y) // div_y
            min_x, max_x = min_x + cell_x * step_x, min_x + (cell_x + 1) * step_x
            min_y, max_y = min_y + cell_y * step_y, min_y + (cell_y + 1) * step_y
        centre_x = max_x - ((max_x - min_x + 1) // 2)
        centre_y = max_y - ((max_y - min_y + 1) // 2)
        return {
            "level": level,
            "index": index,
            "cells": cells,
            "bounds": (min_x, min_y, max_x, max_y),
            "centre": (centre_x, centre_y),
            "shift": self.descriptors[level]["configuration"][3],
        }

    def absolute_point(self, frame: dict, raw_x: int, raw_y: int) -> tuple[int, int]:
        centre_x, centre_y = frame["centre"]
        min_x, min_y, max_x, max_y = frame["bounds"]
        shift = frame["shift"]
        x = centre_x + (raw_x << shift)
        y = centre_y + (raw_y << shift)
        return snap_coordinate(x, min_x, max_x), snap_coordinate(y, min_y, max_y)

    def decode_block(self, level: int, index: int) -> dict:
        data, file_offset = self.read_block(level, index)
        expected_length = len(data)
        parsed = probe_block(data, expected_length, include_records=True)
        if not parsed["accepted"]:
            raise ValueError(f"L{level}[{index}] at {file_offset:#x}: {parsed['reason']}")
        frame = self.tile_frame(level, index)
        areas = []
        for record in parsed["tables"]["a"]["records"]:
            coordinates = []
            for point_index in range(record["data_length"]):
                position = record["data_offset"] + point_index * 4
                raw_x, raw_y = struct.unpack_from("<hh", data, position)
                coordinates.append(self.absolute_point(frame, raw_x, raw_y))
            areas.append({
                "type": record["type"],
                "flags": record["flags"],
                "unknown3": record["unknown3"],
                "unknown4": record["unknown4"],
                "trailing_uint32": record["trailing_uint32"],
                "coordinates": coordinates,
            })
        lines = []
        for record in parsed["tables"]["b_lines"]["records"]:
            coordinates = []
            for point_index in range(record["point_count"]):
                position = record["coordinate_offset"] + point_index * 4
                raw_x, raw_y = struct.unpack_from("<hh", data, position)
                coordinates.append(self.absolute_point(frame, raw_x, raw_y))
            lines.append({
                "type": record["type"],
                "flags": record["flags"],
                "text_offset": record["text_offset"],
                "coordinates": coordinates,
            })
        points = []
        for record in parsed["tables"]["c_points"]["records"]:
            points.append({
                "type": record["type"],
                "flags": record["flags"],
                "label_count": record["label_count"],
                "coordinate": self.absolute_point(frame, record["relative_x"], record["relative_y"]),
            })
        return {
            "level": level,
            "index": index,
            "file_offset": file_offset,
            "length": expected_length,
            "frame": frame,
            "areas": areas,
            "lines": lines,
            "points": points,
            "table_counts": {
                name: table["count"] for name, table in parsed["tables"].items()
            },
        }

    def selected_indices(self, level: int, per_group: int) -> dict[int, list[str]]:
        raw = self.directory_bytes(level)
        count = self.descriptors[level]["count"]
        uniform = sample_indices(count, per_group)
        eligible_count = 0
        for _, length in struct.iter_unpack("<II", raw):
            if length > 16:
                eligible_count += 1
        eligible_ranks = sample_indices(eligible_count, per_group)
        eligible = set()
        if eligible_ranks:
            rank = 0
            for index, (_, length) in enumerate(struct.iter_unpack("<II", raw)):
                if length > 16:
                    if rank in eligible_ranks:
                        eligible.add(index)
                    rank += 1
        selected = {index: ["uniform"] for index in uniform}
        for index in eligible:
            selected.setdefault(index, []).append("nonempty")
        return selected

    def validate_sample(self, per_group: int = 32) -> dict:
        levels = []
        for level, descriptor in enumerate(self.descriptors):
            selected = self.selected_indices(level, per_group)
            errors = []
            accepted = 0
            line_types = Counter()
            point_types = Counter()
            lines = 0
            points = 0
            for index in sorted(selected):
                try:
                    decoded = self.decode_block(level, index)
                    accepted += 1
                    lines += len(decoded["lines"])
                    points += len(decoded["points"])
                    line_types.update(line["type"] for line in decoded["lines"])
                    point_types.update(point["type"] for point in decoded["points"])
                except Exception as error:
                    if len(errors) < 20:
                        errors.append({"index": index, "error": str(error)})
            levels.append({
                "level": level,
                "record_count": descriptor["count"],
                "sample_count": len(selected),
                "accepted": accepted,
                "decoded_lines": lines,
                "decoded_points": points,
                "line_types": dict(sorted(line_types.items())),
                "point_types": dict(sorted(point_types.items())),
                "errors": errors,
            })
        return {
            "file": str(self.path),
            "file_size": self.file_size,
            "bounds": self.bounds,
            "coordinate_system": "TPMAP2 signed integer map units; WGS84 transform not yet established",
            "levels": levels,
        }


def parse_indices(value: str) -> list[int]:
    indices = set()
    for part in value.split(","):
        bounds = part.split("-", 1)
        start = int(bounds[0], 0)
        end = int(bounds[-1], 0)
        if end < start:
            raise ValueError(f"invalid descending index range: {part}")
        indices.update(range(start, end + 1))
    return sorted(indices)


def render_map(path: Path, level: int, output: Path, max_blocks: int = 0,
               include_areas: bool = False, indices: list[int] | None = None) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection

    tpmap = TPMap(path)
    block_count = tpmap.descriptors[level]["count"]
    if indices is None:
        selected = range(min(block_count, max_blocks) if max_blocks else block_count)
    else:
        selected = indices
    areas_by_type = {}
    lines_by_type = {}
    point_types = Counter()
    outside_tile_points = 0
    total_points = 0
    area_count = 0
    line_count = 0
    decoded_count = 0
    for index in selected:
        decoded = tpmap.decode_block(level, index)
        decoded_count += 1
        min_x, min_y, max_x, max_y = decoded["frame"]["bounds"]
        if include_areas:
            for area in decoded["areas"]:
                coordinates = area["coordinates"]
                if len(coordinates) < 2:
                    continue
                areas_by_type.setdefault(area["type"], []).append(coordinates)
                area_count += 1
        for line in decoded["lines"]:
            coordinates = line["coordinates"]
            if len(coordinates) < 2:
                continue
            lines_by_type.setdefault(line["type"], []).append(coordinates)
            line_count += 1
            for x, y in coordinates:
                total_points += 1
                if x < min_x or x > max_x or y < min_y or y > max_y:
                    outside_tile_points += 1
        point_types.update(point["type"] for point in decoded["points"])
    if not lines_by_type and not areas_by_type:
        raise ValueError("selected blocks contain no visible geometry")

    fig, ax = plt.subplots(figsize=(12, 10), dpi=180)
    feature_types = sorted(set(areas_by_type) | set(lines_by_type))
    colours = plt.cm.tab20.colors
    colour_by_type = {
        feature_type: colours[position % len(colours)]
        for position, feature_type in enumerate(feature_types)
    }
    for feature_type in sorted(areas_by_type):
        collection = PolyCollection(
            areas_by_type[feature_type],
            closed=True,
            facecolors=[colour_by_type[feature_type]],
            edgecolors=[colour_by_type[feature_type]],
            linewidths=0.55,
            alpha=0.35,
            label=f"A 0x{feature_type:02x}",
        )
        ax.add_collection(collection)
    for feature_type in sorted(lines_by_type):
        collection = LineCollection(
            lines_by_type[feature_type],
            colors=[colour_by_type[feature_type]],
            linewidths=0.7,
            alpha=0.85,
            label=f"B 0x{feature_type:02x}" if include_areas else f"0x{feature_type:02x}",
        )
        ax.add_collection(collection)
    geometry_groups = list(areas_by_type.values()) + list(lines_by_type.values())
    all_coordinates = [
        point for geometries in geometry_groups for geometry in geometries for point in geometry
    ]
    xs = [point[0] for point in all_coordinates]
    ys = [point[1] for point in all_coordinates]
    margin_x = max(1, (max(xs) - min(xs)) // 50)
    margin_y = max(1, (max(ys) - min(ys)) // 50)
    ax.set_xlim(min(xs) - margin_x, max(xs) + margin_x)
    ax.set_ylim(min(ys) - margin_y, max(ys) + margin_y)
    ax.set_aspect("equal", adjustable="box")
    object_kind = "geometry A+B" if include_areas else "table-B linear features"
    ax.set_title(f"{path.parent.name} — TPMAP2 L{level}, {object_kind}")
    ax.set_xlabel("X, internal TPMAP2 units")
    ax.set_ylabel("Y, internal TPMAP2 units")
    ax.grid(True, linewidth=0.2, alpha=0.35)
    if len(feature_types) * (2 if include_areas else 1) <= 20:
        ax.legend(title="Table / type", loc="best", fontsize=7, title_fontsize=8)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)

    stats = {
        "file": str(path),
        "level": level,
        "blocks_decoded": decoded_count,
        "areas_rendered": area_count,
        "area_types": {f"0x{key:02x}": len(value) for key, value in sorted(areas_by_type.items())},
        "lines_rendered": line_count,
        "line_types": {f"0x{key:02x}": len(value) for key, value in sorted(lines_by_type.items())},
        "point_types": {f"0x{key:02x}": value for key, value in sorted(point_types.items())},
        "coordinate_system": "TPMAP2 signed integer map units; not WGS84",
        "geometry_bounds": [min(xs), min(ys), max(xs), max(ys)],
        "outside_tile_points": outside_tile_points,
        "total_line_points": total_points,
        "outside_tile_fraction": outside_tile_points / total_points if total_points else 0,
        "image": str(output),
    }
    if indices is not None:
        stats["selected_indices"] = list(indices)
    stats_path = output.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate deterministic nonempty/uniform samples")
    validate.add_argument("files", nargs="+", type=Path)
    validate.add_argument("--samples", type=int, default=32)
    validate.add_argument("--output", required=True, type=Path)
    render = subparsers.add_parser("render", help="render raw geometry for a complete level or selected tiles")
    render.add_argument("file", type=Path)
    render.add_argument("--level", type=int, default=1, choices=range(4))
    render.add_argument("--max-blocks", type=int, default=0)
    render.add_argument("--indices", help="comma-separated zero-based tile indices or inclusive ranges")
    render.add_argument("--include-areas", action="store_true", help="render table-A polygonal geometry")
    render.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        results = []
        for path in args.files:
            result = TPMap(path).validate_sample(args.samples)
            results.append(result)
            print(path)
            for level in result["levels"]:
                print(
                    f"  L{level['level']}: {level['accepted']}/{level['sample_count']} valid, "
                    f"lines={level['decoded_lines']}, points={level['decoded_points']}, "
                    f"errors={len(level['errors'])}"
                )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {args.output}")
    elif args.command == "render":
        if args.indices and args.max_blocks:
            parser.error("--indices and --max-blocks are mutually exclusive")
        indices = parse_indices(args.indices) if args.indices else None
        stats = render_map(
            args.file, args.level, args.output, args.max_blocks, args.include_areas, indices
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
