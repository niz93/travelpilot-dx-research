#!/usr/bin/env python3
"""Embed a mutated TPNAV2 cluster back into a NAV remap container.

Strategy per entry:
  - uncompressed entry with physical_size == logical_size: in-place byte patch
  - anything else: append the (padded) uncompressed block at end of file and
    rewrite the remap entry to point at it with compression_flag = 0
      (firmware searches the remap table from the end for the exact
       logical offset/size pair, so the last matching entry wins — we patch
       the last exact match, mirroring that behavior)

The replacement block is zero-padded to the entry's logical size; the TPNAV2
cluster format self-describes its used length (declared_size + section table),
so trailing padding is inert for our tooling and tolerated by the firmware
round-trip evidence gathered so far.

Verification pass re-opens the patched container, decodes the block, and
parses it as a graph.
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_container import NavContainer, NavContainerError
from tpnav2_graph import parse_graph
from tpnav2_graph_mutate import ClusterModel

ENTRY_STRUCT = struct.Struct("<IHHIHH")


def patch(nav_path: Path, logical_offset: int, logical_size: int,
          cluster: bytes, out_path: Path, verify: bool = True) -> dict:
    container = NavContainer(nav_path)
    entry = container.find_entry(logical_offset, logical_size)
    if len(cluster) > logical_size:
        raise NavContainerError(
            f"cluster ({len(cluster)}B) exceeds logical size {logical_size}"
        )
    block = cluster + b"\0" * (logical_size - len(cluster))

    data = bytearray(container.data)
    report = {
        "entry_index": entry.index,
        "logical_offset": logical_offset,
        "logical_size": logical_size,
        "orig_physical_offset": entry.physical_offset,
        "orig_physical_size": entry.physical_size,
        "orig_compression_flag": entry.compression_flag,
        "cluster_size": len(cluster),
    }
    if entry.compression_flag == 0 and entry.physical_size == entry.logical_size:
        data[entry.physical_offset:entry.physical_offset + entry.physical_size] = block
        report["mode"] = "in-place"
    else:
        new_offset = len(data)
        data.extend(block)
        values = (logical_offset, logical_size, entry.field06,
                  new_offset, len(block), 0)
        ENTRY_STRUCT.pack_into(data, container.table_offset + entry.index * 16, *values)
        report["mode"] = "append"
        report["new_physical_offset"] = new_offset
    out_path.write_bytes(bytes(data))
    report["output"] = str(out_path)
    report["output_size"] = len(data)

    if verify:
        check = NavContainer(out_path)
        decoded, new_entry, _ = check.read_block(logical_offset, logical_size)
        graph = parse_graph(decoded, "patched")
        report["verify"] = {
            "decoded_size": len(decoded),
            "declared_size": struct.unpack_from("<H", decoded, 0)[0],
            "nodes": len(graph["nodes"]),
            "links": len(graph["links"]),
            "errors": graph["validation"]["errors"][:5],
            "conflicts": len(graph["validation"]["endpoint_conflicts"]),
            "patched_entry": {
                "physical_offset": new_entry.physical_offset,
                "physical_size": new_entry.physical_size,
                "compression_flag": new_entry.compression_flag,
            },
        }
        # semantic identity between supplied cluster and what reads back
        ref = parse_graph(cluster, "ref")
        proj = lambda g: (
            [(n["field0"], n["flags"], [r["raw"] for r in n["link_references"]])
             for n in g["nodes"]],
            [(l["raw_first"], l["raw_second"], l["field04_le32"], l["flags"])
             for l in g["links"]],
        )
        report["verify"]["roundtrip_identical"] = proj(ref) == proj(graph)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nav", type=Path, required=True, help="source NAV container")
    ap.add_argument("--logical-offset", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--logical-size", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--cluster", type=Path, required=True, help="mutated cluster bytes")
    ap.add_argument("--out", type=Path, required=True, help="patched NAV output")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    report = patch(args.nav, args.logical_offset, args.logical_size,
                   args.cluster.read_bytes(), args.out,
                   verify=not args.no_verify)
    import json
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
