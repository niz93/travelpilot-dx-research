#!/usr/bin/env python3
"""Build TravelPilot DX NAV typed-layer blocks (v6 experimental format).

Generates region chains from OSM-like street polylines, following the donor
NAV24019.DAT Warsaw chain (decoded 2026-11-16). A street is a list of
polylines ("chains", e.g. disconnected parts); chains never merge.

GEOMETRY BLOCK (type 0x001a, code 0x0304) -- detailed street geometry
  header 0x40 bytes:
    u16 @0x00 declared size, u16 @0x02 0x0101, u16 @0x04 0x001a,
    u16 @0x06 1, u32 @0x08 0, u16 @0x0c 0, u16 @0x0e 0x0304,
    u32 @0x10 sibling logical offset, u16 @0x14 sibling size,
    u16 @0x16 0x20, u16 @0x18 nrecs+3, u16 @0x1a 6, u16 @0x1c 9,
    u16 @0x20 end of last catalogued segment, u16 @0x22 idx field of the
    last catalog record, u16 @0x2e 1.
  catalog @0x40: 10B <u16 seg_off, u16 cnt(pairs), u32 key=0, u16 idx>;
    one record per segment, street segments consecutive.
  segment stream right after catalog:
    segment = 0c 00 0c 00 + n*(u32 lon, u32 lat) + 01 00
    (lon = deg*2**32/360; minimal grammar: no street-lists, no glue)

STREET CONTAINER (type 0x0000, code 0x0304) -- chain terminator with names
  header 0x1a bytes: declared, 0x0101, 0, 0, u32@0x08 back-link to the
    LAST geometry block of the chain, u16@0x0c its size, 0x0304, sibling=0,
    u16@0x16 0x1a (header size), u16@0x18 record count.
  records @0x1a, 10B, alphabetical: <u16 name_off, u16 ref1, u8 cnt, u8 0,
    u16 f3=0, u8 n2=0, u8 0>; ref1 = offset of the street's summary
    geometry (single segment, all chains' samples concatenated, <=255 pts).
  geometry stream after records (per street, record order), then the string
  table (NUL-terminated cp1252 names, name_off absolute).

Chain planner: plan_groups() splits the sorted street list into groups so
that each group fits one container and each group's geometry splits into
blocks <= GEOM_BUDGET bytes (donor-faithful: several geometry blocks per
chain, one terminating container per chain).

Open risks: see analysis/b5-v6-nav-recipe.md (no street-lists/glue/tail,
unknown header fields zeroed; HU acceptance pending).
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

CODE = 0x0304
GEOM_HDR = 0x40
CONT_HDR = 0x1A
SEG_MAX_POINTS = 32
SUMMARY_MAX_POINTS = 255
GEOM_BUDGET = 58000
CONT_BUDGET = 58000
PREAMBLE = b"\x0c\x00\x0c\x00"
ENDMARK = b"\x01\x00"

# empirical from the 3-street fixture: pairs*8.6 + recs*10 + hdr
PAIR_BYTES = 8.6
REC_BYTES = 10


def deg2u32(deg: float) -> int:
    return int(round(deg * 2**32 / 360)) & 0xFFFFFFFF


def chunks(points, size=SEG_MAX_POINTS):
    """Split one polyline into segments of <=size points, consecutive
    chunks sharing one endpoint so the polyline stays connected."""
    if len(points) <= size:
        yield points
        return
    i = 0
    while i < len(points) - 1:
        yield points[i:i + size]
        i += size - 1


def summary(points, max_pts=SUMMARY_MAX_POINTS):
    if len(points) <= max_pts:
        return list(points)
    step = (len(points) - 1) / (max_pts - 1)
    return [points[int(round(i * step))] for i in range(max_pts)]


def street_summary(chains):
    """Concatenate per-chain samples, cap total at SUMMARY_MAX_POINTS."""
    total = [pt for ch in chains for pt in ch]
    return summary(total, SUMMARY_MAX_POINTS)


def _segment_bytes(points) -> bytes:
    out = bytearray(PREAMBLE)
    for lon, lat in points:
        out += struct.pack("<II", deg2u32(lon), deg2u32(lat))
    out += ENDMARK
    return bytes(out)


def street_points(street):
    """street = (name, [chain,...]) -> flat point count."""
    return sum(len(c) for c in street[1])


def est_geom_bytes(street) -> float:
    pts = street_points(street)
    nseg = sum(max(1, (len(c) - 1 + SEG_MAX_POINTS - 2) // (SEG_MAX_POINTS - 1))
               for c in street[1]) if street[1] else 0
    return pts * PAIR_BYTES + nseg * (REC_BYTES + 6)


def est_cont_bytes(street, nav_name) -> float:
    return (10 + len(street[1] and street_summary(street[1]) or []) * 8.6
            + len(nav_name) + 8)


def plan_groups(streets, geom_budget=GEOM_BUDGET, cont_budget=CONT_BUDGET):
    """Split (name, chains) streets -- already NAV-sorted by caller -- into
    groups; each group becomes one chain (geometry blocks + container).
    A street never spans groups."""
    groups, cur, gsize, csize = [], [], 0.0, CONT_HDR
    for name, chains in streets:
        eg = est_geom_bytes((name, chains))
        ec = est_cont_bytes((name, chains), name)
        if cur and (gsize + eg > geom_budget or csize + ec > cont_budget):
            groups.append(cur)
            cur, gsize, csize = [], 0.0, CONT_HDR
        cur.append((name, chains))
        gsize += eg
        csize += ec
    if cur:
        groups.append(cur)
    return groups


def build_geometry_block(streets, sibling_off=0, sibling_size=0) -> bytes:
    """streets: list of (name, [chain,...]) in catalog order."""
    segs = []           # (seg_bytes, n_points)
    for name, chains in streets:
        for ch in chains:
            for c in chunks(ch):
                segs.append((_segment_bytes(c), len(c)))
    nrecs = len(segs)

    stream_off = GEOM_HDR + nrecs * REC_BYTES
    offs = []
    cur = stream_off
    for sb, _ in segs:
        offs.append(cur)
        cur += len(sb)
    total = cur
    if total > 0xFFFF:
        raise ValueError(f"geometry block too large: {total}")

    hdr = bytearray(GEOM_HDR)
    struct.pack_into("<H", hdr, 0x00, total)
    struct.pack_into("<H", hdr, 0x02, 0x0101)
    struct.pack_into("<H", hdr, 0x04, 0x001A)
    struct.pack_into("<H", hdr, 0x06, 0x0001)
    struct.pack_into("<H", hdr, 0x0E, CODE)
    struct.pack_into("<I", hdr, 0x10, sibling_off)
    struct.pack_into("<H", hdr, 0x14, sibling_size)
    struct.pack_into("<H", hdr, 0x16, 0x0020)
    struct.pack_into("<H", hdr, 0x18, nrecs + 3)
    struct.pack_into("<H", hdr, 0x1A, 0x0006)
    struct.pack_into("<H", hdr, 0x1C, 0x0009)
    struct.pack_into("<H", hdr, 0x20, offs[-1] + len(segs[-1][0])
                     if segs else 0)
    struct.pack_into("<H", hdr, 0x22, 0x40 + (nrecs - 1) * 10 + 8
                     if nrecs else 0)
    struct.pack_into("<H", hdr, 0x2E, 1)

    cat = bytearray()
    for i, (off, (sb, np_)) in enumerate(zip(offs, segs)):
        idx = 0x0100 + (i * 37) % 0x9F00          # deterministic unique-ish
        cat += struct.pack("<HHIH", off, np_, 0, idx)
    return bytes(hdr) + bytes(cat) + b"".join(sb for sb, _ in segs)


def build_street_container(streets, geom_off=0, geom_size=0,
                         name_fn=None) -> bytes:
    """streets: list of (name, [chain,...]); sorted alphabetically by the
    NAV (cp1252 upper) name. name_fn maps source name -> NAV name."""
    name_fn = name_fn or (lambda s: s)
    nav_names = []
    for name, chains in streets:
        nav = name_fn(name).upper().encode("cp1252", "replace")
        nav_names.append((nav, street_summary(chains)))
    nav_names.sort(key=lambda t: t[0])

    nrecs = len(nav_names)
    geo_off = CONT_HDR + nrecs * 10

    geo = bytearray()
    recs = []           # (nav_name, ref1, cnt)
    for nav, pts in nav_names:
        sb = _segment_bytes(pts)
        recs.append((nav, geo_off + len(geo), len(pts)))
        geo += sb
    str_start = geo_off + len(geo)

    strtab = bytearray()
    out_recs = []
    for nav, ref1, cnt in recs:
        name_off = str_start + len(strtab)
        strtab += nav + b"\x00"
        out_recs.append(struct.pack("<HHBBHBB", name_off, ref1, cnt,
                                    0, 0, 0, 0))
    total = str_start + len(strtab)
    if total > 0xFFFF:
        raise ValueError(f"container block too large: {total}")

    hdr = bytearray(CONT_HDR)
    struct.pack_into("<H", hdr, 0x00, total)
    struct.pack_into("<H", hdr, 0x02, 0x0101)
    struct.pack_into("<H", hdr, 0x04, 0x0000)
    struct.pack_into("<H", hdr, 0x06, 0x0000)
    struct.pack_into("<I", hdr, 0x08, geom_off)
    struct.pack_into("<H", hdr, 0x0C, geom_size)
    struct.pack_into("<H", hdr, 0x0E, CODE)
    struct.pack_into("<H", hdr, 0x16, CONT_HDR)
    struct.pack_into("<H", hdr, 0x18, nrecs)
    return bytes(hdr) + b"".join(out_recs) + bytes(geo) + bytes(strtab)


def parse_container(blk: bytes) -> dict:
    """Parse a street container block back (roundtrip helper)."""
    declared, = struct.unpack_from("<H", blk, 0)
    nrecs, = struct.unpack_from("<H", blk, 0x18)
    recs = []
    for i in range(nrecs):
        o = CONT_HDR + i * 10
        name_off, ref1, cnt, b, f3, n2, b2 = struct.unpack_from(
            "<HHBBHBB", blk, o)
        end = blk.index(0, name_off)
        name = blk[name_off:end].decode("cp1252")
        pts = []
        p = ref1
        if blk[p:p + 4] == PREAMBLE:
            p += 4
            for _ in range(cnt):
                lon, lat = struct.unpack_from("<II", blk, p)
                pts.append((lon * 360 / 2**32, lat * 360 / 2**32))
                p += 8
        recs.append({"name": name, "ref1": ref1, "cnt": cnt,
                     "f3": f3, "n2": n2, "points": pts})
    return {"declared": declared, "records": recs}


def load_streets_json(path):
    """Accepts both fixture formats:
    old: {name: {"geom": [{"lon","lat"}...]}}
    new: {name: {"chains": [[[lon,lat]...],...]}}"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    streets = []
    for k, v in data.items():
        if "chains" in v:
            chains = [[(float(a), float(b)) for a, b in ch]
                      for ch in v["chains"]]
        else:
            chains = [[(float(p["lon"]), float(p["lat"]))
                       for p in v["geom"]]]
        streets.append((k, chains))
    return streets


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("streets_json", type=Path)
    ap.add_argument("out_prefix", type=Path)
    ap.add_argument("--sibling-off", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--sibling-size", type=lambda v: int(v, 0), default=0)
    args = ap.parse_args()

    streets = load_streets_json(args.streets_json)
    geom = build_geometry_block(streets, args.sibling_off,
                                args.sibling_size)
    cont = build_street_container(streets, args.sibling_off or 0,
                                  len(geom))
    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.out_prefix.with_suffix(".geom.bin").write_bytes(geom)
    args.out_prefix.with_suffix(".cont.bin").write_bytes(cont)
    report = {
        "streets": len(streets),
        "points": sum(street_points(s) for s in streets),
        "geom_size": len(geom),
        "cont_size": len(cont),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
