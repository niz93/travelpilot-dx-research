#!/usr/bin/env python3
"""Build a custom TPMAP2 MAP00001.MAP from OSM data (Krasnodar Krai test map).

Reuses the donor header shell (strings kept for disk-compatibility checks),
regenerates the four catalogue levels, emits a shared minimal block for empty
cells and content blocks built from OSM coastline/roads/town nodes.

Record archetypes are copied from donor samples (kind: flags/unknown4):
  0x03/0x23 flags 0xF000 u4 524038835 | 0x40 0x7000/327944053
  0x70 0x7000/295177049 | 0x71 0x3000/4284751885 | 0x90 0x7000/323426984
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpdx_coords import Datum
from tpmap_block_probe import probe_block

# ---------------------------------------------------------------- geometry --

class Grid:
    """Tile frame math equivalent to tpmap_geometry.TPMap (pure functions)."""

    CONFIGS = {0: (1, 1, 13), 1: (4, 3, 11), 2: (10, 11, 7), 3: (10, 10, 4)}

    def __init__(self, bounds):
        self.bounds = bounds

    def grid_size(self, level):
        width = height = 1
        for current in range(1, level + 1):
            div_x, div_y, _ = self.CONFIGS[current]
            width *= div_x
            height *= div_y
        return width, height

    def index_at_xy(self, level, x, y):
        width, height = self.grid_size(level)
        assert 0 <= x < width and 0 <= y < height, (level, x, y)
        cells = [0] * 4
        rx, ry = x, y
        for current in range(level, 0, -1):
            div_x, div_y, _ = self.CONFIGS[current]
            cells[current] = (ry % div_y) * div_x + (rx % div_x)
            rx //= div_x
            ry //= div_y
        index = 0
        for current in range(1, level + 1):
            div_x, div_y, _ = self.CONFIGS[current]
            index = index * div_x * div_y + cells[current]
        return index

    def index_at_point(self, level, px, py):
        min_x, min_y, max_x, max_y = self.bounds
        width, height = self.grid_size(level)
        gx = min(width - 1, max(0, int((px - min_x) / (max_x - min_x) * width)))
        gy = min(height - 1, max(0, int((py - min_y) / (max_y - min_y) * height)))
        return self.index_at_xy(level, gx, gy)

    def frame(self, level, index):
        min_x, min_y, max_x, max_y = self.bounds
        cells = [0] * 4
        remainder = index
        for current in range(level, 0, -1):
            div_x, div_y, _ = self.CONFIGS[current]
            cells[current] = remainder % (div_x * div_y)
            remainder //= div_x * div_y
        assert remainder == 0
        for current in range(1, level + 1):
            div_x, div_y, _ = self.CONFIGS[current]
            cell_x, cell_y = cells[current] % div_x, cells[current] // div_x
            step_x = (max_x - min_x) // div_x
            step_y = (max_y - min_y) // div_y
            min_x, max_x = min_x + cell_x * step_x, min_x + (cell_x + 1) * step_x
            min_y, max_y = min_y + cell_y * step_y, min_y + (cell_y + 1) * step_y
        centre = (max_x - ((max_x - min_x + 1) // 2),
                  max_y - ((max_y - min_y + 1) // 2))
        return {"bounds": (min_x, min_y, max_x, max_y), "centre": centre,
                "shift": self.CONFIGS[level][2]}

    @staticmethod
    def to_rel(frame, x, y):
        cx, cy = frame["centre"]
        return ((x - cx) >> frame["shift"], (y - cy) >> frame["shift"])


# ------------------------------------------------------------ block builder --

AREA_ARCHETYPES = {
    0x03: (0xF000, 524038835),
    0x23: (0xF000, 524038835),
    0x40: (0x7000, 327944053),
    0x70: (0x7000, 295177049),
    0x71: (0x3000, 4284751885),
    0x90: (0x7000, 323426984),
}

MINIMAL_BLOCK = struct.pack("<IHHHHHH", 16, 0, 0, 0, 0, 0, 0)


def build_block(areas, lines, points):
    """areas: [(kind, [(rel x,y)...])]; lines: [(kind, [(rel x,y)...])];
    points: [(kind, relx, rely, [label text...])]. Returns block bytes."""
    header_len = 16
    # u16 pool offsets and the <60000 block budget: thin long records until
    # the estimated block fits, halving vertex counts each pass.
    def estimate(areas, lines, points):
        n_a = sum(len(p) for _, p in areas)
        n_b = sum(len(p) for _, p in lines)
        lbl = sum(12 + len(t.encode("latin-1", "replace")) + 4
                  for _, _, _, labels in points for t in labels)
        return (header_len + len(areas) * 16 + len(lines) * 12
                + len(points) * 12 + n_a * 4 + n_b * 4 + lbl)

    def thin(seq):
        out = []
        for kind, p in seq:
            if len(p) > 4:
                q = p[::2]
                if q[-1] != p[-1]:
                    q = q + [p[-1]]
                p = q
            out.append((kind, p))
        return out

    guard = 0
    while estimate(areas, lines, points) >= 59000 and guard < 12:
        guard += 1
        areas = thin(areas)
        lines = thin(lines)
    # record count is also bounded: each line record costs 12 bytes of header
    # and pushes pool offsets up; dense urban cells exceed u16 otherwise.
    if len(areas) > 1000:
        areas.sort(key=lambda t: -len(t[1]))
        areas = areas[:1000]
    if len(lines) > 1200:
        lines.sort(key=lambda t: -len(t[1]))
        lines = lines[:1200]
    a_off = header_len if areas else 0
    pool_base = header_len + len(areas) * 16 + len(lines) * 12 + len(points) * 12
    a_records = b""
    a_pools = b""
    for kind, pairs in areas:
        if not pairs:
            continue
        flags, u4 = AREA_ARCHETYPES.get(kind, (0x7000, 0))
        a_records += struct.pack("<HBBIHHI", flags, kind, 0, u4,
                                 pool_base + len(a_pools), len(pairs), 0)
        a_pools += b"".join(struct.pack("<hh", x, y) for x, y in pairs)
    if not a_records:
        a_off = 0
    b_off = header_len + len(a_records) if lines else 0
    b_records = b""
    b_pools = b""
    for kind, pairs in lines:
        if len(pairs) < 2:
            continue
        b_records += struct.pack("<HBBHHHH", 0, kind, 0,
                                 pool_base + len(a_pools) + len(b_pools),
                                 len(pairs), 0, 0)
        b_pools += b"".join(struct.pack("<hh", x, y) for x, y in pairs)
    if not b_records:
        b_off = 0
    c_off = header_len + len(a_records) + len(b_records) if points else 0
    c_records = b""
    c_pools = b""
    for kind, x, y, labels in points:
        payload = b""
        for text in labels:
            raw = b"\xf1" + text.encode("latin-1", "replace") + b"\x00"
            size = (2 + len(raw) + 3) & ~3
            payload += bytes([size]) + raw + b"\x00" * (size - 1 - len(raw))
        c_records += struct.pack("<HBBhhHH", 0, kind, 0, x, y,
                                 pool_base + len(a_pools) + len(b_pools) + len(c_pools)
                                 if labels else 0, len(labels))
        c_pools += payload
    if not c_records:
        c_off = 0
    body = a_records + b_records + c_records + a_pools + b_pools + c_pools
    length = header_len + len(body)
    assert length < 60000, f"block too large: {length}"
    block = struct.pack("<IHHHHHH", length, a_off, len(a_records) // 16,
                        b_off, len(b_records) // 12,
                        c_off, len(c_records) // 12) + body
    check = probe_block(block, len(block), include_records=False)
    assert check["accepted"], check["reason"]
    return block


# --------------------------------------------------------------- clipping ---

def douglas_peucker(points, eps):
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1.0
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            dist = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if dist > best:
                best, idx = dist, i
        if best > eps and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def clip_segment(p1, p2, rect):
    (x0, y0), (x1, y1) = p1, p2
    min_x, min_y, max_x, max_y = rect
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - min_x), (dx, max_x - x0),
                 (-dy, y0 - min_y), (dy, max_y - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return ((round(x0 + t0 * dx), round(y0 + t0 * dy)),
            (round(x0 + t1 * dx), round(y0 + t1 * dy)))


def clip_polyline(points, rect):
    out, run = [], []
    for a, b in zip(points, points[1:]):
        seg = clip_segment(a, b, rect)
        if seg is None:
            if run:
                out.append(run)
                run = []
            continue
        s, e = seg
        if not run or run[-1] != s:
            if run:
                out.append(run)
            run = [s]
        run.append(e)
    if run:
        out.append(run)
    return out


def clip_polygon(points, rect):
    def clip_edge(pts, inside, intersect):
        if not pts:
            return []
        out = []
        prev = pts[-1]
        prev_in = inside(prev)
        for cur in pts:
            cur_in = inside(cur)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
            prev, prev_in = cur, cur_in
        return out

    min_x, min_y, max_x, max_y = rect
    eps = 1
    pts = list(points)
    pts = clip_edge(pts, lambda p: p[0] >= min_x - eps,
                    lambda a, b: (min_x, a[1] + (b[1] - a[1]) * (min_x - a[0]) / ((b[0] - a[0]) or 1)))
    pts = clip_edge(pts, lambda p: p[0] <= max_x + eps,
                    lambda a, b: (max_x, a[1] + (b[1] - a[1]) * (max_x - a[0]) / ((b[0] - a[0]) or 1)))
    pts = clip_edge(pts, lambda p: p[1] >= min_y - eps,
                    lambda a, b: (a[0] + (b[0] - a[0]) * (min_y - a[1]) / ((b[1] - a[1]) or 1), min_y))
    pts = clip_edge(pts, lambda p: p[1] <= max_y + eps,
                    lambda a, b: (a[0] + (b[0] - a[0]) * (max_y - a[1]) / ((b[1] - a[1]) or 1), max_y))
    return pts


def point_in_polygon(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def close_along_border(chain, bounds):
    """Close an open coastline chain along the map bbox perimeter (CCW).

    Perimeter parameter: t=0 at (min_x,min_y), increasing CCW
    (east along the bottom, up, west along the top, down).
    """
    min_x, min_y, max_x, max_y = bounds
    w, h = max_x - min_x, max_y - min_y
    perimeter = 2 * (w + h)

    def param(p):
        x, y = p
        if y <= min_y:
            return (x - min_x) % perimeter
        if x >= max_x:
            return w + (y - min_y)
        if y >= max_y:
            return w + h + (max_x - x)
        return 2 * w + h + (max_y - y)

    def pt_at(t):
        t %= perimeter
        if t < w:
            return (min_x + int(t), min_y)
        if t < w + h:
            return (max_x, min_y + int(t - w))
        if t < 2 * w + h:
            return (max_x - int(t - w - h), max_y)
        return (min_x, max_y - int(t - 2 * w - h))

    t_end, t_start = param(chain[-1]), param(chain[0])
    dist = (t_start - t_end) % perimeter
    corners = sorted((c - t_end) % perimeter
                     for c in (0, w, w + h, 2 * w + h))
    chain = chain + [pt_at(t_end + d) for d in corners if 0 < d < dist]
    chain.append(chain[0])
    return chain


def polygonize_sea(coastline, bounds, datum):
    """Chain coastline ways, close along bbox, keep rings containing water."""
    if not coastline:
        return []
    chains, used = [], [False] * len(coastline)
    for i, way in enumerate(coastline):
        if used[i]:
            continue
        chain, used[i] = list(way), True
        extended = True
        while extended:
            extended = False
            for j, other in enumerate(coastline):
                if used[j]:
                    continue
                if chain[-1] == other[0]:
                    chain += other[1:]
                elif chain[-1] == other[-1]:
                    chain += other[-2::-1]
                elif chain[0] == other[-1]:
                    chain = other[:-1] + chain
                elif chain[0] == other[0]:
                    chain = other[:0:-1] + chain
                else:
                    continue
                used[j] = True
                extended = True
        chains.append(chain)
    probe = datum.to_internal(37.0, 43.6)  # deep Black Sea water inside bbox
    sea = []
    for chain in chains:
        candidates = []
        if chain[0] == chain[-1]:
            candidates.append(chain)
        else:
            candidates.append(close_along_border(list(chain), bounds))
            candidates.append(close_along_border(list(chain[::-1]), bounds))
        for ring in candidates:
            if point_in_polygon(probe, ring):
                sea.append(ring)
                break
    return sea


# ------------------------------------------------------------------- main ----

COUNTS = {0: 1, 1: 12, 2: 1320, 3: 132000}
BLOCKS_BASE = 0x104A98
SHARED_EMPTY = 0x10AEC0


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", type=Path, required=True)
    parser.add_argument("--donor", type=Path,
                        default=Path("../../extracted/czech_poland_2010_2011/MAP00001.MAP"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bbox", default="43.2,36.3,46.4,41.2",
                        help="south,west,north,east WGS84")
    parser.add_argument("--shifts", default="13,11,7,4",
                        help="per-level coordinate shifts L0..L3; must satisfy "
                             "(bounds_size/2/cell_count) >> shift <= 32767 for "
                             "both axes at every level")
    args = parser.parse_args()

    shifts = [int(v) for v in args.shifts.split(",")]
    assert len(shifts) == 4
    Grid.CONFIGS = {0: (1, 1, shifts[0]), 1: (4, 3, shifts[1]),
                    2: (10, 11, shifts[2]), 3: (10, 10, shifts[3])}

    south, west, north, east = (float(v) for v in args.bbox.split(","))
    datum = Datum()
    bounds = (*datum.to_internal(west, south), *datum.to_internal(east, north))
    print("internal bounds:", bounds)
    grid = Grid(bounds)

    osm = json.loads(args.osm.read_text(encoding="utf-8"))
    roads, coastline, towns = [], [], []
    for el in osm.get("elements", []):
        if el["type"] == "way":
            geom = [datum.to_internal(n["lon"], n["lat"])
                    for n in el.get("geometry", [])]
            if len(geom) < 2:
                continue
            tags = el.get("tags", {})
            if tags.get("natural") == "coastline":
                coastline.append(geom)
            elif "highway" in tags:
                roads.append((tags["highway"], geom))
        elif el["type"] == "node" and el.get("tags", {}).get("place") in ("city", "town"):
            tags = el["tags"]
            name = tags.get("name:en") or tags.get("int_name")
            if not name:
                continue
            towns.append((*datum.to_internal(el["lon"], el["lat"]),
                          name, tags["place"]))
    print(f"roads: {len(roads)}, coastline: {len(coastline)}, towns: {len(towns)}")

    sea = polygonize_sea(coastline, bounds, datum)
    print("sea rings:", len(sea))

    def land_rect(frame):
        r = frame["bounds"]
        pairs = [Grid.to_rel(frame, x, y) for x, y in
                 ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))]
        return pairs

    def sea_areas(frame, rect):
        out = []
        # cap coordinate count per record: A-record pool offsets are u16 and
        # the whole block must stay < 60000 bytes. Large bboxes make a single
        # clipped sea ring exceed that, so decimate aggressively when needed.
        cell_w = rect[2] - rect[0]
        cell_h = rect[3] - rect[1]
        eps = max(1.0, max(cell_w, cell_h) / 2000.0)
        for ring in sea:
            clipped = clip_polygon(ring, rect)
            if len(clipped) > 3000:
                clipped = douglas_peucker(clipped, eps)
            if len(clipped) > 6000:
                stride = (len(clipped) + 5999) // 6000
                clipped = clipped[::stride]
            if len(clipped) < 3:
                continue
            pairs = [Grid.to_rel(frame, round(x), round(y)) for x, y in clipped]
            if all(-32768 <= p[0] <= 32767 and -32768 <= p[1] <= 32767
                   for p in pairs):
                out.append(pairs)
        return out

    catalog = {lvl: [None] * COUNTS[lvl] for lvl in COUNTS}
    blobs = []
    cursor = BLOCKS_BASE

    def alloc(block):
        nonlocal cursor
        entry = (cursor, len(block))
        blobs.append((cursor, block))
        cursor += len(block)
        return entry

    def put(level, index, block):
        catalog[level][index] = alloc(block)

    def rect_of(level, index):
        return grid.frame(level, index)["bounds"]

    # ---- level 0: whole-map outline
    f0 = grid.frame(0, 0)
    r = bounds
    outline = douglas_peucker(
        [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])], 1)
    put(0, 0, build_block([(0x70, [Grid.to_rel(f0, x, y) for x, y in outline])],
                          [], []))

    # ---- level 1: land + sea per cell
    for idx in range(COUNTS[1]):
        f = grid.frame(1, idx)
        rect = f["bounds"]
        areas = [(0x40, land_rect(f))]
        for pairs in sea_areas(f, rect):
            areas.append((0x03, pairs))
        put(1, idx, build_block(areas, [], []))

    # ---- level 2: land + sea + major roads + towns
    keep2 = {"motorway", "trunk", "primary"}
    width2, height2 = grid.grid_size(2)
    major_by_cell = {}
    for cls, geom in roads:
        if cls not in keep2:
            continue
        min_x = min(p[0] for p in geom)
        max_x = max(p[0] for p in geom)
        min_y = min(p[1] for p in geom)
        max_y = max(p[1] for p in geom)
        gx0 = max(0, int((min_x - bounds[0]) / (bounds[2] - bounds[0]) * width2))
        gx1 = min(width2 - 1, int((max_x - bounds[0]) / (bounds[2] - bounds[0]) * width2))
        gy0 = max(0, int((min_y - bounds[1]) / (bounds[3] - bounds[1]) * height2))
        gy1 = min(height2 - 1, int((max_y - bounds[1]) / (bounds[3] - bounds[1]) * height2))
        for gy in range(gy0, gy1 + 1):
            for gx in range(gx0, gx1 + 1):
                idx = grid.index_at_xy(2, gx, gy)
                major_by_cell.setdefault(idx, []).append((cls, geom))
    town_cells2 = {}
    for x, y, name, place in towns:
        town_cells2.setdefault(grid.index_at_point(2, x, y), []).append((x, y, name, place))
    for idx in range(COUNTS[2]):
        f = grid.frame(2, idx)
        rect = f["bounds"]
        areas = [(0x23, land_rect(f))]
        for pairs in sea_areas(f, rect):
            areas.append((0x03, pairs))
        lines = []
        for cls, geom in major_by_cell.get(idx, []):
            for run in clip_polyline(geom, rect):
                simp = douglas_peucker(run, 120)
                if len(simp) < 2:
                    continue
                pairs = [Grid.to_rel(f, x, y) for x, y in simp]
                if all(-32768 <= p[0] <= 32767 and -32768 <= p[1] <= 32767
                       for p in pairs):
                    lines.append((0x10, pairs))
        points = []
        for x, y, name, place in town_cells2.get(idx, []):
            rx, ry = Grid.to_rel(f, x, y)
            points.append((0x2b if place == "town" else 0x2c, rx, ry,
                           [name.upper()]))
        put(2, idx, build_block(areas, lines, points))

    # ---- level 3: content cells only (coast, towns, roads)
    width3, height3 = grid.grid_size(3)
    coastal = set()
    for ring in sea:
        step = max(1, len(ring) // 64)
        for x, y in ring[::step]:
            coastal.add(grid.index_at_point(3, x, y))
    town_cells = {}
    for x, y, name, place in towns:
        town_cells.setdefault(grid.index_at_point(3, x, y), []).append((x, y, name, place))

    # spatial index: L3 cell -> roads passing through it
    roads_by_cell = {}
    for cls, geom in roads:
        min_x = min(p[0] for p in geom)
        max_x = max(p[0] for p in geom)
        min_y = min(p[1] for p in geom)
        max_y = max(p[1] for p in geom)
        gx0 = max(0, int((min_x - bounds[0]) / (bounds[2] - bounds[0]) * width3))
        gx1 = min(width3 - 1, int((max_x - bounds[0]) / (bounds[2] - bounds[0]) * width3))
        gy0 = max(0, int((min_y - bounds[1]) / (bounds[3] - bounds[1]) * height3))
        gy1 = min(height3 - 1, int((max_y - bounds[1]) / (bounds[3] - bounds[1]) * height3))
        for gy in range(gy0, gy1 + 1):
            for gx in range(gx0, gx1 + 1):
                idx = grid.index_at_xy(3, gx, gy)
                roads_by_cell.setdefault(idx, []).append((cls, geom))

    content = coastal | set(town_cells) | set(roads_by_cell)
    print(f"L3 content cells: {len(content)}")
    for idx in sorted(content):
        f = grid.frame(3, idx)
        rect = f["bounds"]
        areas = []
        if idx in coastal:
            areas.append((0x23, land_rect(f)))
            for pairs in sea_areas(f, rect):
                areas.append((0x03, pairs))
        lines = []
        for cls, geom in roads_by_cell.get(idx, []):
            for run in clip_polyline(geom, rect):
                simp = douglas_peucker(run, 15)
                if len(simp) < 2:
                    continue
                pairs = [Grid.to_rel(f, x, y) for x, y in simp]
                if all(-32768 <= p[0] <= 32767 and -32768 <= p[1] <= 32767
                       for p in pairs):
                    lines.append((0xf0, pairs))
        points = []
        for x, y, name, place in town_cells.get(idx, []):
            rx, ry = Grid.to_rel(f, x, y)
            points.append((0x2c if place == "city" else 0x2b, rx, ry,
                           [name.upper()]))
        put(3, idx, build_block(areas, lines, points))

    # shared pool of minimal blocks is placed after all content, then all
    # remaining catalogue slots point at its first block (donor pattern).
    shared_empty = (cursor + 15) & ~15
    for i in range(176):
        blobs.append((shared_empty + i * 16, MINIMAL_BLOCK))
    empty_entry = (shared_empty, 16)
    for lvl in COUNTS:
        for i, entry in enumerate(catalog[lvl]):
            if entry is None:
                catalog[lvl][i] = empty_entry

    # ----- assemble: donor shell up to the catalogue start, then the four
    # generated catalogues (contiguous, like the donor), then block data.
    donor = args.donor.read_bytes()
    header = bytearray(donor[:0x3F0])
    struct.pack_into("<4i", header, 0x08, *bounds)
    # grid descriptor block @0x3b0: four 16-byte entries, byte +3 of each
    # holds the level shift; the firmware reads shifts from here, so they
    # must match the shifts used by Grid for this bbox.
    for i, s in enumerate(shifts):
        header[0x3B0 + 16 * i + 3] = s
    body = header
    for lvl in COUNTS:
        for off, ln in catalog[lvl]:
            body += struct.pack("<II", off, ln)
    assert len(body) == BLOCKS_BASE, hex(len(body))
    data = bytearray(b"\x00" * max(cursor, shared_empty + 176 * 16))
    data[:len(body)] = body
    for off, block in blobs:
        data[off:off + len(block)] = block
    struct.pack_into("<I", data, 0x04, len(data))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bytes(data))
    print(f"wrote {args.out} ({len(data)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
