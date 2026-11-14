#!/usr/bin/env python3
"""TPNAV2 cluster mutator: parse -> mutate -> full re-layout -> serialize.

Layout contract (validated on all 128 real clusters):
    header (0x1A) + bounds coords + section table (4B per present section bit)
    small sections in bit order (0x0001..0x0008)
    [legacy gap dropped on re-layout]
    0x0040 node records (6B each)
    node subsection area:
        per node with flags&2: [prefix descriptor 4B if flags&1][link-list descriptor 4B]
        payloads: prefix payloads (count*4B), then link-ref lists (count*2B)
    0x0080 link records (12B each)
    link subsection area:
        per link with flags&0x1f: contiguous descriptor array (4B per flagged bit,
        bit order 0..4), then payloads (shape 4B/pt, list4 4B/item,
        annotations/bit2 2B/item)
    remaining sections in bit order (0x0100, 0x0200, 0x0400 node coordinates)

Node link refs are 1-based link numbers; bit 0x8000 marks the node as the
SECOND endpoint of the link. Small/unparsed sections are carried as raw byte
blobs with their original count, so sections we do not understand yet survive
mutation untouched. Prefix/annotation/bit2 payloads are carried raw; their
semantics are not yet reversed.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_graph import parse_graph


class ClusterModel:
    def __init__(self, data: bytes):
        g = parse_graph(data, "model")
        self.header = dict(g["header"])
        self.bounds_coords = [(c["delta_x"], c["delta_y"]) for c in g["bounds_coordinates"]]
        self.section_blobs = {}   # bit -> (count, bytes)
        for name, sec in g["sections"].items():
            bit = sec["bit"]
            self.section_blobs[bit] = (sec["count"], data[sec["offset"]:sec["offset"] + sec["count"] * self._stride(bit)])
        # nodes: field0, flags, refs[list of raw u16], coord(dx,dy),
        #        prefix_count, prefix_payload (raw bytes, count*4)
        self.nodes = []
        for nd in g["nodes"]:
            prefix_count, prefix_payload = 0, b""
            if nd["flags"] & 0x3 == 0x3:
                po, pc = struct.unpack_from("<HH", data, nd["subsection_base"])
                prefix_count = pc
                prefix_payload = data[po:po + pc * 4]
            self.nodes.append({
                "field0": nd["field0"], "flags": nd["flags"],
                "refs": [r["raw"] for r in nd["link_references"]],
                "coord": (nd["coordinate"]["delta_x"], nd["coordinate"]["delta_y"]),
                "prefix_count": prefix_count, "prefix_payload": prefix_payload,
            })
        # links: raw_first, raw_second, field04, flags, shape points, list4,
        #        subs: bit -> (count, raw payload bytes)
        self.links = []
        for l in g["links"]:
            subs = {}
            for bit, name in ((0, "annotations"), (1, "shape"), (2, "unknown_bit2"),
                              (3, "list4_a"), (4, "list4_b")):
                if not l["flags"] & (1 << bit):
                    continue
                d = l["subsections"][name]
                stride = 4 if bit in (1, 3, 4) else 2
                subs[bit] = (d["count"], data[d["offset"]:d["offset"] + d["count"] * stride])
            self.links.append({
                "raw_first": l["raw_first"], "raw_second": l["raw_second"],
                "field04": l["field04_le32"], "flags": l["flags"],
                "shape": [(p["delta_x"], p["delta_y"]) for p in l["shape_points"]],
                "list4_a": l.get("list4_a", []), "list4_b": l.get("list4_b", []),
                "subs": subs,
            })

    @staticmethod
    def _stride(bit: int) -> int:
        # known strides; small sections carried by observed span where fixed
        return {6: 6, 7: 12, 10: 4}.get(bit, 0)

    @staticmethod
    def _pack_sub_payload(bit: int, l: dict) -> bytes:
        """Payload bytes for a link subsection; raw carried bytes win."""
        if bit in l["subs"]:
            return l["subs"][bit][1]
        if bit == 1:
            return b"".join(struct.pack("<hh", *p) for p in l["shape"])
        if bit in (3, 4):
            vals = l["list4_a"] if bit == 3 else l["list4_b"]
            return b"".join(bytes.fromhex(v.replace(" ", "")) for v in vals)
        return b""

    @staticmethod
    def _sub_count(bit: int, l: dict, payload: bytes) -> int:
        if bit in l["subs"]:
            return l["subs"][bit][0]
        stride = 4 if bit in (1, 3, 4) else 2
        return len(payload) // stride

    def serialize(self) -> bytes:
        h = self.header
        wide = h["wide_coordinates"]
        if wide:
            raise NotImplementedError("wide coordinate form")
        cstride = 4
        flags16 = h["section_flags"]
        present = [b for b in range(16) if flags16 & (1 << b)]
        nsec = len(present)
        pos = 0x1A + len(self.bounds_coords) * cstride + nsec * 4
        sec_off = {}
        # --- layout pass ---
        for b in present:
            if b >= 6:
                continue
            count, blob = self.section_blobs.get(b, (0, b""))
            sec_off[b] = pos
            pos += len(blob)
        if 6 in present:
            sec_off[6] = pos
            pos += len(self.nodes) * 6
        node_chain_at = []
        for nd in self.nodes:
            node_chain_at.append(pos)
            if nd["flags"] & 2:
                pos += 4 + (4 if nd["flags"] & 1 else 0)
        node_prefix_at = []
        for nd in self.nodes:
            if nd["flags"] & 0x3 == 0x3:
                node_prefix_at.append(pos)
                pos += len(nd["prefix_payload"])
            else:
                node_prefix_at.append(None)
        node_refs_at = []
        for nd in self.nodes:
            if nd["flags"] & 2:
                node_refs_at.append(pos)
                pos += len(nd["refs"]) * 2
            else:
                node_refs_at.append(None)
        if 7 in present:
            sec_off[7] = pos
            pos += len(self.links) * 12
        link_desc_at = []
        for l in self.links:
            bits = [b for b in (0, 1, 2, 3, 4) if l["flags"] & (1 << b)]
            if bits:
                link_desc_at.append((pos, bits))
                pos += 4 * len(bits)
            else:
                link_desc_at.append((0, bits))
        link_pay_at = []
        for l in self.links:
            for bit in (0, 1, 2, 3, 4):
                if not l["flags"] & (1 << bit):
                    continue
                payload = self._pack_sub_payload(bit, l)
                link_pay_at.append((l, bit, pos, payload))
                pos += len(payload)
        for b in present:
            if b <= 7:
                continue
            sec_off[b] = pos
            if b == 10:
                pos += len(self.nodes) * 4
            else:
                count, blob = self.section_blobs.get(b, (0, b""))
                pos += len(blob)
        total = pos
        if total > 0xFFFF:
            raise ValueError("cluster exceeds 64k")
        # --- write pass ---
        buf = bytearray(total)
        struct.pack_into("<H", buf, 0, total)
        buf[2] = h["byte02"]; buf[3] = h["byte03"]
        struct.pack_into("<I", buf, 4, h["field04_le32"])
        struct.pack_into("<i", buf, 8, h["base_x"]); struct.pack_into("<i", buf, 0x0C, h["base_y"])
        buf[0x10] = h["coordinate_shift"]; buf[0x11] = h["field11"]
        struct.pack_into("<H", buf, 0x12, 0x1A)
        struct.pack_into("<H", buf, 0x14, len(self.bounds_coords))
        struct.pack_into("<H", buf, 0x16, flags16)
        struct.pack_into("<H", buf, 0x18, 0x1A + len(self.bounds_coords) * cstride)
        for i, (dx, dy) in enumerate(self.bounds_coords):
            struct.pack_into("<hh", buf, 0x1A + i * 4, dx, dy)
        table_off = 0x1A + len(self.bounds_coords) * 4
        for cursor, b in enumerate(present):
            count, blob = self.section_blobs.get(b, (0, b""))
            if b == 6:
                count = len(self.nodes)
            elif b == 7:
                count = len(self.links)
            elif b == 10:
                count = len(self.nodes)
            struct.pack_into("<HH", buf, table_off + cursor * 4, sec_off[b], count)
        for b in present:
            if b >= 6:
                continue
            count, blob = self.section_blobs.get(b, (0, b""))
            buf[sec_off[b]:sec_off[b] + len(blob)] = blob
        # nodes
        for i, nd in enumerate(self.nodes):
            struct.pack_into("<HHH", buf, sec_off[6] + i * 6,
                             nd["field0"], nd["flags"],
                             node_chain_at[i] if nd["flags"] & 2 else 0)
        for i, nd in enumerate(self.nodes):
            if nd["flags"] & 0x3 == 0x3:
                struct.pack_into("<HH", buf, node_chain_at[i],
                                 node_prefix_at[i], nd["prefix_count"])
                buf[node_prefix_at[i]:node_prefix_at[i] + len(nd["prefix_payload"])] = nd["prefix_payload"]
            if nd["flags"] & 2:
                d_off = node_chain_at[i] + (4 if nd["flags"] & 1 else 0)
                payload = b"".join(struct.pack("<H", r) for r in nd["refs"])
                struct.pack_into("<HH", buf, d_off, node_refs_at[i], len(nd["refs"]))
                buf[node_refs_at[i]:node_refs_at[i] + len(payload)] = payload
        # links
        for i, l in enumerate(self.links):
            desc_at, bits = link_desc_at[i]
            struct.pack_into("<HHIHH", buf, sec_off[7] + i * 12,
                             l["raw_first"], l["raw_second"], l["field04"],
                             l["flags"], desc_at if bits else 0)
        pay_lookup = {(id(l), bit): (off, payload) for l, bit, off, payload in link_pay_at}
        for i, l in enumerate(self.links):
            desc_at, bits = link_desc_at[i]
            for j, bit in enumerate(bits):
                off, payload = pay_lookup[(id(l), bit)]
                count = self._sub_count(bit, l, payload)
                struct.pack_into("<HH", buf, desc_at + j * 4, off, count)
                buf[off:off + len(payload)] = payload
        # remaining sections
        for b in present:
            if b <= 7:
                continue
            if b == 10:
                blob = b"".join(struct.pack("<hh", *nd["coord"]) for nd in self.nodes)
            else:
                count, blob = self.section_blobs.get(b, (0, b""))
            buf[sec_off[b]:sec_off[b] + len(blob)] = blob
        return bytes(buf)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path("analysis/tpnav2/regional-blocks/czech_poland_2010_2011-NAV20001/entry-0241-lo000b3250.bin")
    data = src.read_bytes()
    m = ClusterModel(data)
    # mutation demo: add node #12 and link #12 connecting node #11 <-> node #12.
    # Refs are 1-based; bit 0x8000 marks the node as the SECOND endpoint.
    m.nodes.append({"field0": 0, "flags": 2, "refs": [0x800C], "coord": (40, 40),
                    "prefix_count": 0, "prefix_payload": b""})
    m.links.append({"raw_first": 11, "raw_second": 12, "field04": 0,
                    "flags": 0x0, "shape": [], "list4_a": [], "list4_b": [], "subs": {}})
    m.nodes[10]["refs"].append(0xC)  # node #11 = first endpoint of link #12
    out = m.serialize()
    g = parse_graph(out, "mutated")
    print("orig size:", len(data), " mutated size:", len(out))
    print("nodes:", len(g["nodes"]), "links:", len(g["links"]))
    print("validation:", g["validation"]["errors"][:3], "conflicts:", len(g["validation"]["endpoint_conflicts"]))
    l12 = g["links"][11]
    print("link 12 resolved:", l12["resolved_first"], l12["resolved_second"],
          "sources:", l12.get("first_source"), l12.get("second_source"))


if __name__ == "__main__":
    main()
