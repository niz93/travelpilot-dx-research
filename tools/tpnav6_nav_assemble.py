#!/usr/bin/env python3
"""Assemble a v6 NAV container: TPNAV2 clusters + typed layer (region
chains of geometry blocks + street containers) appended to an existing
generated NAV.

Each region chain mirrors the donor: 1..N geometry blocks (sibling-linked,
last sibling -> container) + one street container terminator whose back-link
(@0x08/@0x0c) points at the LAST geometry block of its chain. Chains come
from plan_groups() (alphabetical greedy fit into size budgets).

Logical and physical images are both contiguous (tpnav2_nav_build
conventions); head [0..320) copied from the base NAV.

Usage:
  python tpnav6_nav_assemble.py --base NAV21315-krasnodar.DAT \
      --streets krasnodar-city-streets.json --out NAV21315-krasnodar-v6full.DAT
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_container import NavContainer
import tpnav6_typed_build as gen

HEAD_SIZE = 320
TABLE_HEADER_STRUCT = struct.Struct("<IIII")
ENTRY_STRUCT = struct.Struct("<IHHIHH")


def split_geom_blocks(streets, budget=gen.GEOM_BUDGET):
    """Split one group's streets into geometry-block sub-lists, each
    estimated to fit the budget. A street never spans sub-blocks."""
    blocks, cur, size = [], [], 0.0
    for st in streets:
        eg = gen.est_geom_bytes(st)
        if cur and size + eg > budget:
            blocks.append(cur)
            cur, size = [], 0.0
        cur.append(st)
        size += eg
    if cur:
        blocks.append(cur)
    return blocks


def assemble(base_nav: Path, streets_json: Path, out: Path) -> dict:
    nav = NavContainer(base_nav)
    blocks = []
    for e in nav.entries:
        decoded, _, _ = nav.read_block(e.logical_offset, e.logical_size)
        blocks.append(decoded)
    n_base = len(blocks)

    streets = gen.load_streets_json(streets_json)
    streets.sort(key=lambda s: s[0].upper())
    groups = gen.plan_groups(streets)

    # build chains unpatched, remember structure
    chains = []           # (group_streets, [geom bytearrays], container)
    for g in groups:
        sub_lists = split_geom_blocks(g)
        geoms = [bytearray(gen.build_geometry_block(sl))
                 for sl in sub_lists]
        cont = bytearray(gen.build_street_container(g))
        chains.append((g, geoms, cont))
        for gb in geoms:
            blocks.append(bytes(gb))
        blocks.append(bytes(cont))

    n = len(blocks)
    table_offset = HEAD_SIZE + 16
    blocks_offset = table_offset + n * 16

    logical = HEAD_SIZE
    physical = blocks_offset
    entries = []
    payload = bytearray()
    for blob in blocks:
        size = len(blob)
        entries.append((logical, size, 0, physical, size, 0))
        payload.extend(blob)
        logical += size
        physical += size

    # second pass: patch chain links with real offsets (physical in payload)
    payload = bytearray(payload)
    chain_reports = []
    pos = n_base
    for g, geoms, cont in chains:
        entry_slice = entries[pos:pos + len(geoms) + 1]
        pos += len(geoms) + 1
        for i, gb in enumerate(geoms):
            base_p = entry_slice[i][3] - blocks_offset
            if i + 1 < len(geoms):
                tgt, tsz = entry_slice[i + 1][0], len(geoms[i + 1])
            else:
                tgt, tsz = entry_slice[-1][0], len(cont)
            struct.pack_into("<I", payload, base_p + 0x10, tgt)
            struct.pack_into("<H", payload, base_p + 0x14, tsz)
        cbase_p = entry_slice[-1][3] - blocks_offset
        struct.pack_into("<I", payload, cbase_p + 0x08,
                         entry_slice[-2][0])
        struct.pack_into("<H", payload, cbase_p + 0x0C, len(geoms[-1]))
        chain_reports.append({
            "streets": len(g),
            "geom_blocks": len(geoms),
            "geom_size": sum(len(x) for x in geoms),
            "cont_size": len(cont),
            "geom_logical": entry_slice[0][0],
            "cont_logical": entry_slice[-1][0],
        })

    base_data = base_nav.read_bytes()
    out_data = bytearray(base_data[:HEAD_SIZE])
    struct.pack_into("<I", out_data, 4, HEAD_SIZE)
    out_data.extend(TABLE_HEADER_STRUCT.pack(n, table_offset, 0, 0))
    for e in entries:
        out_data.extend(ENTRY_STRUCT.pack(*e))
    out_data.extend(payload)
    out.write_bytes(bytes(out_data))

    # --- verification ---
    check = NavContainer(out)
    ok = len(check.entries) == n
    for i, e in enumerate(check.entries):
        decoded, _, _ = check.read_block(e.logical_offset, e.logical_size)
        want = bytes(payload[e.physical_offset - blocks_offset:
                           e.physical_offset - blocks_offset + e.physical_size])
        if decoded != want:
            ok = False
            print(f"MISMATCH entry {i}")

    # verify one chain's links from the written file
    first = chain_reports[0]
    g0, _, _ = check.read_block(first["geom_logical"],
                                chain_reports[0]["geom_size"])
    sib, = struct.unpack_from("<I", g0, 0x10)
    c0, _, _ = check.read_block(first["cont_logical"],
                                first["cont_size"])
    back, = struct.unpack_from("<I", c0, 0x08)
    back_ok = back == first["geom_logical"] + sum(
        len(chains[0][1][i]) for i in range(len(chains[0][1]) - 1))         if len(chains[0][1]) > 1 else back == first["geom_logical"]
    chain_ok = sib == first["cont_logical"] and back_ok

    parsed = gen.parse_container(c0)
    report = {
        "base_entries": n_base,
        "typed_blocks": n - n_base,
        "chains": len(chains),
        "total_entries": n,
        "streets": len(streets),
        "file_size": len(out_data),
        "roundtrip_identical": ok,
        "chain0_links_ok": chain_ok,
        "chain0_streets": len(parsed["records"]),
        "chain0_first_names": [r["name"] for r in parsed["records"][:5]],
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", type=Path, required=True,
                    help="existing generated NAV container")
    ap.add_argument("--streets", type=Path, required=True,
                    help="streets JSON (fixture or city chains format)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = assemble(args.base, args.streets, args.out)
    print(json.dumps(report, indent=1))
    print("RESULT:", "ALL OK" if report["roundtrip_identical"]
          and report["chain0_links_ok"] else "FAIL")


if __name__ == "__main__":
    main()
