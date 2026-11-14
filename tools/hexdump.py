#!/usr/bin/env python3
"""Print a bounded hexadecimal/ASCII view of a file region."""
from __future__ import annotations

import argparse
from pathlib import Path

from binary_probe import hexdump


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--offset", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--length", type=lambda value: int(value, 0), default=256)
    args = parser.parse_args()
    with args.file.open("rb") as handle:
        handle.seek(args.offset)
        data = handle.read(args.length)
    print(hexdump(data, args.offset))


if __name__ == "__main__":
    main()
