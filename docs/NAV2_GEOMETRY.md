# NAV2xxxx.DAT geometry blocks (type 0x001a)

Reverse-engineered layout of the geometry blocks that carry road/line
geometry inside the per-region `NAV2xxxx.DAT` navigation containers of
TravelPilot DX discs. Established on `NAV24019.DAT` (Czech/Poland 2010-2011
disc), block at logical offset `0xc6870` (Warsaw test area), with the decoder
`tools/tpdx_geometry.py`. Geometry here is **not** in the TPMAP2 map file
(`MAP00001.MAP`) — it lives in the NAV containers; see
`docs/TECHNICAL_REPORT.md` §6.

## Block header (little-endian)

| Offset | Size | Meaning |
|---|---|---|
| 0x00 | u16 | declared size (equals logical size) |
| 0x02 | u16 | 0x0101 ("back_sub") |
| 0x04 | u16 | block type: **0x001a** for geometry blocks; **0x0000** for the street/tiny container block that terminates each region chain |
| 0x06 | u16 | 0x0001 |
| 0x08 | u32 | 0 |
| 0x0e | u16 | 0x0304 (code) |
| 0x10 | u32 | logical offset of a sibling block (region chain link) |
| 0x14 | u16 | size of that sibling block |
| 0x16..0x3f | — | further parameters, partially understood |

The sibling link at 0x10 chains geometry blocks of one region; the chain
terminates in a container block of type 0x0000 that holds the region's
street/tiny records and its string table.

## Segment catalog

10-byte records starting at 0x40, ordered by offset:

```
u16  offset of segment inside the block
u16  item count (coordinate pairs / link records)
u32  key (0 for pure link segments; otherwise a stable id that also appears
     in a sorted key table in the block tail region)
u16  idx (ordinal into an external table, roughly 0x7744-based)
```

## Segment record stream

- Preamble: bytes `0c 00 0c 00`.
- Then a sequence of:
  - **Coordinate pair**: u32 lon, u32 lat, degrees = value · 360 / 2³². The
    first pair of a segment is absolute; subsequent pairs were observed
    absolute as well (Warsaw test area; delta encoding not observed yet).
  - **Short node attribute**: u8 type (0x13..0x1c observed), 0x00, u16 value.
  - **Street-list attribute**: `u16 name_off, u8 0x01, u16 n, u8 k, n×u8 id`.
    The leading u16 resolves into the **string table of the block's own
    region** — confirmed by decoding real street names (e.g. Warsaw
    "Marszałkowska"). The remaining bytes select street records; `k` and the
    id-byte semantics are not fully resolved.
  - **Cross-block link**: `0c 00 0a 00`, u32 block logical offset, u16 block
    size, u16 sub-offset — the node continues in another block.
- Segment end: `01 00`.

## Street/tiny container (type 0x0000)

Fixed-size **12-byte records**; the low 16 bits of the first u32 equal the
`name_off` used by geometry-block street-list attributes, tying geometry →
streets → names together within one region.

## Decoder and caveats

`tools/tpdx_geometry.py` (imports `tools/tpnav2_container.py`) parses a block
given its logical offset and a coordinate plausibility window, and dumps
segments, attributes, and cross-block links as JSON.

- Pair/link/short-attribute decoding is solid.
- Street-list payload layout is **best-effort**: resynchronisation by
  coordinate plausibility can skip bytes; treat attribute streams from it as
  approximate.
- Open questions: semantics of the id bytes and the `k` counter in
  street-list attributes; the sorted key table in the block tail; whether
  non-first coordinate pairs are ever delta-encoded on other discs.
