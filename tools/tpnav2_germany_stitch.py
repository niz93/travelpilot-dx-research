#!/usr/bin/env python3
"""Full-Germany boundary-stitch run.

Decodes every entry of every NAV file of the Germany set, parses graph clusters,
collects unresolved endpoints, and stitches them across cluster boundaries by the
confirmed rule: equal word body (raw & 0x3ff) + overlapping bounds + coincident
local endpoint geometry.
"""
from __future__ import annotations
import json, math, struct, sys, time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import parse_graph, GraphFormatError
from tpnav2_container import decompress

ROOT = Path(__file__).resolve().parent.parent
NAV_DIR = ROOT / "extracted" / "germany"
OUT_IDX = ROOT / "analysis" / "tpnav2" / "germany-full-index.json"
OUT_STITCH = ROOT / "analysis" / "tpnav2" / "germany-full-stitch.json"

GRAPH_SECTION_BITS = 0x0040 | 0x0080 | 0x0400  # 0x4C0


def decode_entry(data: bytes, entry) -> bytes | None:
    physical = data[entry.physical_offset:entry.physical_offset + entry.physical_size]
    if entry.compression_flag == 0:
        return physical
    try:
        decoded, _ = decompress(physical, entry.logical_size)
        return decoded
    except Exception:
        return None


def is_graph_candidate(decoded: bytes) -> bool:
    if len(decoded) < 0x1A:
        return False
    flags = struct.unpack_from("<H", decoded, 0x16)[0]
    return (flags & GRAPH_SECTION_BITS) == GRAPH_SECTION_BITS


def collect() -> dict:
    files = sorted(NAV_DIR.glob("NAV*.DAT"))
    clusters = {}
    stats = {"files": 0, "entries_total": 0, "graph_candidates": 0, "parsed": 0,
             "parse_errors": 0, "unresolved_endpoints": 0}
    t0 = time.time()
    for fi, path in enumerate(files):
        raw = path.read_bytes()
        if len(raw) < 26:
            continue
        try:
            table_header_offset = struct.unpack_from("<I", raw, 4)[0]
            entry_count, table_offset = struct.unpack_from("<II", raw, table_header_offset)
        except struct.error:
            continue
        stats["files"] += 1
        for index in range(entry_count):
            off = table_offset + index * 16
            if off + 16 > len(raw):
                break
            logical_offset, logical_size, _f06, physical_offset, physical_size, cflag = \
                struct.unpack_from("<IHHIHH", raw, off)
            stats["entries_total"] += 1
            if physical_offset + physical_size > len(raw):
                continue
            physical = raw[physical_offset:physical_offset + physical_size]
            if cflag == 0:
                decoded = physical
            else:
                try:
                    decoded, _ = decompress(physical, logical_size)
                except Exception:
                    continue
            if len(decoded) < logical_size:
                continue
            if not is_graph_candidate(decoded):
                continue
            stats["graph_candidates"] += 1
            key = f"{path.name}#e{index:04d}@0x{logical_offset:x}"
            try:
                g = parse_graph(decoded, key)
            except (GraphFormatError, struct.error):
                stats["parse_errors"] += 1
                continue
            n = len(g["nodes"])
            if n == 0:
                continue
            stats["parsed"] += 1
            b = g["bounds_coordinates"]
            xs = [c["x"] for c in b]; ys = [c["y"] for c in b]
            unres = []
            for l in g["links"]:
                ok_f, ok_s = 1 <= l["resolved_first"] <= n, 1 <= l["resolved_second"] <= n
                if not ok_f or not ok_s:
                    for end, ok, res, raww in (("first", ok_f, l["resolved_first"], l["raw_first"]),
                                               ("second", ok_s, l["resolved_second"], l["raw_second"])):
                        if ok:
                            c = g["nodes"][res - 1]["coordinate"]
                            unres.append({"link": l["index"], "end": end, "node": res,
                                          "x": c["x"], "y": c["y"], "raw": raww,
                                          "body": raww & 0x3ff})
                            stats["unresolved_endpoints"] += 1
            clusters[key] = {"file": path.name, "bounds": [min(xs), max(xs), min(ys), max(ys)],
                             "unres": unres}
        if (fi + 1) % 100 == 0:
            print(f"[{fi+1}/{len(files)}] files, {stats['parsed']} clusters, "
                  f"{stats['unresolved_endpoints']} unresolved, {time.time()-t0:.0f}s", flush=True)
    return {"stats": stats, "clusters": clusters}


def stitch(data: dict) -> dict:
    clusters = data["clusters"]
    by_body = defaultdict(list)
    for key, c in clusters.items():
        for u in c["unres"]:
            by_body[u["body"]].append((key, u))
    matches = []
    used = set()
    for body, occ in sorted(by_body.items()):
        if len(occ) < 2:
            continue
        for i in range(len(occ)):
            for j in range(i + 1, len(occ)):
                ki, ui = occ[i]; kj, uj = occ[j]
                if ki == kj:
                    continue
                if (ki, ui["link"], ui["end"]) in used or (kj, uj["link"], uj["end"]) in used:
                    continue
                ax0, ax1, ay0, ay1 = clusters[ki]["bounds"]
                bx0, bx1, by0, by1 = clusters[kj]["bounds"]
                if min(ax1, bx1) - max(ax0, bx0) <= 0 or min(ay1, by1) - max(ay0, by0) <= 0:
                    continue
                d = math.hypot(ui["x"] - uj["x"], ui["y"] - uj["y"])
                if d <= 1000:
                    matches.append({"body": body,
                                    "a": {"cluster": ki, **{k: v for k, v in ui.items() if k != "body"}},
                                    "b": {"cluster": kj, **{k: v for k, v in uj.items() if k != "body"}},
                                    "distance": d})
                    used.add((ki, ui["link"], ui["end"]))
                    used.add((kj, uj["link"], uj["end"]))
    total_unres = sum(len(c["unres"]) for c in clusters.values())
    return {"matches": matches,
            "total_unresolved_endpoints": total_unres,
            "stitched_endpoints": len(used),
            "unique_bodies": len(by_body),
            "multi_occurrence_bodies": sum(1 for v in by_body.values() if len(v) > 1)}


def main() -> None:
    data = collect()
    OUT_IDX.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print("collect stats:", json.dumps(data["stats"], indent=1))
    result = stitch(data)
    OUT_STITCH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("stitch:", json.dumps({k: v for k, v in result.items() if k != "matches"}, indent=1))
    dists = sorted(m["distance"] for m in result["matches"])
    if dists:
        print("distance median:", round(dists[len(dists)//2], 1),
              "p95:", round(dists[int(len(dists)*0.95)], 1),
              "max:", round(dists[-1], 1))


if __name__ == "__main__":
    main()
