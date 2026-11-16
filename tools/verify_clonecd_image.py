#!/usr/bin/env python3
"""Verify every 2352-byte sector of a CloneCD (.img) image.

Checks per sector:
  - 12-byte sync pattern
  - Mode byte (expect 1 = Mode 1 data)
  - header MSF (BCD) == absolute address (LBA + 150)
  - EDC (CRC of bytes 0..2063)
  - Reed-Solomon ECC P (bytes 12..2075) and ECC Q (bytes 12..2247)

Sectors whose stored EDC does not match the recomputed value are reported as
"weak/protected". Original TeleAtlas DX masters carry a copy-protection
signature of a few hundred EDC-corrupt sectors inside an unallocated gap
(0x55 filler), and some mastering plants also produce scattered weak sectors
from aging stampers.

Usage:
  python verify_clonecd_image.py image.img [more.img ...]

Exit status is always 0; this is a reporting tool.
Requires numpy. The ECC/EDC implementation is shared with iso_to_clonecd.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

from iso_to_clonecd import RAW, SYNC, ecc, tables

assert RAW == 2352


def verify(path: Path, max_sectors: int | None = None) -> dict:
    raw = np.fromfile(path, dtype=np.uint8)
    n = len(raw) // RAW
    if max_sectors:
        n = min(n, max_sectors)
    sectors = raw[: n * RAW].reshape(n, RAW)
    print(f"{path}: {n} sectors")
    crc, log, mul_alpha = tables()

    syncb = np.frombuffer(SYNC, dtype=np.uint8)
    sync_ok = (sectors[:, :12] == syncb).all(axis=1)
    bad_sync = np.where(~sync_ok)[0].tolist()

    ok = sync_ok.copy()
    bad_mode = np.where(ok & (sectors[:, 15] != 1))[0].tolist()

    idx = np.where(ok)[0]
    absadr = idx + 150
    m = sectors[idx, 12]
    s = sectors[idx, 13]
    f = sectors[idx, 14]
    got_m = (m >> 4) * 10 + (m & 15)
    got_s = (s >> 4) * 10 + (s & 15)
    got_f = (f >> 4) * 10 + (f & 15)
    em = (absadr // 75) // 60
    es = (absadr // 75) % 60
    ef = absadr % 75
    hdr_bad = (got_m != em) | (got_s != es) | (got_f != ef)
    bad_addr = idx[hdr_bad].tolist()

    remainder = np.zeros(n, dtype=np.uint32)
    for column in range(2064):
        remainder = (remainder >> 8) ^ crc[(remainder ^ sectors[:, column].astype(np.uint32)) & 255]
    stored = sectors[:, 2064:2068].copy().view("<u4").ravel()
    edc_bad = remainder != stored
    weak = np.where(ok & edc_bad)[0].tolist()

    good = ok & ~edc_bad
    gi = np.where(good)[0]
    bad_eccp: list[int] = []
    bad_eccq: list[int] = []
    if len(gi):
        g = sectors[gi]
        p = ecc(g[:, 12:2076], 86, 24, 2, 86, log, mul_alpha)
        bad_eccp = gi[~(p == g[:, 2076:2248]).all(axis=1)].tolist()
        q = ecc(g[:, 12:2248], 52, 43, 86, 88, log, mul_alpha)
        bad_eccq = gi[~(q == g[:, 2248:2352]).all(axis=1)].tolist()

    print(f"  bad sync:       {len(bad_sync)} {bad_sync[:8]}")
    print(f"  bad mode:       {len(bad_mode)} {bad_mode[:8]}")
    print(f"  bad header MSF: {len(bad_addr)} {bad_addr[:8]}")
    print(f"  EDC mismatch (weak/protected): {len(weak)}", end="")
    if weak:
        print(f", LBA range {weak[0]}..{weak[-1]}")
        diffs = sorted(set(np.diff(weak).tolist()))
        print(f"  weak-sector address diffs: {diffs[:16]}")
    else:
        print()
    print(f"  bad ECC P: {len(bad_eccp)} {bad_eccp[:8]}")
    print(f"  bad ECC Q: {len(bad_eccq)} {bad_eccq[:8]}")
    return {
        "sectors": n,
        "bad_sync": bad_sync,
        "bad_mode": bad_mode,
        "bad_header_address": bad_addr,
        "weak": weak,
        "bad_ecc_p": bad_eccp,
        "bad_ecc_q": bad_eccq,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--max-sectors", type=int, default=None)
    args = parser.parse_args()
    for img in args.images:
        verify(img, args.max_sectors)
        print()


if __name__ == "__main__":
    main()
