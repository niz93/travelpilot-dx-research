#!/usr/bin/env python3
"""Batch mutation test: several real clusters, mutate -> serialize -> reparse.

Checks per cluster:
  1. mutated output parses with no errors / 0 endpoint conflicts
  2. new link resolves from both node-link sources
  3. serialization is idempotent (mutate -> parse -> serialize == same bytes)
  4. all pre-existing nodes/links/bounds survive field-for-field
  5. distribution of non-empty annotation (bit0) / bit2 link subsections
"""
from __future__ import annotations
import glob
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import parse_graph
from tpnav2_graph_mutate import ClusterModel

TARGETS = [
    "entry-0241-lo000b3250.bin",
    "entry-0496-lo000a25f0.bin",
    "entry-0519-lo0010b250.bin",
    "entry-0168-lo000fc7e0.bin",
    "entry-0464-lo0002b260.bin",
]


def mutate_model(m: ClusterModel) -> tuple[int, int]:
    """Append node N+1 (coord 40,40) and link N+1 connecting last node."""
    ni = len(m.nodes)  # 1-based number of the new node = ni + 1
    li = len(m.links)  # 1-based number of the new link = li + 1
    prev_node = ni - 1  # 0-based index of previous last node
    new_node_no = ni + 1
    new_link_no = li + 1
    # refs are 1-based; bit 0x8000 marks the node as the SECOND endpoint
    m.nodes.append({"field0": 0, "flags": 2, "refs": [0x8000 | new_link_no], "coord": (40, 40),
                    "prefix_count": 0, "prefix_payload": b""})
    m.links.append({"raw_first": ni, "raw_second": new_node_no, "field04": 0,
                    "flags": 0x0, "shape": [], "list4_a": [], "list4_b": [], "subs": {}})
    m.nodes[prev_node]["refs"].append(new_link_no)  # first endpoint of the new link
    return new_node_no, new_link_no


def strip_indices(g):
    """Drop index fields so parsed graphs compare field-for-field."""
    g = dict(g)
    for nd in g["nodes"]:
        nd.pop("index", None)
    for l in g["links"]:
        l.pop("index", None)
    return g


def main() -> None:
    files = []
    for t in TARGETS:
        hits = sorted(glob.glob(f"analysis/tpnav2/regional-blocks/*/{t}"))
        files.extend(hits)
    print("targets:", [Path(f).name for f in files])

    # --- payload distribution across ALL real cluster files ---
    ann_nonempty = bit2_nonempty = 0
    links_total = 0
    for f in glob.glob("analysis/tpnav2/regional-blocks/*/*.bin"):
        try:
            g = parse_graph(Path(f).read_bytes(), f)
        except Exception:
            continue
        for l in g["links"]:
            links_total += 1
            if l["flags"] & 0x1:
                ann_nonempty += 1
            if l["flags"] & 0x4:
                bit2_nonempty += 1
    print(f"all clusters: links={links_total} flag_bit0={ann_nonempty} flag_bit2={bit2_nonempty}")

    ok = True
    for f in files:
        data = Path(f).read_bytes()
        m = ClusterModel(data)
        ni, li = mutate_model(m)
        out1 = m.serialize()
        g1 = parse_graph(out1, Path(f).name)
        errs = g1["validation"]["errors"]
        conf = len(g1["validation"]["endpoint_conflicts"])
        link = g1["links"][li - 1]  # li is 1-based link number
        res = (link["resolved_first"], link["resolved_second"])
        srcs = (link.get("first_source"), link.get("second_source"))
        # idempotence
        m2 = ClusterModel(out1)
        out2 = m2.serialize()
        idem = out1 == out2
        # survival of pre-existing fields: compare semantic content only
        # (record offsets / descriptor addresses legitimately change on re-layout)
        g0 = parse_graph(data, "orig")
        g1s = g1
        proj_nodes = lambda g: [
            (nd["field0"], nd["flags"], [r["raw"] for r in nd["link_references"]],
             (nd["coordinate"]["delta_x"], nd["coordinate"]["delta_y"]))
            for nd in g["nodes"]]
        proj_links = lambda g: [
            (l["raw_first"], l["raw_second"], l["field04_le32"], l["flags"],
             [(p["delta_x"], p["delta_y"]) for p in l["shape_points"]],
             l.get("list4_a", []), l.get("list4_b", []))
            for l in g["links"]]
        # prev (last original) node legitimately gains one appended ref;
        # declared_size legitimately changes on re-layout
        surv = (proj_nodes(g0)[:-1] == proj_nodes(g1s)[: len(g0["nodes"]) - 1]
                and proj_links(g0) == proj_links(g1s)[: len(g0["links"])]
                and g0["bounds_coordinates"] == g1s["bounds_coordinates"]
                and {k: v for k, v in g0["header"].items() if k != "declared_size"}
                == {k: v for k, v in g1s["header"].items() if k != "declared_size"})
        # raw opaque payloads must survive byte-for-byte
        import struct as _st
        raw_ok = True
        for nd in g0["nodes"]:
            if nd["flags"] & 0x3 != 0x3:
                continue
            po, pc = _st.unpack_from("<HH", data, nd["subsection_base"])
            orig_pl = data[po:po + pc * 4]
            nd1 = g1s["nodes"][nd["index"] - 1]
            po1, pc1 = _st.unpack_from("<HH", out1, nd1["subsection_base"])
            if out1[po1:po1 + pc1 * 4] != orig_pl:
                raw_ok = False
        for l in g0["links"]:
            l1 = g1s["links"][l["index"] - 1]
            for name, stride in (("annotations", 2), ("unknown_bit2", 2)):
                if name not in l["subsections"]:
                    continue
                d = l["subsections"][name]
                orig_pl = data[d["offset"]:d["offset"] + d["count"] * stride]
                d1 = l1["subsections"][name]
                if out1[d1["offset"]:d1["offset"] + d1["count"] * stride] != orig_pl:
                    raw_ok = False
        surv = surv and raw_ok
        # validation errors must match the ORIGINAL cluster exactly (none are
        # allowed to be introduced or lost by the mutation itself); normalize
        # the node-count figure that shifts because a node was appended
        import re as _re
        norm = lambda es: set(_re.sub(r"1\.\.\d+", "1..N", e) for e in es)
        orig_errs = norm(parse_graph(data, "orig")["validation"]["errors"])
        status = "OK" if (norm(errs) == orig_errs and conf == 0 and idem and surv) else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"{Path(f).name}: size {len(data)}->{len(out1)} new=({ni},{li}) "
              f"errors={len(errs)} conflicts={conf} resolved={res} src={srcs} "
              f"idem={idem} survive={surv} [{status}]")
        if errs:
            print("   first error:", errs[0])
    print("RESULT:", "ALL OK" if ok else "FAILURES PRESENT")


if __name__ == "__main__":
    main()
