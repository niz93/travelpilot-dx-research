#!/usr/bin/env python3
"""Extract all ASCII strings with their hexadecimal file offsets."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--minimum", type=int, default=4)
    args = parser.parse_args()
    data = args.file.read_bytes()
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % args.minimum)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        for match in pattern.finditer(data):
            output.write(f"{match.start():08x}  {match.group().decode('ascii')}\n")
            count += 1
    print(f"{args.file}: wrote {count} strings to {args.output}")


if __name__ == "__main__":
    main()
