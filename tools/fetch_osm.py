#!/usr/bin/env python3
"""Download a drivable-road OSM region via Overpass (kumi mirror)."""
import sys
import urllib.request
import urllib.parse
from pathlib import Path

bbox = sys.argv[1] if len(sys.argv) > 1 else "44.97,38.80,45.12,39.15"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "analysis/osm-krasnodar.json")

query = f'[out:json][timeout:1500];way["highway"]({bbox});out geom;'
data = urllib.parse.urlencode({"data": query}).encode()
req = urllib.request.Request(
    "https://overpass.kumi.systems/api/interpreter",
    data=data,
    headers={
        "User-Agent": "tpdx-research/1.0 (navigation map research)",
        "Content-Type": "application/x-www-form-urlencoded",
    },
)
with urllib.request.urlopen(req, timeout=1500) as resp:
    payload = resp.read()
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(payload)
print(f"saved {out} ({len(payload)/1e6:.1f} MB)")
