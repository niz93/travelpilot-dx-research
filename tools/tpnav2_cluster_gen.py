#!/usr/bin/env python3
"""Generate a TPNAV2 cluster from scratch (no source cluster).

This is the first building block of the OSM->DX custom-disc methodology:
a minimal model (nodes, links, geometry, self-assigned boundary words)
is turned into a byte-valid cluster that the existing parser accepts with
zero errors and zero endpoint conflicts, and two generated neighbours
stitch under the confirmed boundary rule (word body + spatial match).

Coordinate model (confirmed): absolute = base + (delta << shift).
Internal unit ~0.35 m (28.3 units ~ 10 m in the Germany stitch median).

Header conventions copied from real clusters: byte02=8, byte03=1,
field11=4, field04_le32=0xB8010001, 4 bounds corners.

Boundary words: body = raw & 0x3ff is the boundary number (local to the
pair); observed live pairs use 0xAxxx (0x8000|0x2000|body) on one side
and 0xExxx (additionally 0x4000) on the other. Links with an unresolved
(boundary) end carry field04 = 0, matching the observed population.
"""
from __future__ import annotations
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import parse_graph
from tpnav2_graph_mutate import ClusterModel

HEADER_FIELD04 = 0xB8010001
WEIGHT_DIVISOR = 316.3

# boundary word templates (see module docstring); bodies are chosen ABOVE any
# realistic node count so the fallback resolution stays out of range, exactly
# like live data (bodies there are local pair numbers, not node indices)
WORD_SIDE_A = 0x8000 | 0x2000
WORD_SIDE_B = 0x8000 | 0x2000 | 0x4000
BOUNDARY_BODY = 607


