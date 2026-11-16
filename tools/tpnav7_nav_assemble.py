#!/usr/bin/env python3
"""Assemble a v7 NAV container: v6 typed layer + the catalog stack that
registers it with the firmware (donor NAV21315 conventions, see
analysis/fw_region/REPORT.md):

  per typed chain:  0x30d place-name block + 0x201 area catalog
                    -> (street container, fam 0x04), (names, fam 0x0d)
  global:           0x201 global catalog -> (0x403 stub, 0x308 stub, 0x30a stub)
                    0x604 region name pool -> records point at chain-0 geometry
                    0x104 city record (KRASNODAR) -> pool + geometry + sibling

Place names come from OSM place nodes (transliterated, " [RU]" suffix,
plus a "KRASNODAR KRAI [RU], <name>" cross-reference per place).

Usage:
  python tpnav7_nav_assemble.py --base NAV21315-krasnodar.DAT \
      --streets krasnodar-city-streets.json --osm osm-krasnodar-krai.json \
      --out NAV21315-krasnodar-v7.DAT
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
import tpnav7_catalogs as cat
from tpdx_coords import Datum

HEAD_SIZE = 320
TABLE_HEADER_STRUCT = struct.Struct("<IIII")
ENTRY_STRUCT = struct.Struct("<IHHIHH")

CITY = "KRASNODAR"
REGION = "KRASNODAR KRAI"


def split_geom_blocks(streets, budget=gen.GEOM_BUDGET):
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


def load_places(osm_json: Path, datum: Datum) -> list[dict]:
    """OSM place nodes -> [{"name","x","y"}] transliterated, [RU]-suffixed."""
    d = json.loads(osm_json.read_text(encoding="utf-8"))
    places = []
    for el in d.get("elements", []):
        if el.get("type") != "node":
            continue
        if "place" not in el.get("tags", {}) or "name" not in el["tags"]:
            continue
        x, y = datum.to_internal(el["lon"], el["lat"])
        nav = cat.translit(el["tags"]["name"])
        if not nav:
            continue
        places.append({"name": f"{nav} [RU]", "x": x, "y": y})
    return places


def chain_bbox(streets_group) -> tuple[float, float, float, float]:
    lons = [p[0] for _, chains in streets_group for ch in chains for p in ch]
    lats = [p[1] for _, chains in streets_group for ch in chains for p in ch]
    return min(lons), min(lats), max(lons), max(lats)


def assign_places(places, group_bboxes) -> list[list[dict]]:
    """Place -> chain whose bbox contains it (nearest bbox as fallback)."""
    out = [[] for _ in group_bboxes]

    def dist(b, p):
        dx = max(b[0] - p[0], 0, p[0] - b[2])
        dy = max(b[1] - p[1], 0, p[1] - b[3])
        return dx * dx + dy * dy

    # places carry internal x/y; convert back roughly for bbox test
    datum = Datum()
    for pl in places:
        lon, lat = datum.to_wgs84(pl["x"], pl["y"])
        best, best_d = 0, None
        for i, b in enumerate(group_bboxes):
            d = dist(b, (lon, lat))
            if best_d is None or d < best_d:
                best, best_d = i, d
        out[best].append(pl)
    return out


def assemble(base_nav: Path, streets_json: Path, osm_json: Path,
             out: Path) -> dict:
    nav = NavContainer(base_nav)
    blocks = []
    for e in nav.entries:
        decoded, _, _ = nav.read_block(e.logical_offset, e.logical_size)
        blocks.append(decoded)
    n_base = len(blocks)

    streets = gen.load_streets_json(streets_json)
    streets.sort(key=lambda s: s[0].upper())
    groups = gen.plan_groups(streets)

    chains = []
    for g in groups:
        sub_lists = split_geom_blocks(g)
        geoms = [bytearray(gen.build_geometry_block(sl)) for sl in sub_lists]
        cont = bytearray(gen.build_street_container(g))
        chains.append((g, geoms, cont))
        for gb in geoms:
            blocks.append(bytes(gb))
        blocks.append(bytes(cont))
    n_chains_end = len(blocks)

    # ---- places and per-chain names/catalogs ----
    datum = Datum()
    places = load_places(osm_json, datum)
    bboxes = [chain_bbox(g) for g, _, _ in chains]
    per_chain = assign_places(places, bboxes)

    def xref_entries(pls):
        entries = []
        for pl in sorted(pls, key=lambda p: p["name"]):
            entries.append(pl)
            entries.append({"name": f"{REGION} [RU], {pl['name'][:-6]}",
                            "xref": None})  # xref patched later (self ref)
        return entries

    # ---- pass 1: layout (sizes only) ----
    # block plan after chains: for each chain [names030d], then stubs,
    # 0604, 0104, then 0x201 area catalogs + global catalog
    n_chains = len(chains)

    # dry-run real blocks with zero offsets to get exact sizes
    names_blocks = []
    for pls in per_chain:
        entries = xref_entries(pls)
        for e in entries:
            if e.get("xref") is None and "x" not in e:
                e["xref"] = (0, 0)
        names_blocks.append(cat.build_030d(entries))
    stub403, stub308, stub30a = (cat.build_stub(0x403),
                                  cat.build_stub(0x308),
                                  cat.build_stub(0x30A))
    all_names = [p["name"] for p in places] + [CITY, f"{REGION} [RU]"]
    pool_block = cat.build_0604(sorted(set(all_names)), (0, 0))
    city_block = cat.build_0104(CITY, (0, 0), (0, 0), (0, 0))
    cat201_area = [cat.build_0201([(0, 0, 4), (0, 0, 0x0D)])
                   for _ in chains]
    cat201_global = cat.build_0201([(0, 0, 3), (0, 0, 8), (0, 0, 0x0A)])

    plan = (names_blocks + [stub403, stub308, stub30a, pool_block,
                             city_block] + cat201_area + [cat201_global])
    sizes = [len(b) for b in plan]

    # logical offsets of plan blocks (contiguous after the base blocks)
    plan_logical = []
    logical = HEAD_SIZE + sum(len(b) for b in blocks)
    for size in sizes:
        plan_logical.append(logical)
        logical += size

    # ---- pass 2: build catalog blocks with real logical offsets ----
    # chain blocks sit right after the base blocks: walk their logical offsets
    chain_meta = []
    logical = HEAD_SIZE + sum(len(b) for b in blocks[:n_base])
    for g, geoms, cont in chains:
        entry_slice = []
        for blob in list(geoms) + [cont]:
            entry_slice.append((logical, len(blob)))
            logical += len(blob)
        chain_meta.append(entry_slice)
    geom0_logical = chain_meta[0][0][0]
    geom0_size = len(chains[0][1][0])
    cont0_logical = chain_meta[0][-1][0]
    cont0_size = len(chains[0][2])

    rebuilt = []
    # names blocks: xref -> self (own logical offset + size)
    for pls, self_off, self_size in zip(
            per_chain, plan_logical[:n_chains], sizes[:n_chains]):
        entries_n = xref_entries(pls)
        for e in entries_n:
            if "x" not in e:
                e["xref"] = (self_off, self_size)
        rebuilt.append(cat.build_030d(entries_n))

    pool = cat.build_0604(sorted(set(all_names)),
                          (geom0_logical, geom0_size))
    city = cat.build_0104(CITY,
                          (plan_logical[n_chains + 3],
                           sizes[n_chains + 3]),
                          (geom0_logical, geom0_size),
                          (cont0_logical, cont0_size))
    for i, entry_slice in enumerate(chain_meta):
        cont_off, cont_size = entry_slice[-1][0], len(chains[i][2])
        nm_off, nm_size = plan_logical[i], sizes[i]
        rebuilt.append(cat.build_0201(
            [(cont_off, cont_size, 4), (nm_off, nm_size, 0x0D)]))
    rebuilt.append(cat.build_0201([
        (plan_logical[n_chains + 0], sizes[n_chains + 0], 3),
        (plan_logical[n_chains + 1], sizes[n_chains + 1], 8),
        (plan_logical[n_chains + 2], sizes[n_chains + 2], 0x0A)]))

    plan_final = (rebuilt[:n_chains] + [stub403, stub308, stub30a, pool,
                                        city]
                  + rebuilt[n_chains:])
    assert [len(b) for b in plan_final] == sizes, "size drift"

    # ---- payload with chain link patching (same as v6) ----
    all_blobs = blocks + plan_final
    blob_offsets = []
    off = 0
    for blob in all_blobs:
        blob_offsets.append(off)
        off += len(blob)
    payload = bytearray().join(bytearray(b) for b in all_blobs)

    chain_pos = n_base
    for i, (g, geoms, cont) in enumerate(chains):
        entry_slice = chain_meta[i]
        for j, gb in enumerate(geoms):
            base_p = blob_offsets[chain_pos + j]
            if j + 1 < len(geoms):
                tgt, tsz = entry_slice[j + 1][0], len(geoms[j + 1])
            else:
                tgt, tsz = entry_slice[-1][0], len(cont)
            struct.pack_into("<I", payload, base_p + 0x10, tgt)
            struct.pack_into("<H", payload, base_p + 0x14, tsz)
        cb = blob_offsets[chain_pos + len(geoms)]
        struct.pack_into("<I", payload, cb + 0x08, entry_slice[-2][0])
        struct.pack_into("<H", payload, cb + 0x0C, len(geoms[-1]))
        chain_pos += len(geoms) + 1

    n = len(all_blobs)
    table_offset = HEAD_SIZE + 16
    blocks_offset = table_offset + n * 16
    logical = HEAD_SIZE
    out_entries = []
    for blob, poff in zip(all_blobs, blob_offsets):
        size = len(blob)
        out_entries.append((logical, size, 0, blocks_offset + poff, size, 0))
        logical += size

    base_data = base_nav.read_bytes()
    out_data = bytearray(base_data[:HEAD_SIZE])
    struct.pack_into("<I", out_data, 4, HEAD_SIZE)
    out_data.extend(TABLE_HEADER_STRUCT.pack(n, table_offset, 0, 0))
    for e in out_entries:
        out_data.extend(ENTRY_STRUCT.pack(*e))
    out_data.extend(payload)
    out.write_bytes(bytes(out_data))

    return verify(out, nav_entries_expected=n, n_base=n_base,
                  plan_logical=plan_logical, sizes=sizes,
                  places=places, per_chain=per_chain, chains=chains)


def verify(out: Path, nav_entries_expected, n_base, plan_logical, sizes,
           places, per_chain, chains) -> dict:
    check = NavContainer(out)
    ok = len(check.entries) == nav_entries_expected
    for e in check.entries:
        blk, _, _ = check.read_block(e.logical_offset, e.logical_size)
    entry_at = {(e.logical_offset, e.logical_size): e.index
                for e in check.entries}

    report = {"entries": len(check.entries), "checks": {}}
    # all 0x201 catalogs parse and point at real entries
    n201, bad_targets = 0, 0
    for e in check.entries[n_base:]:
        blk, _, _ = check.read_block(e.logical_offset, e.logical_size)
        if len(blk) < 0x1A or struct.unpack_from("<H", blk, 2)[0] != 0x101:
            continue
        if struct.unpack_from("<H", blk, 0x0E)[0] == 0x201:
            n201 += 1
            for off, size, fam in cat.parse_0201(blk):
                if (off, size) not in entry_at:
                    bad_targets += 1
    report["checks"]["catalogs_0201"] = n201
    report["checks"]["bad_targets"] = bad_targets
    # names blocks re-parse and match input
    n_names, names_ok = 0, True
    for pls, off, size in zip(per_chain, plan_logical[:len(per_chain)],
                              sizes[:len(per_chain)]):
        blk, _, _ = check.read_block(off, size)
        parsed = cat.parse_030d(blk)
        want = {p["name"] for p in pls}
        got = {p["name"] for p in parsed if "x" in p}
        if want != got:
            names_ok = False
        for p in parsed:
            if "x" in p:
                src = next(q for q in pls if q["name"] == p["name"])
                if (p["x"], p["y"]) != (src["x"], src["y"]):
                    names_ok = False
        n_names += 1
    report["checks"]["names_blocks"] = n_names
    report["checks"]["names_roundtrip"] = names_ok
    # city record
    city_idx = plan_logical[len(per_chain) + 4]
    cblk, _, _ = check.read_block(city_idx,
                                  sizes[len(per_chain) + 4])
    report["checks"]["city_name_ok"] = CITY.encode() in cblk
    report["checks"]["pool_ref_ok"] = struct.unpack_from(
        "<I", cblk, 0x10)[0] in {e.logical_offset for e in check.entries}
    report["checks"]["geom_ref_ok"] = struct.unpack_from(
        "<I", cblk, 0x39 + 1)[0] in {e.logical_offset
                                     for e in check.entries} \
        if len(cblk) > 0x40 else False
    report["checks"]["all_ok"] = (ok and bad_targets == 0 and names_ok
                                  and report["checks"]["city_name_ok"]
                                  and report["checks"]["pool_ref_ok"])
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--streets", type=Path, required=True)
    ap.add_argument("--osm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = assemble(args.base, args.streets, args.osm, args.out)
    print(json.dumps(report, indent=1))
    print("RESULT:", "ALL OK" if report["checks"]["all_ok"] else "FAIL")


if __name__ == "__main__":
    main()
