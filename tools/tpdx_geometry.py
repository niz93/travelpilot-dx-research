#!/usr/bin/env python3
"""Decode geometry blocks (type 0x001a) of TravelPilot DX NAV2xxxx.DAT files.

Reverse-engineered layout (Czech/Poland 2010-2011 NAV24019.DAT, block
0xc6870, Warsaw test area). Decoded and verified:

Block header (little-endian):
  u16 @0x00  declared size (== logical size)
  u16 @0x02  0x0101 ("back_sub")
  u16 @0x04  0x001a for geometry blocks (0x0000 for the street/tiny container
             block that terminates each region chain)
  u16 @0x06  0x0001
  u32 @0x08  0
  u16 @0x0e  0x0304 (code)
  u32 @0x10  logical offset of a sibling block (region chain link)
  u16 @0x14  size of that sibling block
  ...        further params @0x16..0x3f (partially understood)

Segment catalog: 10-byte records starting at 0x40, ordered by offset:
  u16  offset of segment inside the block
  u16  item count (number of coordinate pairs / link records)
  u32  key (0 for pure link segments; otherwise a stable id that also appears
       in a sorted key table in the block tail region)
  u16  idx (ordinal into an external table, roughly 0x7744-based)

Segment record stream:
  preamble  bytes 0c 00 0c 00
  then a sequence of:
    - coordinate pair: u32 lon, u32 lat (degrees = value * 360 / 2**32);
      first pair of a segment is absolute, subsequent pairs observed absolute
      as well (Warsaw test area; deltas not observed yet)
    - short node attribute: u8 type (0x13..0x1c observed), 0x00, u16 value
    - street-list attribute (partially decoded):
        u16 ref (offset-ish into the region's street/tiny container block),
        u8  0x01, u16 n, n bytes payload (starts with a count byte followed
        by that many u8 street-name indices, 0x80|id encoding suspected)
    - cross-block link: 0c 00 0a 00, u32 block logical offset,
      u16 block size, u16 sub-offset (node continues in another block)
    - segment end: 01 00

Status: pair/link/short-attr decoding is solid; street-list payload layout is
best-effort (resynchronisation by coordinate plausibility may skip bytes).
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from tpnav2_container import NavContainer

GEOM_TYPE = 0x001A
CODE = 0x0304


def plausible(lon: float, lat: float, lon_range, lat_range) -> bool:
    return lon_range[0] < lon < lon_range[1] and lat_range[0] < lat < lat_range[1]


def catalog(blk: bytes):
    """Yield (seg_off, count, key, idx) records until offsets break order."""
    recs = []
    for i in range(0x4000):
        o = 0x40 + i * 10
        if o + 10 > len(blk):
            break
        off, cnt, key, idx = struct.unpack_from("<HHIH", blk, o)
        if not (0x40 <= off <= len(blk)):
            break
        if recs and off < recs[-1][0]:
            break
        recs.append((off, cnt, key, idx))
    return recs


def parse_segment(blk: bytes, start: int, end: int, lon_range, lat_range,
                  expected_pairs=None):
    """Decode one segment record stream.

    ``expected_pairs`` is the catalog ``cnt`` field: number of coordinate
    pairs in this segment. When given, exactly that many pairs are read after
    the preamble, then an ENDMARK (01 00) is expected. This avoids the classic
    false-ENDMARK desync: a lat around 45.0000-45.0039 encodes as
    u32 0x20040001..0x2004FFFF whose LE bytes start with 01 00, which the
    bare marker scan would misread as the segment end and desynchronise.
    """
    cur = start
    pairs, attrs, links, skipped = [], [], [], []
    if blk[cur:cur + 4] == b"\x0c\x00\x0c\x00":
        cur += 4
    if expected_pairs:
        for _ in range(int(expected_pairs)):
            if cur + 8 > end:
                skipped.append(cur)
                break
            lo, la = struct.unpack_from("<II", blk, cur)
            lon, lat = lo * 360 / 2**32, la * 360 / 2**32
            if not plausible(lon, lat, lon_range, lat_range):
                skipped.append(cur)
                break
            pairs.append((round(lon, 6), round(lat, 6)))
            cur += 8
        if blk[cur:cur + 2] != b"\x01\x00":
            skipped.append(cur)
        return pairs, attrs, links, skipped, cur + 2
    while cur < end - 1:
        two = blk[cur:cur + 2]
        if two == b"\x01\x00":
            cur += 2
            break
        if blk[cur:cur + 4] == b"\x0c\x00\x0a\x00":
            boff, = struct.unpack_from("<I", blk, cur + 4)
            bsz, sub = struct.unpack_from("<HH", blk, cur + 8)
            links.append({"block": boff, "size": bsz, "sub": sub})
            cur += 12
            continue
        if (blk[cur + 1] == 0x00 and 0x13 <= blk[cur] <= 0x1C):
            val, = struct.unpack_from("<H", blk, cur + 2)
            attrs.append({"kind": "short", "type": blk[cur], "value": val})
            cur += 4
            continue
        if blk[cur + 2] == 0x01 and blk[cur + 1] != 0x00:
            ref, = struct.unpack_from("<H", blk, cur)
            n, = struct.unpack_from("<H", blk, cur + 3)
            payload = blk[cur + 5:cur + 5 + n]
            attrs.append({"kind": "streets", "ref": ref,
                          "payload": payload.hex()})
            cur += 5 + n
            continue
        if cur + 8 <= end:
            lo, la = struct.unpack_from("<II", blk, cur)
            lon, lat = lo * 360 / 2**32, la * 360 / 2**32
            if plausible(lon, lat, lon_range, lat_range):
                pairs.append((round(lon, 6), round(lat, 6)))
                cur += 8
                continue
        skipped.append(cur)
        cur += 2  # resync
    return pairs, attrs, links, skipped, cur


def block_header(blk: bytes) -> dict:
    return {
        "declared": struct.unpack_from("<H", blk, 0)[0],
        "back_sub": hex(struct.unpack_from("<H", blk, 2)[0]),
        "type": hex(struct.unpack_from("<H", blk, 4)[0]),
        "code": hex(struct.unpack_from("<H", blk, 0x0E)[0]),
        "sibling": hex(struct.unpack_from("<I", blk, 0x10)[0]),
        "sibling_size": struct.unpack_from("<H", blk, 0x14)[0],
    }


def dump_geometry(nav: NavContainer, logical_offset: int, logical_size: int,
                  lon_range=(10, 60), lat_range=(40, 72)) -> dict:
    blk, entry, _ = nav.read_block(logical_offset, logical_size)
    recs = catalog(blk)
    segments = []
    for i, (off, cnt, key, idx) in enumerate(recs):
        end = recs[i + 1][0] if i + 1 < len(recs) else len(blk)
        pairs, attrs, links, skipped, stop = parse_segment(
            blk, off, end, lon_range, lat_range)
        segments.append({
            "off": off, "count": cnt, "key": key, "idx": idx,
            "pairs": pairs, "attrs": attrs, "links": links,
            "skipped": len(skipped),
        })
    all_pairs = [p for s in segments for p in s["pairs"]]
    bbox = None
    if all_pairs:
        lons = [p[0] for p in all_pairs]
        lats = [p[1] for p in all_pairs]
        bbox = [min(lons), min(lats), max(lons), max(lats)]
    return {
        "entry_index": entry.index,
        "header": block_header(blk),
        "segments": len(segments),
        "pairs": len(all_pairs),
        "links": sum(len(s["links"]) for s in segments),
        "skipped_resyncs": sum(s["skipped"] for s in segments),
        "bbox": bbox,
        "detail": segments,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nav_file", type=Path)
    ap.add_argument("--logical-offset", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--logical-size", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--lon-range", default="10,60")
    ap.add_argument("--lat-range", default="40,72")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    nav = NavContainer(args.nav_file)
    lon_range = tuple(float(x) for x in args.lon_range.split(","))
    lat_range = tuple(float(x) for x in args.lat_range.split(","))
    result = dump_geometry(nav, args.logical_offset, args.logical_size,
                           lon_range, lat_range)
    detail = result.pop("detail")
    print(json.dumps(result, indent=2))
    for s in detail[: int(args.segments_preview)] if False else detail[:5]:
        print(json.dumps(s, ensure_ascii=False))
    if args.json:
        result["detail"] = detail
        args.json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
