#!/usr/bin/env python3
"""Build a NAV remap container from scratch out of generated clusters.

Mirrors the observed real-container conventions (czech_poland_2010_2011
NAV20001.DAT):
  * file head [0..320) copied verbatim from the real container (primary
    header + the unknown 294-byte region), table header at offset 320;
  * logical image is contiguous: entry i+1 logical_offset =
    entry i logical_offset + logical_size, starting at 320;
  * table entries 16B <IHHIHH>, field06 = 0;
  * physical blocks packed right after the table, compression_flag = 0,
    physical_size = logical_size.

The unknown part — how the disc-level index (quadidx/CAT) maps geography
to logical offsets — is NOT solved here; this container is validated with
our own reader and is ready for a head-unit probe.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_container import NavContainer
from tpnav2_graph import parse_graph

HEAD_SIZE = 320          # primary header (26B) + unknown region, copied verbatim
TABLE_HEADER_STRUCT = struct.Struct("<IIII")
ENTRY_STRUCT = struct.Struct("<IHHIHH")


def build(cluster_files: list[Path], template: Path, out: Path) -> dict:
    template_data = template.read_bytes()
    if len(template_data) < HEAD_SIZE:
        raise ValueError("template container shorter than the 320-byte head")

    blobs = [f.read_bytes() for f in cluster_files]
    n = len(blobs)
    table_offset = HEAD_SIZE + 16
    blocks_offset = table_offset + n * 16

    logical = HEAD_SIZE
    physical = blocks_offset
    entries = []
    blocks = bytearray()
    for blob in blobs:
        size = len(blob)
        entries.append((logical, size, 0, physical, size, 0))
        blocks.extend(blob)
        logical += size
        physical += size

    data = bytearray(template_data[:HEAD_SIZE])
    struct.pack_into("<I", data, 4, HEAD_SIZE)  # table_header_offset
    data.extend(TABLE_HEADER_STRUCT.pack(n, table_offset, 0, 0))
    for e in entries:
        data.extend(ENTRY_STRUCT.pack(*e))
    data.extend(blocks)
    out.write_bytes(bytes(data))

    # --- full verification pass ---
    check = NavContainer(out)
    ok = True
    total_conflicts = 0
    max_size = 0
    for f, blob in zip(cluster_files, blobs):
        g = parse_graph(blob, f.name)
        v = g["validation"]
        total_conflicts += len(v["endpoint_conflicts"])
        max_size = max(max_size, len(blob))
    for i, blob in enumerate(blobs):
        e = check.entries[i]
        decoded, _, _ = check.read_block(e.logical_offset, e.logical_size)
        if decoded != blob:
            ok = False
            print(f"MISMATCH entry {i} ({cluster_files[i].name})")
    report = {
        "clusters": n,
        "file_size": len(data),
        "table_offset": table_offset,
        "blocks_offset": blocks_offset,
        "logical_span": logical,
        "max_cluster_size": max_size,
        "roundtrip_identical": ok,
        "total_endpoint_conflicts": total_conflicts,
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clusters", type=Path, required=True,
                    help="directory of gen-*.bin cluster files")
    ap.add_argument("--template", type=Path,
                    default=Path("extracted/czech_poland_2010_2011/NAV20001.DAT"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    files = sorted(args.clusters.glob("gen-*.bin"))
    if not files:
        raise SystemExit(f"no gen-*.bin clusters under {args.clusters}")
    report = build(files, args.template, args.out)
    print(json.dumps(report, indent=1))
    print("RESULT:", "ALL OK" if report["roundtrip_identical"]
          and report["total_endpoint_conflicts"] == 0 else "FAIL")


if __name__ == "__main__":
    main()
