#!/usr/bin/env python3
"""Emulate the two firmware passes that resolve TPNAV2 cluster link endpoints.

Pass L (loader, FUN_ram_ffc937fc ram:ffc937fc): for every node, for every uint16
reference in the node's link list, write the node index (1-based) into the link
record's first (ref bit 0x8000 clear) or second (0x8000 set) u16 field.
No 0x0800 check, no range check (out-of-range writes go to a sentinel and are
harmless). Later writes overwrite earlier ones. This mirrors tools/tpnav2_graph.py.

Pass C (consumer, FUN_ram_ffc812ee ram:ffc812ee): build a per-link endpoint
coordinate table. References with bit 0x0800 set are SKIPPED, and
(raw & 0x3ff) > link_count is skipped. The endpoint coordinate stamped is the
NODE's own coordinate (from the 0x400 coordinate table indexed by the node
record index). After the sweep, the cluster is REJECTED unless every link has
both endpoint x-coordinates non-zero, i.e. every link end must be covered by at
least one non-skipped node-list reference.

Usage:
    python tools/tpnav2_firmware_pass.py --survey analysis/tpnav2/regional-survey.json \
        --decoded-dir analysis/tpnav2/regional-blocks \
        --output analysis/tpnav2/firmware-pass-probe.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path


def load_tpnav2_graph():
    spec = importlib.util.spec_from_file_location(
        "tpnav2_graph", Path(__file__).with_name("tpnav2_graph.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emulate(graph):
    """Run both firmware passes over a parsed graph. Returns result dict."""
    nodes = graph["nodes"]
    links = graph["links"]
    node_count = len(nodes)
    link_count = len(links)
    coords = [n["coordinate"] for n in nodes]

    # ---- Pass L: loader overwrite (no 0x0800 skip) ----
    loader_first = [None] * link_count
    loader_second = [None] * link_count
    loader_writes = 0
    for node in nodes:
        for ref in node["link_references"]:
            li = ref["link_index"]  # parser already applied raw & 0x3ff
            if not 1 <= li <= link_count:
                continue  # firmware writes into a sentinel; harmless
            loader_writes += 1
            if ref["endpoint"] == "first":
                loader_first[li - 1] = node["index"]
            else:
                loader_second[li - 1] = node["index"]

    loader_mismatch = []
    for i, link in enumerate(links):
        for side, loader_val in (("first", loader_first[i]), ("second", loader_second[i])):
            parser_val = link.get("resolved_" + side)
            parser_src = link.get(side + "_source")
            if parser_src == "node_link_list" and parser_val != loader_val:
                loader_mismatch.append(
                    {"link": link["index"], "side": side,
                     "parser": parser_val, "loader": loader_val}
                )

    # ---- Pass C: coordinate table with 0x0800 skip ----
    # endpoint_table[link_index] = {"first": {x,y,node,refcount}|None, "second": ...}
    endpoint_table = [{"first": None, "second": None} for _ in range(link_count)]
    skipped_0800 = 0
    skipped_range = 0
    for node in nodes:
        refs = node["link_references"]
        refcount = len(refs)
        for ref in refs:
            raw = ref["raw"]
            if raw & 0x0800:
                skipped_0800 += 1
                continue
            li = raw & 0x3ff
            if li > link_count:
                skipped_range += 1
                continue
            side = "second" if raw & 0x8000 else "first"
            entry = {
                "x": coords[node["index"] - 1]["x"],
                "y": coords[node["index"] - 1]["y"],
                "node": node["index"],
                "refcount": refcount,
            }
            # later writes overwrite earlier ones, same as the firmware store
            endpoint_table[li - 1][side] = entry

    uncovered = []
    for i, ends in enumerate(endpoint_table):
        for side in ("first", "second"):
            entry = ends[side]
            # firmware rejects when the stored absolute x coordinate is 0;
            # real coordinates are never 0, so treat "not covered" as the criterion
            if entry is None or entry["x"] == 0:
                uncovered.append({"link": i + 1, "side": side})
    verdict = "pass" if not uncovered else "fail"

    return {
        "node_count": node_count,
        "link_count": link_count,
        "loader_writes": loader_writes,
        "loader_parser_mismatch": loader_mismatch,
        "skipped_0800_refs": skipped_0800,
        "skipped_range_refs": skipped_range,
        "verdict": verdict,
        "uncovered_end_count": len(uncovered),
        "uncovered_ends": uncovered,
        "endpoint_table": endpoint_table if verdict == "pass" else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--decoded-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tp = load_tpnav2_graph()
    survey = json.loads(args.survey.read_text(encoding="utf-8"))

    results = []
    totals = Counter()
    for f in survey["files"]:
        parts = f["file"].replace("\\", "/").split("/")
        dirn = parts[-2] + "-" + parts[-1].replace(".DAT", "")
        for block in f.get("blocks", []):
            entry = block.get("entry")
            block_info = block.get("block") or {}
            if not entry or not block_info.get("sections"):
                continue
            name = f"entry-{entry['index']:04d}-lo{entry['logical_offset']:08x}"
            path = args.decoded_dir / dirn / (name + ".bin")
            if not path.exists():
                continue
            data = path.read_bytes()
            try:
                graph = tp.parse_graph(data, str(path))
            except Exception as exc:
                results.append({"file": f["file"], "block": name, "error": str(exc)})
                totals["parse_error"] += 1
                continue
            emu = emulate(graph)
            consistent = graph["validation"]["topologically_consistent"]
            emu["parser_consistent"] = consistent
            emu["agree"] = (emu["verdict"] == "pass") == consistent
            results.append({"file": f["file"], "block": name, **emu})
            totals[f"verdict_{emu['verdict']}"] += 1
            totals["loader_mismatch"] += len(emu["loader_parser_mismatch"])
            if emu["agree"]:
                totals["agree"] += 1
            else:
                totals["disagree"] += 1

    report = {
        "description": "Emulation of FUN_ram_ffc937fc (loader endpoint overwrite) "
        "and FUN_ram_ffc812ee (coordinate-table consumer with 0x0800 skip)",
        "totals": dict(totals),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
