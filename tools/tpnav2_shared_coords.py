#!/usr/bin/env python3
"""Find shared coordinates between clusters' 0x0004/0x0008 records.

A coordinate pair from one cluster's section record that also appears in another
cluster's record is a candidate cross-cluster boundary node. For each shared
coordinate, check proximity to local endpoints of links whose other endpoint is
unresolved (the 948 dangling ends from iteration 1).
"""
from __future__ import annotations
import json, struct, sys, math
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import section_map, coordinate_list, parse_graph

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "analysis" / "tpnav2" / "regional-blocks"
OUT = ROOT / "analysis" / "tpnav2" / "shared-coordinates.json"


def records_u32_pairs(data, sections, bit, block_size):
    if bit not in sections:
        return []
    s = sections[bit]
    start = s["offset"]; count = s["count"]
    following = [v["offset"] for k, v in sections.items() if v["offset"] > start]
    end = min(following) if following else block_size
    if not count or (end - start) % count:
        return []
    stride = (end - start) // count
    out = []
    for i in range(count):
        ro = start + i * stride
        x, y = struct.unpack_from("<II", data, ro)
        out.append((i, ro, x, y))
    return out


def main():
    coord_index = defaultdict(list)  # (x,y) -> [(file, section, record)]
    cluster_info = {}
    graphs = {}
    for block_dir in sorted(BLOCKS.iterdir()):
        for f in sorted(block_dir.glob("entry-*.bin")):
            data = f.read_bytes()
            try:
                sections, header = section_map(data)
            except Exception:
                continue
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            for bit in (2, 3):
                for i, ro, x, y in records_u32_pairs(data, sections, bit, len(data)):
                    coord_index[(x, y)].append({"file": rel, "section": f"0x{1 << bit:04x}",
                                                "record": i, "record_offset": ro})
            try:
                g = parse_graph(data, rel)
                graphs[rel] = g
                cluster_info[rel] = {
                    "bounds": g["bounds_coordinates"],
                    "unresolved": [],
                }
                for link in g["links"]:
                    n = len(g["nodes"])
                    rf, rs = link["resolved_first"], link["resolved_second"]
                    if not (1 <= rf <= n) or not (1 <= rs <= n):
                        # find the local endpoint(s)
                        for end, res in (("first", rf), ("second", rs)):
                            if 1 <= res <= n:
                                coord = g["nodes"][res - 1]["coordinate"]
                                cluster_info[rel]["unresolved"].append({
                                    "link_index": link["index"], "local_end": end,
                                    "node_index": res, "x": coord["x"], "y": coord["y"],
                                    "raw_other": link["raw_second"] if end == "first" else link["raw_first"],
                                })
            except Exception:
                pass

    shared = {k: v for k, v in coord_index.items() if len({e["file"] for e in v}) > 1}
    # proximity check: shared coord vs local unresolved endpoints
    results = []
    for (x, y), entries in sorted(shared.items()):
        files = sorted({e["file"] for e in entries})
        hits = []
        for rel in files:
            for u in cluster_info.get(rel, {}).get("unresolved", []):
                d = math.hypot(u["x"] - x, u["y"] - y)
                if d <= 64:  # within one 16-bit coord quantum (<<3)
                    hits.append({"file": rel, **u, "distance": d})
        results.append({"coordinate": [x, y], "records": entries, "endpoint_hits": hits})

    OUT.write_text(json.dumps({
        "unique_shared_coordinates": len(shared),
        "with_endpoint_hits": sum(1 for r in results if r["endpoint_hits"]),
        "results": results,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"shared coords: {len(shared)}, with nearby unresolved endpoints (<=64u): "
          f"{sum(1 for r in results if r['endpoint_hits'])}")
    for r in results[:20]:
        print(r["coordinate"], [e["file"].split("/")[-1] for e in r["records"]],
              "hits:", len(r["endpoint_hits"]))


if __name__ == "__main__":
    main()
