#!/usr/bin/env python3
"""WGS84 <-> TPMAP2/TPNAV2 internal-unit converter.

Constants come from analysis/tpdx-datum.json (fitted by tools/tpdx_datum_fit.py
from city-name label anchors, robust least squares, 249 points / 71 cities):

    X = Kx*lon + cx        Y = Ky*lat + cy

Precision: label anchors carry legibility offsets; residual median ~0.6 km.
Good for: OSM geometry import into generated clusters, region-wide placement,
render georeferencing. NOT sufficient (~10 m needed) for stitching generated
clusters to untouched TeleAtlas neighbours — that needs a geometry-based
refit (rivers/highways vs OSM), planned next.

Ground scale: 1 internal unit ~ 9.3 mm in latitude direction at Ky units/deg;
east-west distances are stretched by 1/cos(lat) (plate-carree-like frame).
"""
from __future__ import annotations
import json
import math
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _cand in (_HERE.parent / "analysis", _HERE.parent / "results",
              _HERE / "analysis", _HERE / "results"):
    if (_cand / "tpdx-datum.json").exists():
        _DATUM_PATH = _cand / "tpdx-datum.json"
        break
else:
    _DATUM_PATH = _HERE.parent / "analysis" / "tpdx-datum.json"


class Datum:
    def __init__(self, path: Path = _DATUM_PATH):
        d = json.loads(path.read_text(encoding="utf-8"))
        self.Kx = d["Kx"]
        self.cx = d["cx"]
        self.Ky = d["Ky"]
        self.cy = d["cy"]
        self.meta = d

    def to_internal(self, lon: float, lat: float) -> tuple[int, int]:
        return (round(self.Kx * lon + self.cx),
                round(self.Ky * lat + self.cy))

    def to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.cx) / self.Kx, (y - self.cy) / self.Ky)

    def meters_per_unit_lat(self) -> float:
        return 111_320.0 / self.Ky

    def meters_per_unit_lon(self, lat_deg: float) -> float:
        return 111_320.0 * math.cos(math.radians(lat_deg)) / self.Kx

    def path_length_units(self, pts_wgs84: list[tuple[float, float]]) -> float:
        """Polyline length as the original data measures it (internal units,
        plate-carree distorted — matches how field04 was derived)."""
        internal = [self.to_internal(lon, lat) for lon, lat in pts_wgs84]
        return sum(math.hypot(x2 - x1, y2 - y1)
                   for (x1, y1), (x2, y2) in zip(internal, internal[1:]))

    def link_weight_field04(self, pts_wgs84: list[tuple[float, float]]) -> int:
        """field04 = round(path_length / 316.3) per the confirmed rule."""
        return round(self.path_length_units(pts_wgs84) / 316.3)


def main() -> None:
    d = Datum()
    print(f"datum: X = {d.Kx:.4f}*lon + {d.cx:.1f}; "
          f"Y = {d.Ky:.4f}*lat + {d.cy:.1f}")
    print(f"1 unit = {d.meters_per_unit_lat()*1000:.1f} mm (N-S), "
          f"{d.meters_per_unit_lon(52.0)*1000:.1f} mm (E-W at 52N)")
    checks = [("Berlin", 13.4050, 52.5200), ("Warszawa", 21.0122, 52.2297),
              ("Praha", 14.4378, 50.0755), ("Faro", -7.9304, 37.0194),
              ("Stockholm", 18.0686, 59.3293)]
    ok = True
    for name, lon, lat in checks:
        x, y = d.to_internal(lon, lat)
        lon2, lat2 = d.to_wgs84(x, y)
        err = math.hypot((lon2 - lon) * 111320 * math.cos(math.radians(lat)),
                         (lat2 - lat) * 111320)
        print(f"{name:10s} internal=({x}, {y})  roundtrip err {err:.0f} m")
        ok = ok and err < 5  # affine inverse must be ~exact
    # weight sanity: a 1.0 km N-S link
    w = d.link_weight_field04([(14.0, 50.0), (14.0, 50.0 + 1.0 / 111.32)])
    print("field04 of ~1.0 km N-S link:", w)
    print("RESULT:", "ALL OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
