#!/usr/bin/env python3
"""Render generated grid clusters over the source OSM geometry (WGS84)."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpdx_coords import Datum
from tpnav2_graph import parse_graph
from tpdx_osm_grid import DRIVABLE

osm_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("analysis/osm-krasnodar.json")
grid_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("analysis/tpdx-grid-krasnodar")
out_png = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("analysis/grid-check-krasnodar.png")

datum = Datum()

# --- OSM source geometry (light gray) ---
d = json.loads(osm_path.read_text(encoding="utf-8"))
osm_lines = []
for el in d.get("elements", []):
    if el.get("type") != "way":
        continue
    if el.get("tags", {}).get("highway") not in DRIVABLE:
        continue
    geom = [(g["lon"], g["lat"]) for g in el.get("geometry", [])]
    if len(geom) >= 2:
        osm_lines.append(geom)

# --- generated clusters (red) ---
gen_lines = []
stats = {"clusters": 0, "links": 0, "empty": 0}
for f in sorted(grid_dir.glob("gen-*.bin")):
    g = parse_graph(f.read_bytes(), f.name)
    if not g["links"]:
        stats["empty"] += 1
        continue
    stats["clusters"] += 1
    for l in g["links"]:
        pts = l.get("path_coordinates") or []
        if len(pts) >= 2:
            gen_lines.append([datum.to_wgs84(p["x"], p["y"]) for p in pts])
            stats["links"] += 1

fig, ax = plt.subplots(figsize=(16, 11), dpi=140)
for line in osm_lines:
    xs, ys = zip(*line)
    ax.plot(xs, ys, color="#bbbbbb", lw=0.5, zorder=1)
for line in gen_lines:
    xs, ys = zip(*line)
    ax.plot(xs, ys, color="#d62728", lw=0.9, zorder=2)
ax.set_aspect(1 / 0.755)  # ~cos(45N) for plate-carree-like frame
ax.set_title(f"OSM (gray) vs generated TPNAV2 clusters (red): {stats}")
ax.set_xlabel("lon")
ax.set_ylabel("lat")
fig.tight_layout()
fig.savefig(out_png)
print(f"saved {out_png}; osm lines {len(osm_lines)}, gen lines {stats['links']}, "
      f"clusters {stats['clusters']} (empty {stats['empty']})")
