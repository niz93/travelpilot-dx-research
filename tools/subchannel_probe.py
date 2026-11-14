#!/usr/bin/env python3
"""Inspect the Q channel of a CloneCD 96-byte-per-sector .sub file."""
from pathlib import Path
import argparse
import json
import numpy as np


def crc16(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 0xFFFF if value & 0x8000 else (value << 1) & 0xFFFF
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = np.frombuffer(args.file.read_bytes(), dtype=np.uint8)
    if len(data) % 96:
        raise ValueError("Subchannel size is not a multiple of 96 bytes")
    sectors = data.reshape(-1, 8, 12)
    q = sectors[:, 1, :]
    invalid = [index for index, row in enumerate(q)
               if crc16(row[:10].tobytes()) ^ 0xFFFF != int.from_bytes(row[10:12], "big")]
    report = {
        "file": str(args.file), "sectors": len(q), "size": args.file.stat().st_size,
        "q_adr_counts": {str(value): int((q[:, 0] & 15 == value).sum()) for value in sorted(set(q[:, 0] & 15))},
        "q_crc_invalid_count": len(invalid), "q_crc_invalid_first": invalid[:100],
        "first_q_frames": [row.tobytes().hex() for row in q[:10]],
        "last_q_frames": [row.tobytes().hex() for row in q[-5:]],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
