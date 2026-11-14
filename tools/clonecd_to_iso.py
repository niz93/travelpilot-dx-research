#!/usr/bin/env python3
"""Convert a CloneCD Mode 1/2352 .img data track to a 2048-byte-sector ISO.

The input is never modified. The script validates the CD sync pattern and mode
byte before copying each sector's 2048-byte user-data area.
"""
from __future__ import annotations

import argparse
from pathlib import Path

RAW_SECTOR = 2352
ISO_SECTOR = 2048
DATA_OFFSET = 16
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


def convert(source: Path, destination: Path) -> None:
    size = source.stat().st_size
    if size % RAW_SECTOR:
        raise ValueError(
            f"{source}: size {size} is not a multiple of {RAW_SECTOR}; "
            "this is not an unfragmented Mode 1/2352 CloneCD image"
        )
    sectors = size // RAW_SECTOR
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as dst:
        for lba in range(sectors):
            sector = src.read(RAW_SECTOR)
            if len(sector) != RAW_SECTOR:
                raise OSError(f"Short read at raw sector {lba}")
            if sector[:12] != SYNC:
                raise ValueError(f"Bad CD sync pattern at raw sector {lba}")
            if sector[15] != 1:
                raise ValueError(
                    f"Expected Mode 1 at raw sector {lba}, got Mode {sector[15]}"
                )
            dst.write(sector[DATA_OFFSET : DATA_OFFSET + ISO_SECTOR])
            if lba % 50000 == 0:
                print(f"{source.name}: sector {lba}/{sectors}", flush=True)
    print(f"Created {destination} ({sectors} sectors)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    convert(args.source, args.destination)


if __name__ == "__main__":
    main()
