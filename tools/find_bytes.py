#!/usr/bin/env python3
"""Locate exact byte sequences supplied as hexadecimal strings."""
from pathlib import Path
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("patterns", nargs="+")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    data = args.file.read_bytes()
    for text in args.patterns:
        pattern = bytes.fromhex(text)
        matches = []
        start = 0
        while len(matches) < args.limit:
            offset = data.find(pattern, start)
            if offset < 0:
                break
            matches.append(offset)
            start = offset + 1
        print(text, " ".join(f"0x{offset:x}" for offset in matches), f"count_shown={len(matches)}")


if __name__ == "__main__":
    main()
