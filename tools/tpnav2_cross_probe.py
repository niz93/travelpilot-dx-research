#!/usr/bin/env python3
"""Probe sections 0x0004/0x0008 as cross-cluster boundary-node candidates.

Checks:
 1. Actual byte span of sections 0x0004 / 0x0008 vs descriptor count (derive stride).
 2. First two u32 of each record as absolute coordinates: do they fall inside
    cluster bounds (like the u32 pair in the 0x0004 record header of entry 95)?
 3. Do those coordinates sit near cluster bounds edges / near local endpoints
    of links whose other endpoint is unresolved (cross-cluster candidates)?
"""
from __future__ import annotations
import json, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import section_map, coordinate_list, parse_graph

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "analysis" / "tpnav2" / "regional-blocks"
OUT = ROOT / "analysis" / "tpnav2" / "cross-cluster-probe.json"


def section_span(sections: dict, bit: int, block_size: int, next_offsets: list[int]) -> dict | None:
    if bit not in sections:
        return None
    s = sections[bit]
    start = s["offset"]
    following = [o for b, o in next_offsets if o > start]
    end = min(following) if following else block_size
    count = s["count"]
    span = end - start
    return {"offset": start, "count": count, "span": span,
            "stride_if_even": (span / count) if count else None}


def main() -> None:
    report = {"clusters": [], "summary": {}}
    stride_votes = {2: [], 3: []}
    for block_dir in sorted(BLOCKS.iterdir()):
        for f in sorted(block_dir.glob("entry-*.bin")):
            data = f.read_bytes()
            try:
                sections, header = section_map(data)
            except Exception:
                continue
            bits = sorted(sections)
            next_offsets = [(b, sections[b]["offset"]) for b in bits]
            spans = {}
            for bit in (2, 3):
                sp = section_span(sections, bit, len(data), next_offsets)
                if sp:
                    spans[bit] = sp
                    if sp["count"] and sp["span"] % sp["count"] == 0:
                        stride_votes[bit].append(sp["span"] // sp["count"])
            # coordinates: header-like pair (u32,u32) at record start
            bounds_desc = {"offset": header["bounds_coordinate_offset"],
                           "count": header["bounds_coordinate_count"]}
            try:
                bounds = coordinate_list(data, bounds_desc, header, "bounds")
                xs = [c["x"] for c in bounds]; ys = [c["y"] for c in bounds]
                bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
            except Exception:
                continue
            records = []
            for bit in (2, 3):
                if bit not in spans:
                    continue
                sp = spans[bit]
                stride = sp["span"] // sp["count"] if sp["count"] and sp["span"] % sp["count"] == 0 else None
                if not stride:
                    continue
                for i in range(sp["count"]):
                    ro = sp["offset"] + i * stride
                    x, y = struct.unpack_from("<II", data, ro)
                    records.append({
                        "section": f"0x{1 << bit:04x}", "record": i, "record_offset": ro,
                        "u32_0": x, "u32_1": y,
                        "inside_bounds": bx0 <= x <= bx1 and by0 <= y <= by1,
                        "rel_to_base": [x - header["base_x"], y - header["base_y"]],
                    })
            report["clusters"].append({
                "file": str(f.relative_to(ROOT)),
                "flags": hex(header["section_flags"]),
                "base": [header["base_x"], header["base_y"]],
                "bounds": {"x": [bx0, bx1], "y": [by0, by1]},
                "spans": {f"0x{1 << b:04x}": spans[b] for b in spans},
                "u32_pairs": records,
            })
    from collections import Counter
    report["summary"] = {
        "stride_votes_0x0004": Counter(stride_votes[2]).most_common(),
        "stride_votes_0x0008": Counter(stride_votes[3]).most_common(),
        "clusters_total": len(report["clusters"]),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
