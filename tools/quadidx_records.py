#!/usr/bin/env python3
"""Parse TravelPilot DX QUADIDX.DAT into records and cell sections.

Record layout (docs/QUADIDX_FORMAT.md):
    name\0 | u16 sort | u16 kind | u8 flag | u24 cell_id | u32 ffff-field |
    u16 len | 6B f1 (lon,lat u24be) | 6B f2 | 02 u16 seq 09

Usage:
    python tools/quadidx_records.py QUADIDX.DAT                 # summary
    python tools/quadidx_records.py QUADIDX.DAT --name WROCLAW  # one name
    python tools/quadidx_records.py QUADIDX.DAT --settlements   # sort==1 list
"""
import argparse
import re
import struct

SCALE = 2 ** 24 / 360.0  # u24 big-endian coordinate scale
NAME_RE = re.compile(rb"[\x20-\x7e\xa0-\xff]{1,60}\x00")


def u24be(b):
    return (b[0] << 16) | (b[1] << 8) | b[2]


def parse(data):
    """Return list of record dicts in file order."""
    records = []
    for m in NAME_RE.finditer(data):
        o = m.end()
        if o + 30 > len(data):
            continue
        sort, kind = struct.unpack("<HH", data[o:o + 4])
        if data[o + 4] not in (1, 0x81):
            continue
        if data[o + 26] != 2 or data[o + 29] != 9:
            continue
        length = struct.unpack("<H", data[o + 12:o + 14])[0]
        if length > 0x8000:
            continue
        f1, f2 = data[o + 14:o + 20], data[o + 20:o + 26]
        records.append({
            "name": m.group()[:-1].decode("cp1252", "replace"),
            "off": m.start(),
            "end": o + 30,
            "sort": sort,
            "kind": kind,
            "cell_id": data[o + 5:o + 8].hex(),
            "len": length,
            "lon1": u24be(f1[:3]) / SCALE,
            "lat1": u24be(f1[3:]) / SCALE,
            "point": f2 == b"\0" * 6,
        })
    return records


def sections(records):
    """Split file-order records into contiguous cell sections."""
    out, cur = [], []
    for r in records:
        if cur and r["off"] != cur[-1]["end"]:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("quadidx")
    ap.add_argument("--name", help="show all records with this name")
    ap.add_argument("--settlements", action="store_true",
                    help="list settlement (sort==1) point records")
    args = ap.parse_args()
    data = open(args.quadidx, "rb").read()
    records = parse(data)
    print(f"records: {len(records)}")
    secs = sections(records)
    print(f"contiguous sections: {len(secs)} (top sizes "
          f"{sorted((len(s) for s in secs), reverse=True)[:8]})")
    if args.name:
        for r in records:
            if r["name"] == args.name:
                print(f"  @{r['off']:#08x} sort={r['sort']} kind={r['kind']:#06x} "
                      f"({r['lon1']:.4f},{r['lat1']:.4f})"
                      + (" point" if r["point"] else ""))
    if args.settlements:
        for r in records:
            if r["sort"] == 1 and r["point"]:
                print(f"{r['name']:40s} kind={r['kind']:#06x} "
                      f"({r['lon1']:.4f},{r['lat1']:.4f}) @{r['off']:#08x}")


if __name__ == "__main__":
    main()
