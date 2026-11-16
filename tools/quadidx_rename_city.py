#!/usr/bin/env python3
"""In-place rename of settlement records in QUADIDX.DAT (research hack).

Renames settlement (sort==1, point) records whose current name has exactly the
same length as the target name to the target name and moves their coordinate
to (lon, lat). The patch is strictly in-place: file size, record offsets and all
indexes stay valid. Useful to test how the head unit builds its city list —
see docs/QUADIDX_FORMAT.md ("City list — open") for the 2026-11 finding that
this alone is NOT sufficient to add a city to "Ortsliste".

Usage:
    python tools/quadidx_rename_city.py QUADIDX.DAT KRASNODAR 38.9765 45.0355 \
        -o QUADIDX-patched.bin --bbox 12,48.5,24,54.5
"""
import argparse
import json
import struct

from quadidx_records import NAME_RE, SCALE, parse, u24be


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("quadidx")
    ap.add_argument("new_name", help="ASCII, <= 60 chars; matched donors must "
                                   "have exactly this name length")
    ap.add_argument("lon", type=float)
    ap.add_argument("lat", type=float)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--bbox", default="12,48.5,24,54.5",
                    help="lon0,lat0,lon1,lat1 donor selection window")
    args = ap.parse_args()

    data = bytearray(open(args.quadidx, "rb").read())
    lon0, lat0, lon1, lat1 = (float(x) for x in args.bbox.split(","))
    new_name = args.new_name.encode("ascii")
    assert len(new_name) <= 60
    x = int(round(args.lon * SCALE))
    y = int(round(args.lat * SCALE))
    assert 0 <= x < 2 ** 24 and 0 <= y < 2 ** 24

    patched = []
    for m in NAME_RE.finditer(bytes(data)):
        o = m.end()
        if o + 30 > len(data):
            continue
        sort, _kind = struct.unpack("<HH", data[o:o + 4])
        if sort != 1 or data[o + 4] not in (1, 0x81):
            continue
        if data[o + 26] != 2 or data[o + 29] != 9:
            continue
        if bytes(data[o + 20:o + 26]) != b"\0" * 6:
            continue
        old = m.group()[:-1].decode("cp1252", "replace")
        if len(old) != len(new_name):
            continue
        lon, lat = u24be(data[o + 14:o + 17]) / SCALE, u24be(data[o + 17:o + 20]) / SCALE
        if not (lon0 < lon < lon1 and lat0 < lat < lat1):
            continue
        data[m.start():m.start() + len(new_name) + 1] = new_name + b"\0"
        data[o + 14:o + 17] = bytes([(x >> 16) & 255, (x >> 8) & 255, x & 255])
        data[o + 17:o + 20] = bytes([(y >> 16) & 255, (y >> 8) & 255, y & 255])
        patched.append({"off": m.start(), "old": old})

    assert patched, "no matching donor records found"
    open(args.out, "wb").write(bytes(data))
    print(f"patched {len(patched)} records -> {args.out}")
    print(json.dumps(patched, indent=1))


if __name__ == "__main__":
    main()
