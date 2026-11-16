#!/usr/bin/env python3
"""NAV00001.DAT (Ortsverzeichnis) — reverse-engineered container tools.

Layout (verified on Teleatlas Polska Ceska 2010-2011, 15.11.2026):

    file  := header, string-pool directory, region directory, blocks*
    header (0x20 bytes):
        u16le block_size   (0x0fb2 = 4018; all blocks this size)
        u16le 0x0101       (version)
        u16le 0x0001
        u16le 0x0000
        u32le dir_size     (bytes of string-pool directory, 0x32c = 812)
        u32le region_count (0x3dc02?? -- actually 0x0003dc02: low u16
                            region_count=0x3dc02&0xffff... see below)
        u32le c            (0x02dc)
        u16le d, u16le e   (0x0002)
        u32le f            (0x0049)
        u32le g            (0x00f4)
        u32le h            (0x000a)

Real semantics recovered empirically:
    dir_size      = header[4]  (u32le)          -> string directory bytes
    block_size    = header[0]  (u16le)          -> 0x0fb2
    region_count  = header[8] & 0xffff (u16le)  -> 0x3dc02??

Wait — header bytes 8..11 = 02 dc 02 00 -> u32le = 0x0002dc02.
Low u16 = 0xdc02 = 56322 (too many regions). High u16 = 0x0002.
Empirically: 0x0fb2*? ... The directory at 0x20 has dir_size bytes
(0x32c) of packed (u16 id, u16 off) pairs.

Blocks: each block_size (0x0fb2) bytes:
    u32le block_len_with_flag (0x010140b2 -> len 0x40b2? NO --
        value is 0x010140b2: hi16=0x0101, low16=0x40b2=16562 -> this is
        the /payload/ length following the 16-byte block header)
    u16le 0x001a, u16le 0x0001, u32le 0x03000000
    u8 0x05, u24 0x005f52           (key seed / class tag 0x5f52)
    u32le d0, u32le d1              (key range: min, max key of block)
    u32le 0x000601e0                (constant)
    u16le 0x0009, u16le dir_off     (string directory offset selector)
    u16le n_runs, u16le ?           (run directory)
    then n_runs * 4 bytes directory of (delta<<2|kind) u32le:
        kind 0 -> u16le data_off, u16le count  (record run)
        kind 1 -> u16le pool_off, u16le byte_len (string pool run)
    record run data: count * 8 bytes  <u32le key, u16le a, u16le b>
        key = (y<<16)|x packed internal coordinates
    string pool run: byte_len bytes, NUL-separated cp1252 strings,
        concatenated directory-first (cross-references "X [CC], PARENT").

Blocks tile the file after the 0x20+dir_size+? region directory;
block[i] starts at region_dir_end + i*block_size... verified: first
block at 0x47d0, header+dir = 0x20+0x32c = 0x34c, region dir size
= 0x47d0-0x34c = 0x4484 = 17540 = 0x4484. 17540/?? regions...
region_count = header[8] u16le low = 0xdc02?? -> 56322 no.
Empirical: region dir entries 8 bytes: u32le first_block,
u32le last_key? 17540/8 = 2192.5 no. 17540 = 0x4484; header[8]=0x0002dc02
-- 0x2dc02>>? ... 0x4484 = 17540 = 2192*8 + 4. Possibly region_count
(u32le header[8]=0x0002dc02=187394) no.

Pragmatic choice: regions directory parse rule discovered by monotone
scan: entries are 8 bytes <u32le block_start_off, u32le range_max_key>;
block_start_off are absolute file offsets, monotone; count =
(0x47d0 - 0x34c) / 8 = 2192.625 -> NOT integral. Hmm.

Alternative: region entries 4 bytes: 17540/4 = 4385 entries.
We leave region-dir semantics OPEN; the tools below operate on blocks
located by scanning block signatures (u32le with hi16==0x0101 and
low16 in 0x1000..0x8000), which is robust.
"""
import argparse, json, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpnav2_container import NavContainer


def iter_blocks(data: bytes):
    """Decode every logical block through the TPNAV2 container."""
    import tempfile, os
    fd, name = tempfile.mkstemp(suffix=".dat")
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_bytes(data)
        c = NavContainer(tmp)
        for e in c.entries:
            blk, _, _ = c.read_block(e.logical_offset, e.logical_size)
            yield e.index, blk
    finally:
        os.unlink(tmp)


def find_unit_array(blk: bytes):
    """Locate the 8-byte unit array <u16 A, u16 B, u32 1> where B values
    are ascending (record offsets, typically 0x0C-strided). Returns
    (start, count) or (None, 0). Verified against block 0 of NAV00001."""
    best = (None, 0)
    for start in range(0x28, min(len(blk) - 32, 0x200)):
        n = 0
        prev_b = -1
        while True:
            a, b, one = struct.unpack_from("<HHI", blk, start + 8 * n)
            if one != 1 or b <= prev_b or b >= len(blk):
                break
            prev_b = b
            n += 1
        if n > best[1]:
            best = (start, n)
    return best


def parse_block(index: int, blk: bytes):
    """Parse one decoded logical block. Fields +0..+24 verified by
    hexdump; unit array and 12-byte records verified empirically."""
    tag = struct.unpack_from("<I", blk, 16)[0]
    f20, f24 = struct.unpack_from("<II", blk, 20)
    ustart, units = find_unit_array(blk)
    records = []
    if ustart is not None:
        for k in range(units):
            a, b, one = struct.unpack_from("<HHI", blk, ustart + 8 * k)
            if b + 12 > len(blk):
                break
            c0, ra, rb, key = struct.unpack_from("<IHHI", blk, b)
            records.append({"unit_a": a, "off": b, "c0": c0,
                            "u16": [ra, rb], "key": key})
    # heuristic: printable cp1252 runs >= 5 bytes = pool strings
    strs = []
    i = 0
    while i < len(blk):
        if 32 <= blk[i] < 127 or blk[i] in (0xd9,):
            j = i
            while j < len(blk) and (32 <= blk[j] < 127 or blk[j] in (0xd9,)):
                j += 1
            if j - i >= 5:
                strs.append(blk[i:j].decode("cp1252", "replace"))
            i = j
        else:
            i += 1
    return {"index": index, "size": len(blk), "tag": tag,
            "f20": f20, "f24": f24,
            "unit_start": ustart, "unit_count": units,
            "records": records, "strings": strs}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--json", help="dump parsed blocks to JSON")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    data = open(args.file, "rb").read()
    parsed = []
    total_recs = 0
    total_strs = 0
    for index, blk in iter_blocks(data):
        b = parse_block(index, blk)
        parsed.append(b)
        total_recs += len(b["records"])
        total_strs += len(b["strings"])
        if not args.json and not args.stats:
            print(f"  block {index:3d} size={b['size']:6d} tag={b['tag']:#x} "
                  f"f20={b['f20']:#x} f24={b['f24']:#x} units={b['unit_count']:5d} "
                  f"recs={len(b['records']):5d} strs={len(b['strings']):4d}")
    print(f"total: {len(parsed)} blocks, {total_recs} records, "
          f"{total_strs} strings")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(parsed, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
