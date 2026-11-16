#!/usr/bin/env python3
"""Build a test disc by patching a donor CloneCD image in place.

Instead of rebuilding the ISO from scratch (which loses the original disc's
copy-protection signature and LBA layout — head units reject such images),
this tool takes the pristine donor image and replaces only selected extents:

  * a NAV container region (e.g. a patched TPNAV2 file copied from a proven
    test image),
  * the MAP00001.MAP extent, with the tail of the old extent zeroed and
    EDC/ECC recomputed,
  * the ISO-9660 directory record for MAP00001.MAP (data length, both
    endiannesses).

Everything else — TOC, subchannel (.sub), weak protection sectors, firmware
executable, info files — stays byte-identical to the donor.

The .ccd and .sub companions are copied from the donor image set.

Usage example:
  python patch_donor_image.py \
      --donor source.img --donor-sub source.sub --donor-ccd source.ccd \
      --nav-patch-from patched.img --nav-lba 49204:50176 \
      --map tree/MAP00001.MAP --map-lba 52407 --map-old-sectors 15373 \
      --out krasnodar-v3.img

Coordinates (extent LBAs, sector counts) come from iso_inventory.py output
for the donor ISO. Weak/protected sectors must NOT overlap the patched
regions — verify with verify_clonecd_image.py afterwards.
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

from iso_to_clonecd import RAW, ecc, tables

assert RAW == 2352


def fix_sector(sector: np.ndarray, crc: np.ndarray, log: np.ndarray, mul_alpha: np.ndarray) -> None:
    """Recompute EDC and ECC P/Q for one 2352-byte sector in place."""
    remainder = np.zeros(1, dtype=np.uint32)
    for column in range(2064):
        remainder = (remainder >> 8) ^ crc[(remainder ^ sector[column].astype(np.uint32)) & 255]
    sector[2064:2068] = remainder.astype("<u4").view(np.uint8).reshape(4)
    sector[2068:2076] = 0
    sector[2076:2248] = ecc(sector[12:2076].reshape(1, -1), 86, 24, 2, 86, log, mul_alpha)[0]
    sector[2248:2352] = ecc(sector[12:2248].reshape(1, -1), 52, 43, 86, 88, log, mul_alpha)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--donor", required=True, type=Path, help="donor .img (CloneCD image)")
    parser.add_argument("--donor-sub", type=Path, help="donor .sub (copied to output)")
    parser.add_argument("--donor-ccd", type=Path, help="donor .ccd (copied to output)")
    parser.add_argument("--nav-patch-from", type=Path, help="image with proven NAV patch")
    parser.add_argument("--nav-lba", help="NAV region 'first:last' inclusive LBA, 1:1 with --nav-patch-from")
    parser.add_argument("--map", type=Path, help="replacement MAP00001.MAP")
    parser.add_argument("--map-lba", type=int, help="first LBA of the MAP extent")
    parser.add_argument("--map-old-sectors", type=int, help="full size of the old MAP extent in sectors")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    crc, log, mul_alpha = tables()
    out = np.fromfile(args.donor, dtype=np.uint8).reshape(-1, RAW).copy()
    n = len(out)
    print(f"donor sectors: {n}")

    if args.nav_patch_from:
        first, last = (int(x) for x in args.nav_lba.split(":"))
        patch = np.fromfile(args.nav_patch_from, dtype=np.uint8).reshape(-1, RAW)
        assert len(patch) == n, "patch image sector count differs from donor"
        out[first : last + 1] = patch[first : last + 1]
        print(f"NAV region copied: LBA {first}..{last}")

    if args.map:
        new_map = args.map.read_bytes()
        pad = (-len(new_map)) % 2048
        padded = new_map + b"\0" * pad
        new_sectors = len(padded) // 2048
        assert new_sectors <= args.map_old_sectors, "new MAP does not fit the old extent"
        region = out[args.map_lba : args.map_lba + args.map_old_sectors]
        region[:, 16:2064] = 0
        region[:new_sectors, 16 : 16 + 2048] = np.frombuffer(padded, dtype=np.uint8).reshape(-1, 2048)
        for s in range(args.map_old_sectors):
            fix_sector(region[s], crc, log, mul_alpha)
        print(f"MAP replaced: LBA {args.map_lba}..{args.map_lba + new_sectors - 1}, "
              f"tail zeroed to {args.map_lba + args.map_old_sectors - 1}")

        # update every ISO directory record naming MAP00001.MAP
        needle = b"MAP00001.MAP;1"
        occurrences = []
        for lba in range(n):
            ud = out[lba, 16:2064]
            pos = -1
            while True:
                pos = ud.find(needle, pos + 1)
                if pos < 0:
                    break
                occurrences.append((lba, pos))
        print("directory record occurrences:", occurrences)
        for lba, pos in occurrences:
            start = 16 + pos - 33  # fixed name-field offset for this record length
            assert out[lba, start] > 0, f"bad record start at LBA {lba}"
            out[lba, start + 10 : start + 14] = np.frombuffer(struct.pack("<I", len(new_map)), dtype=np.uint8)
            out[lba, start + 14 : start + 18] = np.frombuffer(struct.pack(">I", len(new_map)), dtype=np.uint8)
            fix_sector(out[lba], crc, log, mul_alpha)
            print(f"  size updated at LBA {lba} (record offset {start - 16}) -> {len(new_map)}")

    args.out.write_bytes(out.tobytes())
    print(f"written {args.out} ({args.out.stat().st_size} bytes)")

    if args.donor_sub:
        shutil.copyfile(args.donor_sub, args.out.with_suffix(".sub"))
        print("sub copied")
    if args.donor_ccd:
        shutil.copyfile(args.donor_ccd, args.out.with_suffix(".ccd"))
        print("ccd copied")


if __name__ == "__main__":
    main()