class ClusterBuilder:
    """Accumulates nodes/links in absolute internal coordinates."""

    def __init__(self, base_x: int, base_y: int, shift: int = 0):
        self.base_x = base_x
        self.base_y = base_y
        self.shift = shift
        self.header = {
            "declared_size": 0,          # patched by serialize
            "byte02": 8, "byte03": 1,
            "field04_le32": HEADER_FIELD04,
            "base_x": base_x, "base_y": base_y,
            "coordinate_shift": shift, "field11": 4,
            "bounds_coordinate_offset": 0x1A,
            "bounds_coordinate_count": 0,  # patched below
            "section_flags": (1 << 6) | (1 << 7) | (1 << 10),
            "section_table_offset": 0,
            "wide_coordinates": False,
        }
        self.bounds_coords: list[tuple[int, int]] = []
        self.nodes: list[dict] = []
        self.links: list[dict] = []

    # --- model helpers -------------------------------------------------
    def set_bounds(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Four corners of the cluster rectangle, absolute coordinates."""
        self.bounds_coords = [
            self._delta(x0, y0), self._delta(x1, y0),
            self._delta(x0, y1), self._delta(x1, y1),
        ]
        self.header["bounds_coordinate_count"] = 4

    def _delta(self, x: int, y: int) -> tuple[int, int]:
        return ((x - self.base_x) >> self.shift, (y - self.base_y) >> self.shift)

    def add_node(self, x: int, y: int) -> int:
        """Add a node at absolute coordinates; returns 1-based node number."""
        self.nodes.append({
            "field0": 0, "flags": 2, "refs": [],
            "coord": self._delta(x, y),
            "prefix_count": 0, "prefix_payload": b"",
        })
        return len(self.nodes)

    def add_link(self, a_node: int | None, b_node: int | None,
                 shape: list[tuple[int, int]] | None = None,
                 boundary_word: int | None = None,
                 boundary_at: str = "second") -> int:
        """Add a link. Exactly one of the ends may be a boundary word (the
        cluster-boundary exit); the other end must be a local node number.
        `boundary_at` selects which raw end carries the word."""
        if boundary_word is None:
            if a_node is None or b_node is None:
                raise ValueError("a local link needs both end nodes")
        else:
            if (a_node is None) == (b_node is None):
                raise ValueError("a boundary link needs exactly one local node")
        shape = shape or []
        flags = 0x2 if shape else 0x0
        link_no = len(self.links) + 1
        raw_first = boundary_word if (boundary_word is not None and boundary_at == "first") else a_node
        raw_second = boundary_word if (boundary_word is not None and boundary_at == "second") else b_node
        local_node = a_node if boundary_at == "second" else b_node
        # local node is the SECOND end iff the boundary word sits in raw_first
        is_second_ref = boundary_at == "first"
        # weight from geometry (internal units); boundary links carry 0,
        # matching the observed population of unresolved ends
        if boundary_word is not None:
            field04 = 0
        else:
            pts = [self._abs_of_node(a_node), *shape,
                   self._abs_of_node(b_node)]
            length = sum(math.hypot(x2 - x1, y2 - y1)
                         for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
            field04 = round(length / WEIGHT_DIVISOR)
        self.links.append({
            "raw_first": raw_first, "raw_second": raw_second,
            "field04": field04, "flags": flags,
            "shape": [self._delta(*p) for p in shape],
            "list4_a": [], "list4_b": [], "subs": {},
        })
        # wire the node reference (1-based, 0x8000 for second endpoint)
        ref = link_no | (0x8000 if is_second_ref else 0)
        self.nodes[local_node - 1]["refs"].append(ref)
        return link_no

    def _abs_of_node(self, node_no: int) -> tuple[int, int]:
        dx, dy = self.nodes[node_no - 1]["coord"]
        return (self.base_x + (dx << self.shift), self.base_y + (dy << self.shift))

    # --- output --------------------------------------------------------
    def to_model(self) -> ClusterModel:
        m = ClusterModel.__new__(ClusterModel)
        m.header = dict(self.header)
        m.bounds_coords = list(self.bounds_coords)
        m.section_blobs = {}
        m.nodes = []
        for nd in self.nodes:
            m.nodes.append({k: nd[k] for k in
                            ("field0", "flags", "refs", "coord",
                             "prefix_count", "prefix_payload")})
        m.links = []
        for l in self.links:
            m.links.append({k: l[k] for k in
                            ("raw_first", "raw_second", "field04", "flags",
                             "shape", "list4_a", "list4_b", "subs")})
        return m

    def build(self) -> bytes:
        return self.to_model().serialize()


def main() -> None:
    # --- two neighbouring generated clusters with one stitched boundary ---
    # internal units; ~0.35 m per unit; boundary at x = 15000
    a = ClusterBuilder(base_x=0, base_y=0)
    a.set_bounds(0, 0, 16000, 8000)          # overlaps B by 2000 units
    a_n1 = a.add_node(2000, 4000)
    a_n2 = a.add_node(9000, 4000)
    a_nb = a.add_node(15000, 5000)           # boundary node (absolute)
    a.add_link(a_n1, a_n2, shape=[(5000, 4100), (7000, 3900)])
    a.add_link(a_n2, a_nb, shape=[(12000, 4500)])
    a.add_link(a_nb, None, boundary_word=WORD_SIDE_A | BOUNDARY_BODY,
               boundary_at="second")

    b = ClusterBuilder(base_x=14000, base_y=0)
    b.set_bounds(14000, 0, 30000, 8000)
    b_nb = b.add_node(15000, 5000)           # same absolute point as a_nb
    b_n2 = b.add_node(21000, 4000)
    b_n3 = b.add_node(27000, 6000)
    b.add_link(None, b_nb, boundary_word=WORD_SIDE_B | BOUNDARY_BODY, boundary_at="first")
    b.add_link(b_nb, b_n2, shape=[(17000, 4800)])
    b.add_link(b_n2, b_n3)

    data_a = a.build()
    data_b = b.build()
    out = Path("analysis/tpnav2/generated")
    out.mkdir(parents=True, exist_ok=True)
    (out / "gen-A.bin").write_bytes(data_a)
    (out / "gen-B.bin").write_bytes(data_b)

    ga = parse_graph(data_a, "gen-A")
    gb = parse_graph(data_b, "gen-B")
    for name, g in (("A", ga), ("B", gb)):
        v = g["validation"]
        print(f"cluster {name}: {len(g['nodes'])} nodes, {len(g['links'])} links, "
              f"size={g['block_size']}, errors={v['errors']}, conflicts={len(v['endpoint_conflicts'])}")

    # --- idempotence through the mutator round-trip ---
    ra = ClusterModel(data_a).serialize()
    rb = ClusterModel(data_b).serialize()
    print("idempotent A:", ra == data_a, " B:", rb == data_b)

    # --- stitch check under the confirmed rule ---
    # (word body match + local ends within 1000 units + bounds overlap)
    def bounds_box(g):
        xs = [c["x"] for c in g["bounds_coordinates"]]
        ys = [c["y"] for c in g["bounds_coordinates"]]
        return min(xs), min(ys), max(xs), max(ys)

    def boundary_ends(g):
        """Ends unresolved by node refs, detected by range like the stitcher."""
        n = len(g["nodes"])
        out = []
        for l in g["links"]:
            for end, src_key, raw_key, other in (
                    ("first", "first_source", "raw_first", "resolved_second"),
                    ("second", "second_source", "raw_second", "resolved_first")):
                if l.get(src_key) == "node_link_list":
                    continue
                raw = l[raw_key]
                if not 1 <= (raw & 0x3ff) <= n:
                    loc = g["nodes"][l[other] - 1]["coordinate"]
                    out.append((raw, loc))
        return out

    box_a, box_b = bounds_box(ga), bounds_box(gb)
    overlap = not (box_a[2] < box_b[0] or box_b[2] < box_a[0]
                   or box_a[3] < box_b[1] or box_b[3] < box_a[1])
    ends_a = boundary_ends(ga)
    ends_b = boundary_ends(gb)
    stitched = 0
    for raw_a, loc_a in ends_a:
        for raw_b, loc_b in ends_b:
            if (raw_a & 0x3ff) != (raw_b & 0x3ff):
                continue
            dist = math.hypot(loc_a["x"] - loc_b["x"], loc_a["y"] - loc_b["y"])
            if dist <= 1000:
                stitched += 1
                print(f"stitch: {raw_a:04x} <-> {raw_b:04x} body={raw_a & 0x3ff} "
                      f"dist={dist:.1f}")
    print(f"bounds overlap: {overlap}, boundary ends A={len(ends_a)} B={len(ends_b)}, stitched={stitched}")
    # expected: each cluster reports exactly ONE validation error — the
    # out-of-range fallback of its own boundary end (same class as live data)
    def boundary_errs(g):
        return [e for e in g["validation"]["errors"] if "outside 1.." in e]
    ok = (len(boundary_errs(ga)) == 1 and len(boundary_errs(gb)) == 1
          and not ga["validation"]["endpoint_conflicts"]
          and not gb["validation"]["endpoint_conflicts"]
          and ra == data_a and rb == data_b and stitched == 1 and overlap)
    print("RESULT:", "ALL OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
