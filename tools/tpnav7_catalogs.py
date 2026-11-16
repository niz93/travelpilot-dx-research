#!/usr/bin/env python3
"""v7 typed-block builders: NAV container catalog stack (0x201/0x30d/0x104/
0x604 + stubs) for a discoverable custom region.

Reverse-engineered from donor NAV21315.DAT (CZ/PL 2010-2011), see
analysis/fw_region/REPORT.md. All typed blocks share the header convention:

    u16le total_size @0x00   0x0101 @0x02   zeros @0x04..0x0d
    u16le code @0x0e         zeros @0x10..0x15 (0x104: pool ref + size)
    u16le 0x001a @0x16       u16le record_count @0x18
    records from @0x1A

Formats (verified by donor roundtrip where noted):

0x201 mini-catalog: records <u32le logical_offset, u16le size, u16le
family_low_byte> (8B each). Area catalog: fam 0x04 -> 0x304 geometry block,
fam 0x0d -> 0x30d names block. Global catalog: fam 0x03 -> 0x403,
fam 0x08 -> 0x308, fam 0x0a -> 0x30a.

0x30d place names: records <u16le name_off, u16le coord_rec_off, u16le kind=1,
u16le aux_off, u16le aux_n> (10B each). coord_rec_off points at a 12-byte
record: coordinate (0x000c,0x000c, u32le X, u32le Y, datum internal
units) or cross-reference (0x000c,0x000a, u32le block_logical_offset,
u16le block_size, u16le 0x001a). aux (12-byte blob, semantics OPEN) is
optional; absent == (0,0). Region order: header, records, 12B coord/xref
records, NUL-separated cp1252 strings, 12B aux blobs.

0x104 city record: pool ref @0x10 (u32 logical + u16 size @0x14), 2 records
<...> @0x1a, "00 00" + name at 0x2c, geometry ref (u32 logical, u32 size) and
sibling ref (u32 logical, u16 size) in the tail. BEST EFFORT: relative layout
replicated from donor, name length shifts the tail.

0x604 region name pool: strings region then records <u32le geom_logical,
u16le, u16le> (semantics partly open). Stub-friendly.

0x30d aux blob semantics are OPEN (12 bytes replicated verbatim from donor
in roundtrip; zero-filled for generated data).
"""
from __future__ import annotations

import struct

TRANS = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def translit(name: str) -> str:
    """Cyrillic -> cp1252-safe Latin, upper case (same table as the
    analysis extractor)."""
    out = []
    for ch in name.lower():
        if ch in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя":
            out.append(ch.translate(TRANS))
        elif ch.isalnum() or ch in " -.,()":
            out.append(ch)
    return " ".join("".join(out).split()).upper()


def typed_header(code: int, count: int, total_size: int) -> bytes:
    hdr = bytearray(0x1A)
    struct.pack_into("<H", hdr, 0x00, total_size)
    struct.pack_into("<H", hdr, 0x02, 0x0101)
    struct.pack_into("<H", hdr, 0x0E, code)
    struct.pack_into("<H", hdr, 0x16, 0x001A)
    struct.pack_into("<H", hdr, 0x18, count)
    return bytes(hdr)


# ---------------------------------------------------------------- 0x201

def build_0201(records: list[tuple[int, int, int]]) -> bytes:
    """records: (logical_offset u32, size u16, family_low_byte u16)."""
    body = bytearray()
    for off, size, fam in records:
        body.extend(struct.pack("<IHH", off, size, fam))
    return typed_header(0x201, len(records), 0x1A + len(body)) + bytes(body)


def parse_0201(blk: bytes) -> list[tuple[int, int, int]]:
    n = struct.unpack_from("<H", blk, 0x18)[0]
    return [struct.unpack_from("<IHH", blk, 0x1A + i * 8)
            for i in range(n)]


# ---------------------------------------------------------------- 0x30d

COORD_REC = 0x0C       # payload kind: coordinate pair
XREF_REC = 0x0A        # payload kind: cross-reference to another block


