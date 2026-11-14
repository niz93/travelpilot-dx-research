#!/usr/bin/env python3
"""Fit the WGS84 <-> TPMAP2/TPNAV2 internal-unit transform from city labels.

Matched city-name labels (table C points, verified survey in
analysis/tpdx-labels-*.json) against known WGS84 city coordinates and fit
X = Kx*lon + cx, Y = Ky*lat + cy by robust least squares (wide baseline:
MRE spans most of Europe). Result is written to analysis/tpdx-datum.json
and consumed by tools/tpdx_coords.py.
"""
from __future__ import annotations
import json
import math
import unicodedata
from pathlib import Path

CITIES = {
    # Germany
    "AACHEN": (6.0839, 50.7753), "AUGSBURG": (10.8978, 48.3705),
    "BERLIN": (13.4050, 52.5200), "BIELEFELD": (8.5325, 52.0302),
    "BOCHUM": (7.2162, 51.4818), "BONN": (7.0982, 50.7374),
    "BRAUNSCHWEIG": (10.5268, 52.2689), "BREMEN": (8.8017, 53.0793),
    "CHEMNITZ": (12.9253, 50.8278), "DARMSTADT": (8.6512, 49.8728),
    "DORTMUND": (7.4653, 51.5136), "DRESDEN": (13.7373, 51.0504),
    "DUISBURG": (6.7623, 51.4344), "DUSSELDORF": (6.7735, 51.2277),
    "ERFURT": (11.0299, 50.9848), "ESSEN": (7.0116, 51.4556),
    "FRANKFURT AM MAIN": (8.6821, 50.1109), "FREIBURG": (7.8421, 47.9990),
    "GELSENKIRCHEN": (7.0857, 51.5177), "GOTTINGEN": (9.7320, 51.5413),
    "HALLE": (11.9705, 51.4825), "HAMBURG": (9.9937, 53.5511),
    "HAMM": (7.8200, 51.6800), "HANNOVER": (9.7320, 52.3759),
    "HEIDELBERG": (8.6908, 49.4068), "KARLSRUHE": (8.4037, 49.0069),
    "KASSEL": (9.4937, 51.3084), "KIEL": (10.1228, 54.3233),
    "KOBLENZ": (7.5969, 50.3569), "KOLN": (6.9603, 50.9375),
    "LEIPZIG": (12.3731, 51.3397), "LEVERKUSEN": (6.9900, 51.0300),
    "LUBECK": (10.6866, 53.8655), "LUDWIGSHAFEN": (8.4464, 49.4774),
    "MAGDEBURG": (11.6276, 52.1205), "MAINZ": (8.2473, 49.9929),
    "MANNHEIM": (8.4660, 49.4875), "MULHEIM": (6.8840, 51.4275),
    "MUNCHEN": (11.5820, 48.1351), "MUNSTER": (7.6261, 51.9607),
    "NURNBERG": (11.0767, 49.4521), "OLDENBURG": (8.2146, 53.1435),
    "OSNABRUCK": (8.0472, 52.2799), "POTSDAM": (13.0645, 52.3906),
    "ROSTOCK": (12.0991, 54.0924), "SAARBRUCKEN": (7.0661, 49.2332),
    "STUTTGART": (9.1829, 48.7758), "WIESBADEN": (8.2392, 50.0782),
    "WUPPERTAL": (7.1508, 51.2562), "WURZBURG": (9.9370, 49.7913),
    # Poland
    "BIALYSTOK": (23.1688, 53.1325), "BYDGOSZCZ": (18.0067, 53.1235),
    "CZESTOCHOWA": (19.1240, 50.8118), "GDANSK": (18.6466, 54.3520),
    "GDYNIA": (18.5460, 54.5189), "GLIWICE": (18.6787, 50.2945),
    "KATOWICE": (19.0216, 50.2649), "KIELCE": (20.9383, 50.8661),
    "KRAKOW": (19.9450, 50.0647), "LODZ": (19.4560, 51.7592),
    "LUBLIN": (22.5684, 51.2465), "OLSZTYN": (20.4802, 53.7784),
    "OPOLE": (17.9213, 50.6751), "POZNAN": (16.9252, 52.4064),
    "RADOM": (21.1471, 51.4025), "RZESZOW": (22.0000, 50.0413),
    "SOSNOWIEC": (19.1044, 50.2863), "SZCZECIN": (14.5528, 53.4285),
    "TORUN": (18.5984, 53.0138), "WARSZAWA": (21.0122, 52.2297),
    "WROCLAW": (17.0385, 51.1079), "ZABRZE": (18.7857, 50.3249),
    "ZIELONA GORA": (15.5062, 51.9356),
    # Czech
    "BRNO": (16.6068, 49.1951), "CESKE BUDEJOVICE": (14.4743, 48.9745),
    "HRADEC KRALOVE": (15.8252, 50.2092), "JIHlAVA": (15.5890, 49.4003),
    "KARLOVY VARY": (12.8711, 50.1435), "LIBEREC": (15.0562, 50.7671),
    "OLOMOUC": (17.2486, 49.5938), "OSTRAVA": (18.2923, 49.8209),
    "PARDUBICE": (15.7773, 50.0343), "PLZEN": (13.3775, 49.7384),
    "PRAHA": (14.4378, 50.0755), "USTI NAD LABEM": (14.0434, 50.6603),
    # Europe (MRE)
    "AMSTERDAM": (4.9041, 52.3676), "ATHEN": (23.7275, 37.9838),
    "ATHENA": (23.7275, 37.9838), "BARCELONA": (2.1734, 41.3851),
    "BERGEN": (5.3221, 60.3913), "BILBAO": (-2.9350, 43.2630),
    "BIRMINGHAM": (-1.8904, 52.4862), "BORdeaux": (-0.5792, 44.8378),
    "BRATISLAVA": (17.1077, 48.1486), "BRUXELLES": (4.3517, 50.8503),
    "BUDAPEST": (19.0402, 47.4979), "BUCURESTI": (26.1025, 44.4268),
    "DUBLIN": (-6.2603, 53.3498), "EDINBURGH": (-3.1883, 55.9533),
    "FARO": (-7.9304, 37.0194), "GENF": (6.1432, 46.2044),
    "GLASGOW": (-4.2518, 55.8609), "GOTEBORG": (11.9746, 57.7089),
    "HELSINKI": (24.9384, 60.1699), "ISTANBUL": (28.9784, 41.0082),
    "KOBENHAVN": (12.5683, 55.6761), "LEEDS": (-1.5491, 53.8008),
    "LILLE": (3.0573, 50.6292), "LIVERPOOL": (-2.9935, 53.4084),
    "LJUBLJANA": (14.5058, 46.0569), "LONDON": (-0.1276, 51.5072),
    "LYON": (4.8357, 45.7640), "MADRID": (-3.7038, 40.4168),
    "MALAGA": (-4.4214, 36.7213), "MALMO": (13.0038, 55.6050),
    "MANCHESTER": (-2.2426, 53.4808), "MARSEILLE": (5.3698, 43.2965),
    "MAILAND": (9.1900, 45.4642), "NANTES": (-1.5536, 47.2184),
    "NAPOLI": (14.2681, 40.8518), "NICE": (7.2620, 43.7102),
    "OSLO": (10.7522, 59.9139), "PALERMO": (13.3613, 38.1157),
    "PARIS": (2.3522, 48.8566), "PORTO": (-8.6291, 41.1579),
    "PRAG": (14.4378, 50.0755), "RIGA": (24.1052, 56.9496),
    "ROM": (12.4964, 41.9028), "ROTTERDAM": (4.4777, 51.9244),
    "SALZBURG": (13.0550, 47.8095), "SARAJEVO": (18.4131, 43.8563),
    "SEVILLA": (-5.9845, 37.3891), "SOFIA": (23.3219, 42.6977),
    "STOCKHOLM": (18.0686, 59.3293), "STRASSBURG": (7.7521, 48.5734),
    "STUTTGART": (9.1829, 48.7758), "TALLINN": (24.7536, 59.4370),
    "TOULOUSE": (1.4442, 43.6047), "TRONDHEIM": (10.3951, 63.4305),
    "TURIN": (7.6869, 45.0703), "VALENCIA": (-0.3763, 39.4699),
    "VILNIUS": (25.2797, 54.6872), "WARSCHAU": (21.0122, 52.2297),
    "WIEN": (16.3738, 48.2082), "ZAGREB": (15.9772, 45.8150),
    "ZURICH": (8.5417, 47.3769),
}

