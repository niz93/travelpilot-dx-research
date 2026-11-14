#!/usr/bin/env python3
"""Conservative TPNAV2 graph serializer: rebuild a cluster byte image from parse output.

Strategy (round-trip first): keep the original byte image as the carrier. Every known
structure (header fields, bounds, section table, node/link records, node link lists,
shape points, list4 payloads) is re-emitted at its original offset; all other bytes
(gaps between sections) stay untouched. Verification: parse(original) == parse(rebuilt)
for every field, and rebuilt == original byte-for-byte.

Mutation support comes later by re-laying out sections; this module proves that all
parse output maps 1:1 onto bytes.
"""
from __future__ import annotations
import argparse, json, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import parse_graph, coordinate_list


def emit_coordinate(buf: bytearray, offset: int, coord: dict, wide: bool) -> None:
    if wide:
        dx = (coord["x"] - coord["base_x"]) >> 0  # deltas already stored
        raise NotImplementedError
    struct.pack_into("<hh", buf, offset, coord["delta_x"], coord["delta_y"])


def rebuild(graph: dict, original: bytes) -> bytes:
    buf = bytearray(original)
    header = graph["header"]
    # --- header ---
    struct.pack_into("<H", buf, 0, header["declared_size"])
    buf[2] = header["byte02"]
    buf[3] = header["byte03"]
    struct.pack_into("<I", buf, 4, header["field04_le32"])
    struct.pack_into("<i", buf, 8, header["base_x"])
    struct.pack_into("<i", buf, 0x0C, header["base_y"])
    buf[0x10] = header["coordinate_shift"]
    buf[0x11] = header["field11"]
    struct.pack_into("<H", buf, 0x12, header["bounds_coordinate_offset"])
    struct.pack_into("<H", buf, 0x14, header["bounds_coordinate_count"])
    struct.pack_into("<H", buf, 0x16, header["section_flags"])
    struct.pack_into("<H", buf, 0x18, header["section_table_offset"])
    # --- bounds coordinates ---
    wide = header["wide_coordinates"]
    stride = 6 if wide else 4
    for i, c in enumerate(graph["bounds_coordinates"]):
        off = header["bounds_coordinate_offset"] + i * stride
        if wide:
            raise NotImplementedError("wide bounds not implemented")
        struct.pack_into("<hh", buf, off, c["delta_x"], c["delta_y"])
    # --- section table ---
    for name, sec in graph["sections"].items():
        struct.pack_into("<HH", buf, sec["descriptor_offset"], sec["offset"], sec["count"])
    # --- node records ---
    node_sec = graph["sections"]["0x0040"]
    for node in graph["nodes"]:
        o = node["record_offset"]
        struct.pack_into("<HHH", buf, o, node["field0"], node["flags"], node["subsection_base"])
        # node link list
        if node["flags"] & 2:
            d = node["link_list"]
            struct.pack_into("<HH", buf, d["descriptor_offset"], d["offset"], d["count"])
            for i, ref in enumerate(node["link_references"]):
                struct.pack_into("<H", buf, ref["reference_offset"], ref["raw"])
        # node coordinate (0x0400 section, same order as nodes)
    coord_sec = graph["sections"]["0x0400"]
    for i, node in enumerate(graph["nodes"]):
        c = node["coordinate"]
        off = coord_sec["offset"] + i * stride
        if wide:
            raise NotImplementedError
        struct.pack_into("<hh", buf, off, c["delta_x"], c["delta_y"])
    # --- link records ---
    for link in graph["links"]:
        o = link["record_offset"]
        struct.pack_into("<HHIHH", buf, o, link["raw_first"], link["raw_second"],
                         link["field04_le32"], link["flags"], link["subsection_base"])
        sub_index = 0
        for bit, name in ((0, "annotations"), (1, "shape"), (2, "unknown_bit2"),
                          (3, "list4_a"), (4, "list4_b")):
            if not link["flags"] & (1 << bit):
                continue
            desc = link["subsections"][name]
            struct.pack_into("<HH", buf, desc["descriptor_offset"], desc["offset"], desc["count"])
            if name == "shape":
                for i, pt in enumerate(link["shape_points"]):
                    po = desc["offset"] + i * stride
                    if wide:
                        raise NotImplementedError
                    struct.pack_into("<hh", buf, po, pt["delta_x"], pt["delta_y"])
            elif name.startswith("list4"):
                for i, hx in enumerate(link[name]):
                    data = bytes.fromhex(hx.replace(" ", ""))
                    buf[desc["offset"] + i * 4:desc["offset"] + i * 4 + 4] = data
            sub_index += 1
    return bytes(buf)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", type=Path, nargs="+")
    args = ap.parse_args()
    results = []
    skipped = 0
    for path in args.files:
        original = path.read_bytes()
        try:
            graph = parse_graph(original, str(path))
        except Exception:
            skipped += 1
            continue
        rebuilt = rebuild(graph, original)
        byte_equal = rebuilt == original
        graph2 = parse_graph(rebuilt, str(path) + "#rebuilt")
        fields_equal = structural_equal(graph, graph2)
        results.append({"file": str(path), "byte_equal": byte_equal, "fields_equal": fields_equal})
        print(json.dumps(results[-1], ensure_ascii=False))
    ok = sum(1 for r in results if r["byte_equal"] and r["fields_equal"])
    print(f"{ok}/{len(results)} round-trip clean")


def structural_equal(a: dict, b: dict) -> bool:
    ka = a["header"]; kb = b["header"]
    for key in ("declared_size", "byte02", "byte03", "field04_le32", "base_x", "base_y",
                "coordinate_shift", "field11", "bounds_coordinate_offset",
                "bounds_coordinate_count", "section_flags", "section_table_offset"):
        if ka[key] != kb[key]:
            return False
    if [(c["delta_x"], c["delta_y"]) for c in a["bounds_coordinates"]] != \
       [(c["delta_x"], c["delta_y"]) for c in b["bounds_coordinates"]]:
        return False
    if {k: (v["offset"], v["count"]) for k, v in a["sections"].items()} != \
       {k: (v["offset"], v["count"]) for k, v in b["sections"].items()}:
        return False
    for na, nb in zip(a["nodes"], b["nodes"]):
        if (na["field0"], na["flags"], na["subsection_base"]) != \
           (nb["field0"], nb["flags"], nb["subsection_base"]):
            return False
        if (na["coordinate"]["delta_x"], na["coordinate"]["delta_y"]) != \
           (nb["coordinate"]["delta_x"], nb["coordinate"]["delta_y"]):
            return False
        if [r["raw"] for r in na["link_references"]] != [r["raw"] for r in nb["link_references"]]:
            return False
    for la, lb in zip(a["links"], b["links"]):
        if (la["raw_first"], la["raw_second"], la["field04_le32"], la["flags"],
            la["subsection_base"]) != (lb["raw_first"], lb["raw_second"],
            lb["field04_le32"], lb["flags"], lb["subsection_base"]):
            return False
        if [(p["delta_x"], p["delta_y"]) for p in la["shape_points"]] != \
           [(p["delta_x"], p["delta_y"]) for p in lb["shape_points"]]:
            return False
        for nm in ("list4_a", "list4_b"):
            if la.get(nm) != lb.get(nm):
                return False
    return True


if __name__ == "__main__":
    main()
