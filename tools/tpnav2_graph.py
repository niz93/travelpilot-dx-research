#!/usr/bin/env python3
"""Recover the node/link layer of a decoded TPNAV2 cluster.

The two-pass endpoint resolution mirrors NAVECE_M.EXE at 0xffc937fc.
Coordinates remain internal integer units, not WGS84.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


class GraphFormatError(ValueError):
    pass


def u16(data: bytes, offset: int) -> int:
    require_range(data, offset, 2, "uint16")
    return struct.unpack_from("<H", data, offset)[0]


def require_range(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise GraphFormatError(
            f"{label}: range 0x{offset:x}..0x{offset + size:x} exceeds block size 0x{len(data):x}"
        )


def descriptor(data: bytes, offset: int, label: str) -> dict:
    require_range(data, offset, 4, label)
    value_offset, count = struct.unpack_from("<HH", data, offset)
    return {"descriptor_offset": offset, "offset": value_offset, "count": count}


def section_map(data: bytes) -> tuple[dict[int, dict], dict]:
    require_range(data, 0, 0x1A, "common header")
    flags, table_offset = struct.unpack_from("<HH", data, 0x16)
    sections = {}
    for bit in range(16):
        if not flags & (1 << bit):
            continue
        pair_offset = table_offset + len(sections) * 4
        item = descriptor(data, pair_offset, f"section bit {bit}")
        item["bit"] = bit
        sections[bit] = item
    header = {
        "declared_size": u16(data, 0),
        "byte02": data[2],
        "byte03": data[3],
        "field04_le32": struct.unpack_from("<I", data, 4)[0],
        "base_x": struct.unpack_from("<i", data, 8)[0],
        "base_y": struct.unpack_from("<i", data, 0x0C)[0],
        "coordinate_shift": data[0x10],
        "field11": data[0x11],
        "bounds_coordinate_offset": u16(data, 0x12),
        "bounds_coordinate_count": u16(data, 0x14),
        "section_flags": flags,
        "section_table_offset": table_offset,
        "wide_coordinates": bool(data[2] & 0x40),
    }
    return sections, header


def coordinate(data: bytes, offset: int, header: dict) -> dict:
    shift = header["coordinate_shift"]
    if header["wide_coordinates"]:
        require_range(data, offset, 6, "24-bit coordinate")
        dx = int.from_bytes(data[offset:offset + 3], "little", signed=False)
        dy = int.from_bytes(data[offset + 3:offset + 6], "little", signed=False)
        stride = 6
    else:
        require_range(data, offset, 4, "16-bit coordinate")
        dx, dy = struct.unpack_from("<hh", data, offset)
        stride = 4
    return {
        "offset": offset,
        "stride": stride,
        "delta_x": dx,
        "delta_y": dy,
        "x": header["base_x"] + (dx << shift),
        "y": header["base_y"] + (dy << shift),
    }


def coordinate_list(data: bytes, desc: dict, header: dict, label: str) -> list[dict]:
    stride = 6 if header["wide_coordinates"] else 4
    require_range(data, desc["offset"], desc["count"] * stride, label)
    return [coordinate(data, desc["offset"] + index * stride, header)
            for index in range(desc["count"])]


def parse_graph(data: bytes, source: str = "") -> dict:
    sections, header = section_map(data)
    if 6 not in sections or 7 not in sections:
        raise GraphFormatError("block has no 0x40/0x80 node/link section pair")
    if 10 not in sections:
        raise GraphFormatError("block has no 0x400 node-coordinate section")
    node_section = sections[6]
    link_section = sections[7]
    node_coord_section = sections[10]
    node_count = node_section["count"]
    link_count = link_section["count"]
    require_range(data, node_section["offset"], node_count * 6, "node records")
    require_range(data, link_section["offset"], link_count * 12, "link records")
    if node_coord_section["count"] < node_count:
        raise GraphFormatError(
            f"node-coordinate count {node_coord_section['count']} < node count {node_count}"
        )
    coord_desc = dict(node_coord_section)
    coord_desc["count"] = node_count
    node_coordinates = coordinate_list(data, coord_desc, header, "node coordinates")

    nodes = []
    for index in range(node_count):
        offset = node_section["offset"] + index * 6
        raw_id, flags, subsection_base = struct.unpack_from("<HHH", data, offset)
        node = {
            "index": index + 1,
            "record_offset": offset,
            "field0": raw_id,
            "flags": flags,
            "subsection_base": subsection_base,
            "coordinate": node_coordinates[index],
            "link_references": [],
        }
        if flags & 2:
            desc_offset = subsection_base + (4 if flags & 1 else 0)
            desc = descriptor(data, desc_offset, f"node {index + 1} link-list descriptor")
            require_range(data, desc["offset"], desc["count"] * 2, f"node {index + 1} link list")
            for item_index in range(desc["count"]):
                raw = u16(data, desc["offset"] + item_index * 2)
                node["link_references"].append({
                    "raw": raw,
                    "link_index": raw & 0x3FF,
                    "endpoint": "second" if raw & 0x8000 else "first",
                    "reference_offset": desc["offset"] + item_index * 2,
                })
            node["link_list"] = desc
        nodes.append(node)

    links = []
    for index in range(link_count):
        offset = link_section["offset"] + index * 12
        raw_first, raw_second, field04, flags, subsection_base = struct.unpack_from("<HHIHH", data, offset)
        link = {
            "index": index + 1,
            "record_offset": offset,
            "raw_first": raw_first,
            "raw_second": raw_second,
            "field04_le32": field04,
            "flags": flags,
            "subsection_base": subsection_base,
            "subsections": {},
            "shape_points": [],
        }
        subsection_index = 0
        for bit, name in ((0, "annotations"), (1, "shape"), (2, "unknown_bit2"),
                          (3, "list4_a"), (4, "list4_b")):
            if not flags & (1 << bit):
                continue
            desc_offset = subsection_base + subsection_index * 4
            desc = descriptor(data, desc_offset, f"link {index + 1} {name} descriptor")
            link["subsections"][name] = desc
            if name == "shape":
                link["shape_points"] = coordinate_list(data, desc, header, f"link {index + 1} shape")
            elif name.startswith("list4"):
                require_range(data, desc["offset"], desc["count"] * 4, f"link {index + 1} {name}")
                link[name] = [data[desc["offset"] + i * 4:desc["offset"] + i * 4 + 4].hex(" ")
                              for i in range(desc["count"])]
            subsection_index += 1
        links.append(link)

    errors = []
    endpoint_writes = 0
    endpoint_conflicts = []
    for node in nodes:
        for reference in node["link_references"]:
            link_index = reference["link_index"]
            if not 1 <= link_index <= link_count:
                errors.append(
                    f"node {node['index']} references link {link_index}, outside 1..{link_count}"
                )
                continue
            link = links[link_index - 1]
            endpoint = reference["endpoint"]
            key = "resolved_" + endpoint
            if key in link and link[key] != node["index"]:
                endpoint_conflicts.append({
                    "link_index": link_index,
                    "endpoint": endpoint,
                    "old_node": link[key],
                    "new_node": node["index"],
                })
            link[key] = node["index"]
            link[endpoint + "_source"] = "node_link_list"
            endpoint_writes += 1

    for link in links:
        for endpoint, raw_key in (("first", "raw_first"), ("second", "raw_second")):
            key = "resolved_" + endpoint
            if key not in link:
                link[key] = link[raw_key] & 0x3FF
                link[endpoint + "_source"] = "raw_record"
            if not 1 <= link[key] <= node_count:
                errors.append(
                    f"link {link['index']} {endpoint} node {link[key]} outside 1..{node_count}"
                )
        if all(1 <= link["resolved_" + end] <= node_count for end in ("first", "second")):
            first = nodes[link["resolved_first"] - 1]["coordinate"]
            last = nodes[link["resolved_second"] - 1]["coordinate"]
            link["path_coordinates"] = [
                {"x": first["x"], "y": first["y"], "kind": "first_node"},
                *({"x": point["x"], "y": point["y"], "kind": "shape"} for point in link["shape_points"]),
                {"x": last["x"], "y": last["y"], "kind": "second_node"},
            ]

    bounds_desc = {
        "offset": header["bounds_coordinate_offset"],
        "count": header["bounds_coordinate_count"],
    }
    bounds = coordinate_list(data, bounds_desc, header, "cluster bounds coordinates")
    return {
        "source": source,
        "block_size": len(data),
        "header": header,
        "sections": {f"0x{1 << bit:04x}": item for bit, item in sections.items()},
        "bounds_coordinates": bounds,
        "nodes": nodes,
        "links": links,
        "validation": {
            "node_count": node_count,
            "link_count": link_count,
            "node_link_reference_count": endpoint_writes,
            "endpoint_conflicts": endpoint_conflicts,
            "errors": errors,
            "topologically_consistent": not errors and not endpoint_conflicts,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summaries = []
    for path in args.files:
        data = path.read_bytes()
        try:
            graph = parse_graph(data, str(path))
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output = args.output_dir / (path.stem + ".json")
            output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            summary = {"file": str(path), "output": str(output), **graph["validation"]}
        except (GraphFormatError, struct.error) as exc:
            summary = {"file": str(path), "error": str(exc)}
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