EXTRA_FOLD = {"ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "æ": "ae",
              "Æ": "l", "ð": "d", "þ": "th", "ß": "ss", "ħ": "h",
              "å": "a", "Å": "a", "œ": "oe"}


def fold(text: str) -> str:
    if text.startswith("ñ"):  # 0xE1 name marker observed in labels
        text = text[1:]
    text = "".join(EXTRA_FOLD.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper().strip()


def load_matches():
    matches = []  # (name, x, y, map, level, index)
    for f in Path("analysis").glob("tpdx-labels-*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        for raw, occ in d["texts"].items():
            name = fold(raw)
            if name in CITIES:
                for o in occ:
                    matches.append((name, o["x"], o["y"], f.stem, o["level"], o["index"]))
    return matches


def fit(matches, iters=4, sigma=3.0):
    pts = list(matches)
    for it in range(iters):
        lons = [CITIES[m[0]][0] for m in pts]
        lats = [CITIES[m[0]][1] for m in pts]
        xs = [m[1] for m in pts]
        ys = [m[2] for m in pts]

        def lin(fit_x, fit_y):
            n = len(fit_x)
            mx = sum(fit_x) / n
            my = sum(fit_y) / n
            sxx = sum((v - mx) ** 2 for v in fit_x)
            sxy = sum((a - mx) * (b - my) for a, b in zip(fit_x, fit_y))
            k = sxy / sxx if sxx else 0.0
            return k, my - k * mx

        kx, cx = lin(lons, xs)
        ky, cy = lin(lats, ys)
        res = []
        for lon, lat, x, y in zip(lons, lats, xs, ys):
            rx = x - (kx * lon + cx)
            ry = y - (ky * lat + cy)
            res.append(math.hypot(rx, ry))
        n = len(res)
        med = sorted(res)[n // 2]
        keep = [p for p, r in zip(pts, res) if r <= max(sigma * med, 1.0)]
        if len(keep) == len(pts):
            break
        pts = keep
    return kx, cx, ky, cy, pts, res


def main():
    matches = load_matches()
    print("matched label occurrences:", len(matches),
          "unique cities:", len(set(m[0] for m in matches)))
    if len(matches) < 10:
        raise SystemExit("too few matches")
    kx, cx, ky, cy, kept, res = fit(matches)
    print(f"fit: X = {kx:.6f}*lon + {cx:.1f}")
    print(f"     Y = {ky:.6f}*lat + {cy:.1f}")
    lons = [CITIES[m[0]][0] for m in kept]
    lats = [CITIES[m[0]][1] for m in kept]
    errs = []
    for m, lon, lat in zip(kept, lons, lats):
        px = kx * lon + cx
        py = ky * lat + cy
        errs.append(math.hypot(m[1] - px, m[2] - py))
    errs.sort()
    n = len(errs)
    print(f"kept {n} pts; residual median {errs[n//2]:.0f} units "
          f"(~{errs[n//2]*111320/ max(kx,ky)/1000:.2f} km), p90 {errs[int(n*0.9)]:.0f}, max {errs[-1]:.0f}")
    # scale sanity
    print(f"K ratio x/y: {kx/ky:.5f}; units per degree lat ~{ky:.0f}")
    # per-city diagnostics (worst 10)
    worst = sorted(zip(errs, kept), reverse=True)[:10]
    for e, m in worst:
        lon, lat = CITIES[m[0]]
        print(f"  worst: {m[0]:20s} err={e:8.0f} at ({m[1]}, {m[2]}) lonlat=({lon},{lat})")
    out = {
        "model": "X = Kx*lon + cx; Y = Ky*lat + cy (plate carree in internal units)",
        "Kx": kx, "cx": cx, "Ky": ky, "cy": cy,
        "units_per_degree_lat": ky,
        "unit_ground_m_at_lat_52": 111320 / ky * 1000 / 1000,
        "points_used": n,
        "cities_used": sorted(set(m[0] for m in kept)),
        "residual_median_units": errs[n // 2],
        "residual_p90_units": errs[int(n * 0.9)],
        "residual_max_units": errs[-1],
    }
    Path("analysis/tpdx-datum.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved analysis/tpdx-datum.json")


if __name__ == "__main__":
    main()
