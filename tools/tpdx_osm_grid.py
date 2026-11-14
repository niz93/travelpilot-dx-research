#!/usr/bin/env python3
"""Build a stitched grid of generated TPNAV2 clusters from OSM geometry.

Pipeline: OSM ways (drivable classes) -> internal coordinates -> grid of
core cells; each way is split where it crosses cell borders; boundary
cut points become shared boundary nodes with pair-assigned boundary words
(same body per shared edge, 0x4000 bit marking the side, like live
0xa075<->0xe075 pairs). Each cluster is serialized with ClusterBuilder,
validated by parse_graph, and the whole grid is re-stitched under the
confirmed rule (word body + local ends <=1000 units + bounds overlap).

Format limits driving the design:
  * node refs are 10-bit (raw & 0x3ff): <= MAX_LINKS links and a body
    pool above the node count per cluster;
  * declared_size is uint16: <= MAX_CLUSTER bytes per cluster;
  * the NAV container holds 256 records: grid stays <= 16x16 cells.

The grid refines automatically (nx, ny double) while any cluster exceeds
a limit. Boundary word bodies are assigned AFTER all clusters are built:
body = 1023 - pair_ordinal, pairs claimed by the largest clusters first,
with the hard check body > max(nodesA, nodesB) so the parser's fallback
resolution stays out of range on both sides.

Usage: python tools/tpdx_osm_grid.py analysis/osm-region.json --grid 4x4
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpdx_coords import Datum
from tpnav2_graph import parse_graph
from tpnav2_cluster_gen import ClusterBuilder, WORD_SIDE_A, WORD_SIDE_B

DRIVABLE = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link", "road",
}
MAX_CLUSTER = 0xFFF0  # declared_size is uint16; keep headroom
MAX_LINKS = 1000      # node refs carry a 10-bit link index (mask 0x3ff):
                      # 0x4000..0x3FFF bits of bigger numbers are attribute
                      # bits (observed ref 0x0C0B = attrs 0x0C00 + link 11)
MAX_NODES = 1023      # boundary bodies (10-bit) must exceed the node count
MAX_GRID = 32         # 32x32 = 1024 cells; NAV entry_count is u32, so the
                      # container format itself is not limited to 256 records
SHIFT = 6
EPS_M = 20.0          # curvature decimation step: private vertices closer
                      # than this to the previous kept one become link shape
                      # instead of nodes (intersections/terminals untouched)


class GridTooDense(Exception):
    """Raised when the current grid cannot satisfy format limits."""


def load_ways(path: Path, datum: Datum, eps_m: float = EPS_M):
    """Return (ways, shared) — polylines in absolute internal units and the
    set of vertex coordinates used by >=2 ways (intersections).

    Decimation: private curvature vertices closer than eps to the previous
    kept vertex are dropped outright (the grid later re-samples what it
    needs); shared vertices and way terminals are always kept.
    """
    d = json.loads(path.read_text(encoding="utf-8"))
    raw = []
    for el in d.get("elements", []):
        if el.get("type") != "way":
            continue
        hw = el.get("tags", {}).get("highway")
        if hw not in DRIVABLE:
            continue
        geom = el.get("geometry", [])
        if len(geom) < 2:
            continue
        raw.append([datum.to_internal(g["lon"], g["lat"]) for g in geom])

    freq: dict[tuple[int, int], int] = {}
    for w in raw:
        for p in w:
            freq[p] = freq.get(p, 0) + 1
    shared = {p for p, c in freq.items() if c >= 2}

    eps = eps_m / datum.meters_per_unit_lat()
    ways = []
    for w in raw:
        keep = [w[0]]
        for p in w[1:-1]:
            if p in shared:
                keep.append(p)
                continue
            x0, y0 = keep[-1]
            if math.hypot(p[0] - x0, p[1] - y0) >= eps:
                keep.append(p)
        keep.append(w[-1])
        if len(keep) >= 2:
            ways.append(keep)
    return ways, shared


class Grid:
    def __init__(self, ways, nx: int, ny: int, margin_units: int):
        xs = [p[0] for w in ways for p in w]
        ys = [p[1] for w in ways for p in w]
        self.x0, self.x1 = min(xs), max(xs)
        self.y0, self.y1 = min(ys), max(ys)
        self.nx, self.ny = nx, ny
        self.margin = margin_units
        self.cw = max(1, (self.x1 - self.x0) // nx)
        self.ch = max(1, (self.y1 - self.y0) // ny)

    def cell_of(self, x: int, y: int) -> tuple[int, int]:
        cx = min(self.nx - 1, max(0, (x - self.x0) // self.cw))
        cy = min(self.ny - 1, max(0, (y - self.y0) // self.ch))
        return cx, cy

    def core_rect(self, cx: int, cy: int):
        return (self.x0 + cx * self.cw, self.y0 + cy * self.ch,
                self.x0 + (cx + 1) * self.cw, self.y0 + (cy + 1) * self.ch)

    def bounds_rect(self, cx: int, cy: int):
        ax0, ay0, ax1, ay1 = self.core_rect(cx, cy)
        return (ax0 - self.margin, ay0 - self.margin,
                ax1 + self.margin, ay1 + self.margin)


def split_way(way, grid: Grid):
    """Split a polyline into per-cell runs.

    Returns list of runs: (cell, points, cut_flags, axes) where cut_flags[i]
    is True when points[i] lies on a cell border (shared boundary node) and
    axes[i] is then 'x' (vertical border crossed) or 'y' (horizontal).
    The axis is what makes the neighbour cell unambiguous on both sides.
    """
    runs = []
    cur_cell = grid.cell_of(*way[0])
    cur = [way[0]]
    cur_flags = [False]
    cur_axes = [None]
    for p_prev, p in zip(way, way[1:]):
        cell_next = grid.cell_of(*p)
        seg_start = p_prev
        while cell_next != cur_cell:
            cx, cy = cur_cell
            rx0, ry0, rx1, ry1 = grid.core_rect(cx, cy)
            # candidate border crossing parameters
            tbest, cellbest, axbest = None, None, None
            if p[0] != seg_start[0]:
                bx = rx1 if p[0] > seg_start[0] else rx0
                tx = (bx - seg_start[0]) / (p[0] - seg_start[0])
                if 0 < tx <= 1:
                    cand = (min(grid.nx - 1, cx + (1 if p[0] > seg_start[0] else -1)), cy)
                    if cand != cur_cell:
                        tbest, cellbest, axbest = tx, cand, "x"
            if p[1] != seg_start[1]:
                by = ry1 if p[1] > seg_start[1] else ry0
                ty = (by - seg_start[1]) / (p[1] - seg_start[1])
                if 0 < ty <= 1 and (tbest is None or ty < tbest):
                    cand = (cx, min(grid.ny - 1, cy + (1 if p[1] > seg_start[1] else -1)))
                    if cand != cur_cell:
                        tbest, cellbest, axbest = ty, cand, "y"
            if tbest is None:
                cell_next = cur_cell  # numeric guard
                break
            cross = (round(seg_start[0] + (p[0] - seg_start[0]) * tbest),
                     round(seg_start[1] + (p[1] - seg_start[1]) * tbest))
            cur.append(cross)
            cur_flags.append(True)
            cur_axes.append(axbest)
            runs.append((cur_cell, cur, cur_flags, cur_axes))
            cur_cell = cellbest
            cur = [cross]
            cur_flags = [True]
            cur_axes = [axbest]
        cur.append(p)
        cur_flags.append(False)
        cur_axes.append(None)
        seg_start = p
    runs.append((cur_cell, cur, cur_flags, cur_axes))
    # merge consecutive runs in same cell (touching cut points)
    merged = []
    for cell, pts, flags, axes in runs:
        if merged and merged[-1][0] == cell:
            pc, pp, pf, pa = merged[-1]
            pp.extend(pts[1:])
            pf.extend(flags[1:])
            pa.extend(axes[1:])
        else:
            merged.append((cell, list(pts), list(flags), list(axes)))
    return merged


def build_grid(ways, grid: Grid, shared: set):
    """Return ({cell: ClusterBuilder}, stats, boundary registry).

    Boundary links are created with a 0 body placeholder; bodies are
    assigned later by assign_bodies once all node counts are known.
    A run is cut into links only at mandatory vertices (terminals, cell
    border crossings, shared intersection coordinates); the remaining
    curvature vertices travel as link shape geometry.
    """
    builders: dict[tuple[int, int], ClusterBuilder] = {}
    node_ids: dict[tuple[int, int], dict[tuple[int, int], int]] = {}
    registry: list[dict] = []
    stats = {"ways": len(ways), "runs": 0, "boundary_links": 0}

    def builder_for(cell):
        if cell not in builders:
            bx0, by0, bx1, by1 = grid.bounds_rect(*cell)
            b = ClusterBuilder(base_x=bx0, base_y=by0, shift=SHIFT)
            b.set_bounds(bx0, by0, bx1, by1)
            builders[cell] = b
            node_ids[cell] = {}
        return builders[cell]

    def node_for(cell, point):
        key = (int(point[0]), int(point[1]))
        m = node_ids[cell]
        if key not in m:
            m[key] = builder_for(cell).add_node(*key)
        return m[key]

    def add_boundary(cell, b, local_node, other, at, shape, cut):
        side = WORD_SIDE_A if cell <= other else WORD_SIDE_B
        pair = (cell, other) if cell <= other else (other, cell)
        if at == "second":
            link_no = b.add_link(local_node, None, shape=list(shape),
                                 boundary_word=side, boundary_at="second")
        else:
            link_no = b.add_link(None, local_node, shape=list(shape),
                                 boundary_word=side, boundary_at="first")
        registry.append({"cell": cell, "link": link_no, "pair": pair,
                         "other": other, "side": side, "at": at, "cut": cut})
        stats["boundary_links"] += 1

    def neighbour_across(cell, cut, interior, ax):
        """Cell on the far side of the border that `cut` lies on."""
        cx, cy = cell
        if ax == "x":
            return (cx + (1 if interior[0] < cut[0] else -1), cy)
        return (cx, cy + (1 if interior[1] < cut[1] else -1))

    def side_ref(dedup, start, stop, step, cut, ax):
        """Nearest run point strictly off the cut's border line: unambiguous
        side reference for neighbour_across. Falls back to `cut` itself
        (pure border-graze runs) which selects the deterministic -1 side."""
        idx = 1 if ax == "y" else 0
        for k in range(start, stop, step):
            q = dedup[k][0]
            if q[idx] != cut[idx]:
                return q
        return cut

    for way in ways:
        runs = split_way(way, grid)
        # Drop zero-interior runs (corner clips, border touch-and-return) and
        # un-flag their endpoints in the neighbouring runs: a crossing that
        # encloses no area in the next cell is an ordinary vertex there.
        for idx, (rcell, rpts, rflags, raxes) in enumerate(runs):
            if not all(rflags):
                continue
            if idx > 0:
                ppts, pflags, paxes = runs[idx - 1][1], runs[idx - 1][2], runs[idx - 1][3]
                if ppts[-1] == rpts[0]:
                    pflags[-1] = False
                    paxes[-1] = None
            if idx < len(runs) - 1:
                npts, nflags, naxes = runs[idx + 1][1], runs[idx + 1][2], runs[idx + 1][3]
                if npts[0] == rpts[-1]:
                    nflags[0] = False
                    naxes[0] = None
        for cell, pts, flags, axes in runs:
            if all(flags):
                continue  # zero-area run: absorbed into its neighbours above
            # drop duplicate consecutive points
            clean = list(zip(pts, flags, axes))
            dedup = [clean[0]]
            for item in clean[1:]:
                if item[0] != dedup[-1][0]:
                    dedup.append(item)
            if len(dedup) < 2:
                continue
            stats["runs"] += 1
            b = builder_for(cell)
            n = len(dedup)
            mandatory = [0] + [k for k in range(1, n - 1)
                               if dedup[k][1] or dedup[k][0] in shared] + [n - 1]
            for a, c in zip(mandatory, mandatory[1:]):
                (p0, f0, ax0), (p1, f1, ax1) = dedup[a], dedup[c]
                shape = [p for p, _, _ in dedup[a + 1:c]]
                # every run is [cut?, interior..., cut?] after the zero-area
                # filter: the cut point itself is a shared node on the border
                n0 = node_for(cell, p0)
                n1 = node_for(cell, p1)
                b.add_link(n0, n1, shape=shape)
                if f1:
                    ref = side_ref(dedup, c - 1, a - 1, -1, p1, ax1)
                    other = neighbour_across(cell, p1, ref, ax1)
                    add_boundary(cell, b, n1, other, "second", [], p1)
                if f0:
                    ref = side_ref(dedup, a + 1, c + 1, 1, p0, ax0)
                    other = neighbour_across(cell, p0, ref, ax0)
                    add_boundary(cell, b, n0, other, "first", [], p0)

    # Ways ending exactly on a cell border produce a boundary exit whose
    # neighbour run degenerated to a single point and never became a
    # cluster. Convert those exits into plain terminal nodes (both raw
    # ends local, ref wired like add_link does).
    kept_registry = []
    for r in registry:
        if r["other"] in builders:
            kept_registry.append(r)
            continue
        b = builders[r["cell"]]
        lnk = b.links[r["link"] - 1]
        node = node_for(r["cell"], r["cut"])
        key = "raw_second" if r["at"] == "second" else "raw_first"
        lnk[key] = node
        lnk["flags"] |= 0x2 if lnk["shape"] else 0
        ref = r["link"] | (0x8000 if r["at"] == "second" else 0)
        b.nodes[node - 1]["refs"].append(ref)
        stats["dangling_exits"] = stats.get("dangling_exits", 0) + 1
    if stats.get("dangling_exits"):
        print(f"converted {stats['dangling_exits']} dangling boundary exits "
              f"to terminal nodes")
    return builders, stats, kept_registry


def assign_bodies(builders, registry):
    """Assign boundary word bodies after all clusters are built.

    Body = 1023 - ordinal, ordinals handed out globally unique. Clusters
    are processed in decreasing node count so the largest clusters claim
    the highest bodies first. Raises GridTooDense when no valid body
    remains (caller refines the grid).
    """
    counts = {c: len(b.nodes) for c, b in builders.items()}
    for c, b in builders.items():
        if len(b.links) > MAX_LINKS:
            raise GridTooDense(f"links {len(b.links)} in cell {c} > {MAX_LINKS}")
        if len(b.nodes) > MAX_NODES:
            raise GridTooDense(f"nodes {len(b.nodes)} in cell {c} > {MAX_NODES}")
    incident: dict[tuple, list[dict]] = {}
    for r in registry:
        incident.setdefault(r["pair"], []).append(r)
    order = sorted(builders, key=lambda c: -counts[c])
    used_ord: set[int] = set()
    assigned: dict[tuple, int] = {}
    for cell in order:
        for pair in sorted(p for p in incident if cell in p):
            if pair in assigned:
                continue
            a, b = pair
            need = max(counts[a], counts[b]) + 1
            ord_ = 0
            while ord_ in used_ord:
                ord_ += 1
            body = 1023 - ord_
            if body < need:
                raise GridTooDense(
                    f"pair {pair} needs body >= {need}, only {body} left "
                    f"(nodes {counts[a]}/{counts[b]})")
            used_ord.add(ord_)
            assigned[pair] = body
    for r in registry:
        body = assigned[r["pair"]]
        lnk = builders[r["cell"]].links[r["link"] - 1]
        key = "raw_second" if r["at"] == "second" else "raw_first"
        lnk[key] = r["side"] | body


def attempt(ways, shared, nx, ny, margin, out: Path):
    """One build at the given grid resolution. Raises GridTooDense."""
    grid = Grid(ways, nx, ny, margin)
    print(f"grid {nx}x{ny}: region x {grid.x0}..{grid.x1}, "
          f"y {grid.y0}..{grid.y1}; cells {grid.cw}x{grid.ch} units, "
          f"margin {margin}")
    builders, stats, registry = build_grid(ways, grid, shared)
    assign_bodies(builders, registry)
    print("build stats:", stats)

    out.mkdir(parents=True, exist_ok=True)
    reports = {}
    total_boundary_ends = 0
    for cell, b in sorted(builders.items()):
        data = b.build()
        if len(data) > MAX_CLUSTER:
            raise GridTooDense(f"cluster {cell} size {len(data)} > {MAX_CLUSTER}")
        name = f"gen-{cell[0]}-{cell[1]}.bin"
        (out / name).write_bytes(data)
        g = parse_graph(data, name)
        v = g["validation"]
        be = [e for e in v["errors"] if "outside 1.." in e]
        reports[cell] = {
            "file": name, "size": len(data),
            "nodes": len(g["nodes"]), "links": len(g["links"]),
            "conflicts": len(v["endpoint_conflicts"]),
            "unexpected_errors": [e for e in v["errors"] if e not in be],
            "boundary_errors": len(be),
        }
        total_boundary_ends += len(be)
        print(f"{name}: {reports[cell]['nodes']}n {reports[cell]['links']}l "
              f"size={len(data)} conflicts={reports[cell]['conflicts']} "
              f"boundary_ends={len(be)} unexpected={reports[cell]['unexpected_errors'][:1]}")

    # --- region-wide stitch under the confirmed rule ---
    clusters = {}
    for cell, b in sorted(builders.items()):
        data = (out / reports[cell]["file"]).read_bytes()
        g = parse_graph(data, reports[cell]["file"])
        xs = [c["x"] for c in g["bounds_coordinates"]]
        ys = [c["y"] for c in g["bounds_coordinates"]]
        ends = []
        n = len(g["nodes"])
        for l in g["links"]:
            for end, skey, rkey, okey in (
                    ("first", "first_source", "raw_first", "resolved_second"),
                    ("second", "second_source", "raw_second", "resolved_first")):
                if l.get(skey) == "node_link_list":
                    continue
                raw = l[rkey]
                if not 1 <= (raw & 0x3ff) <= n:
                    c = g["nodes"][l[okey] - 1]["coordinate"]
                    ends.append((raw, c["x"], c["y"]))
        clusters[cell] = {"box": [min(xs), min(ys), max(xs), max(ys)],
                          "ends": ends, "matched": [False] * len(ends)}

    stitched = 0
    pairs = 0
    details = []
    cells = sorted(clusters)
    for i, ca in enumerate(cells):
        for cb in cells[i + 1:]:
            A, B = clusters[ca], clusters[cb]
            overlap = not (A["box"][2] < B["box"][0] or B["box"][2] < A["box"][0]
                           or A["box"][3] < B["box"][1] or B["box"][3] < A["box"][1])
            if not overlap:
                continue
            pairs += 1
            for ia, (raw_a, xa, ya) in enumerate(A["ends"]):
                for ib, (raw_b, xb, yb) in enumerate(B["ends"]):
                    if (raw_a & 0x3ff) != (raw_b & 0x3ff):
                        continue
                    dist = math.hypot(xa - xb, ya - yb)
                    if dist <= 1000:
                        stitched += 1
                        A["matched"][ia] = True
                        B["matched"][ib] = True
                        if len(details) < 50:
                            details.append({"cells": [ca, cb],
                                            "words": [hex(raw_a), hex(raw_b)],
                                            "body": raw_a & 0x3ff, "dist": round(dist, 1)})
    total_ends = sum(len(c["ends"]) for c in clusters.values())
    matched_ends = sum(sum(c["matched"]) for c in clusters.values())
    print(f"stitch: {pairs} overlapping pairs, boundary ends {total_ends}, "
          f"matched {matched_ends} (combos {stitched})")
    ok = (matched_ends == total_ends == total_boundary_ends
          and all(r["conflicts"] == 0 and not r["unexpected_errors"]
                  for r in reports.values()))
    report = {"ok": ok, "grid": [nx, ny], "stats": stats,
              "cells": {str(k): v for k, v in reports.items()},
              "stitch": {"pairs": pairs, "ends": total_ends,
                         "matched": matched_ends, "combos": stitched},
              "details": details}
    return report, ok


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("osm_json", type=Path)
    ap.add_argument("--grid", default="4x4")
    ap.add_argument("--margin-km", type=float, default=0.8)
    ap.add_argument("--out", type=Path,
                    default=Path("analysis/tpdx-grid"))
    args = ap.parse_args()
    nx, ny = (int(v) for v in args.grid.split("x"))

    datum = Datum()
    ways, shared = load_ways(args.osm_json, datum)
    print(f"ways after filter: {len(ways)} (shared vertices {len(shared)})")
    margin = int(args.margin_km * 1000 / datum.meters_per_unit_lat())

    while True:
        try:
            report, ok = attempt(ways, shared, nx, ny, margin, args.out)
            break
        except GridTooDense as e:
            print(f"grid {nx}x{ny} too dense: {e}; refining")
            nx *= 2
            ny *= 2
            if nx > MAX_GRID or ny > MAX_GRID:
                print("RESULT: FAIL (exceeded grid limit)")
                sys.exit(1)
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("RESULT:", "ALL OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