def build_030d(entries: list[dict],
               self_offset: int | None = None) -> bytes:
    """entries: {"name": str(cp1252), "x": u32, "y": u32} for a coordinate
    record, or {"name": str, "xref": (block_logical, block_size)} for a
    cross-reference, optional "aux": 12 raw bytes.

    self_offset/self_size are required iff any entry uses xref (the xref
    payload carries the block's own logical offset)."""
    n = len(entries)
    recs_off = 0x1A
    coords_off = recs_off + n * 10
    n_coord = sum(1 for e in entries if "coord" not in e or e.get("x") is not None)
    n_aux = sum(1 for e in entries if e.get("aux"))
    # coord/xref records: 12 bytes each
    strings_off = coords_off + n * 12
    strs = bytearray()
    name_offs = {}
    for e in entries:
        raw = e["name"].encode("cp1252")
        if raw not in name_offs:
            name_offs[raw] = strings_off + len(strs)
            strs.extend(raw + b"\0")
    aux_off = strings_off + len(strs)

    out = bytearray(typed_header(0x30D, n, 0))  # size patched at end
    # pass 1: record table (10B each)
    pos_a = aux_off
    for i, e in enumerate(entries):
        name_o = name_offs[e["name"].encode("cp1252")]
        aux = e.get("aux")
        if aux is not None:
            out.extend(struct.pack("<HHHHH", name_o, coords_off + i * 12,
                                   1, pos_a, 1))
            pos_a += 12
        else:
            out.extend(struct.pack("<HHHHH", name_o, coords_off + i * 12,
                                 1, 0, 0))
    # pass 2: coordinate / cross-reference records (12B each)
    for e in entries:
        if e.get("xref") is not None:
            (boff, bsz) = e["xref"]
            out.extend(struct.pack("<HHIHH", COORD_REC, XREF_REC, boff, bsz,
                                 0x001A))
        else:
            out.extend(struct.pack("<HHII", COORD_REC, COORD_REC,
                                 e["x"], e["y"]))
    out.extend(strs)
    for e in entries:
        if e.get("aux") is not None:
            blob = e["aux"]
            out.extend(blob if len(blob) == 12 else (blob + b"\0" * 12)[:12])
    struct.pack_into("<H", out, 0x00, len(out))
    return bytes(out)


def parse_030d(blk: bytes) -> list[dict]:
    n = struct.unpack_from("<H", blk, 0x18)[0]
    entries = []
    for i in range(n):
        name_o, rec_o, kind, aux_o, aux_n = struct.unpack_from(
            "<HHHHH", blk, 0x1A + i * 10)
        name = blk[name_o:blk.index(b"\0", name_o)].decode("cp1252")
        a, b = struct.unpack_from("<HH", blk, rec_o)
        if b == COORD_REC:
            x, y = struct.unpack_from("<II", blk, rec_o + 4)
            e = {"name": name, "x": x, "y": y}
        elif b == XREF_REC:
            boff, bsz, tag = struct.unpack_from("<IHH", blk, rec_o + 4)
            e = {"name": name, "xref": (boff, bsz), "tag": tag}
        else:
            e = {"name": name, "raw_kind": b}
        if aux_n:
            e["aux"] = blk[aux_o:aux_o + 12]
        entries.append(e)
    return entries


# ---------------------------------------------------------------- 0x104

def build_0104(name: str, pool: tuple[int, int],
               geom: tuple[int, int],
               sibling: tuple[int, int]) -> bytes:
    """City record, donor-relative layout (BEST EFFORT, name-len aware).

    pool/geom/sibling: (logical_offset, size)."""
    raw = name.encode("cp1252") + b"\0"
    # fixed region: header 0..0x1A, records 0x1A..0x2A, "00 00" 0x2A..0x2C,
    # name @0x2C; geometry ref follows the name (donor-relative)
    geom_ref_at = 0x39 + (len(raw) - 9)
    total = geom_ref_at + 8 + 4 + 6 + 2
    out = bytearray(b"\0" * total)
    out[0:0x1A] = typed_header(0x104, 2, 0)
    struct.pack_into("<I", out, 0x10, pool[0])
    struct.pack_into("<H", out, 0x14, pool[1])
    # records @0x1a (16 bytes, 2x 8B): replicate donor shape
    name_end = 0x2C + len(raw)                    # "00 00" + name
    struct.pack_into("<IHH", out, 0x1A,
                     (0x2A << 16) | 4, name_end, 1)
    struct.pack_into("<IHH", out, 0x22,
                     (0x2C << 16) | 4, 0x41 + (len(raw) - 9), 1)
    out[0x2A:0x2C] = b"\0\0"
    out[0x2C:0x2C + len(raw)] = raw
    struct.pack_into("<II", out, geom_ref_at, geom[0], geom[1])
    struct.pack_into("<IH", out, geom_ref_at + 12, sibling[0], sibling[1])
    struct.pack_into("<H", out, 0x00, total)
    return bytes(out)


