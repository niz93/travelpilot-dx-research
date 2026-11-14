#!/usr/bin/env python3
"""Produce reproducible header, marker, and ASCII-string probes for binaries."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MARKERS = [
    b"TPNAV2",
    b"TPNAV2_COMPRESSED",
    b"TPMAP2",
    b"GDF",
    b"Copyright",
    b"collect_tmc++",
    b"write_tmc++",
    b"\x7fELF",
    b"MG3_",
    b"NG3_",
]
PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")


def hexdump(data: bytes, base: int = 0) -> str:
    lines = []
    for offset in range(0, len(data), 16):
        row = data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02x}" for byte in row)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        lines.append(f"{base + offset:08x}  {hex_part:<47}  |{ascii_part}|")
    return "\n".join(lines)


def probe(path: Path, header_size: int, string_limit: int) -> dict:
    data = path.read_bytes()
    markers = {}
    for marker in MARKERS:
        offsets = []
        start = 0
        while True:
            offset = data.find(marker, start)
            if offset < 0:
                break
            offsets.append(offset)
            start = offset + 1
            if len(offsets) >= 30:
                break
        if offsets:
            markers[marker.decode("latin-1")] = offsets
    strings = [
        {"offset": match.start(), "text": match.group().decode("ascii")}
        for match in PRINTABLE.finditer(data)
    ]
    return {
        "file": str(path),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_hex": data[:header_size].hex(),
        "header_dump": hexdump(data[:header_size]),
        "markers": markers,
        "string_count": len(strings),
        "strings": strings[:string_limit],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--header", type=int, default=512)
    parser.add_argument("--strings", type=int, default=80)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    results = [probe(path, args.header, args.strings) for path in args.files]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print("\n===", result["file"], f"({result['size']} bytes) ===")
        print(result["header_dump"])
        print("Markers:", json.dumps(result["markers"], ensure_ascii=False))
        print("First strings:")
        for item in result["strings"]:
            print(f"  {item['offset']:08x}: {item['text']}")


if __name__ == "__main__":
    main()