# ---------------------------------------------------------------- 0x604

def build_0604(names: list[str], geom: tuple[int, int]) -> bytes:
    """Region name pool: strings region + one record per name pointing at
    the region geometry block. Semantics partly OPEN (record aux fields)."""
    strs = bytearray()
    offs = []
    for nm in names:
        offs.append(0x1A + len(strs))
        strs.extend(nm.encode("cp1252") + b"\0")
    # records region starts at the next 0x200-ish boundary like the donor
    # (donor: strings 0x21..0x213, records @0x214); use 0x214 when it fits
    recs_at = max(0x1A + len(strs), 0x214)
    n = len(names)
    total = recs_at + n * 8
    out = bytearray(typed_header(0x604, n, total))
    struct.pack_into("<H", out, 0x16, total - 0x100)
    out.extend(strs)
    while len(out) < recs_at:
        out.extend(b"\0")
    for _ in names:
        out.extend(struct.pack("<IHH", geom[0], 0, 0))
    return bytes(out)


# ---------------------------------------------------------------- stubs

def build_stub(code: int) -> bytes:
    """Minimal valid empty block of a directory family (count=0)."""
    return typed_header(code, 0, 0x1A)


def self_test() -> None:
    """Roundtrip checks: 0x201/0x30d rebuild donor bytes byte-identically
    (aux blobs replicated verbatim); generated blocks re-parse."""
    recs = [(0x280, 0x29DC, 4), (0x2C5C, 0x00B4, 0x0D)]
    blk = build_0201(recs)
    assert blk == bytes.fromhex(
        "2a0001010000000000000000000001020000000000001a000200"
        "80020000dc2904005c2c0000b4000d00"), "0x201 donor mismatch"
    assert parse_0201(blk) == recs

    entries = [
        {"name": "BIELANY WROCLAWSKIE [PL]", "x": 0x0C10C7A4,
         "y": 0x244D4E21,
         "aux": bytes.fromhex("00fc08002266635e1d000000")},
        {"name": "BLEDZOW [PL]", "x": 0x0C10E323, "y": 0x244889BB,
         "aux": bytes.fromhex("b0a523003e48435364000000")},
        {"name": "WROCLAWSKIE [PL], BIELANY",
         "xref": (0x2C5C, 0xB4)},
    ]
    blk = build_030d(entries)
    donor = bytes.fromhex(
        "b4000101000000000000000000000d030000000000001a000300"
        "5c00380001009c000100750044000100a800010082005000010000000000"
        "0c000c00a4c7100c214e4d240c000c0023e3100cbb8948240c000a005c2c"
        "0000b4001a00"
        "4249454c414e592057524f434c4157534b4945205b504c5d00424c45445a"
        "4f57205b504c5d0057524f434c4157534b4945205b504c5d2c204249454c"
        "414e5900"
        "00fc08002266635e1d000000b0a523003e48435364000000")
    assert blk == donor, (
        f"0x30d donor mismatch:\n{blk.hex()}\n{donor.hex()}")
    back = parse_030d(blk)
    assert [e["name"] for e in back] == [e["name"] for e in entries]
    assert (back[0]["x"], back[0]["y"]) == (0x0C10C7A4, 0x244D4E21)
    assert back[2]["xref"] == (0x2C5C, 0xB4) and back[0]["aux"] == entries[0]["aux"]
    print("tpnav7_catalogs self-test: ALL OK")


if __name__ == "__main__":
    self_test()
