#!/usr/bin/env python3
"""Parse the TPNAV2 remapping table and optionally decode logical blocks."""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass, asdict
from pathlib import Path

from tpnav2 import NavDecodeError, decompress


class NavContainerError(ValueError):
    pass


@dataclass(frozen=True)
class RemapEntry:
    index: int
    logical_offset: int
    logical_size: int
    field06: int
    physical_offset: int
    physical_size: int
    compression_flag: int


class NavContainer:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        if len(self.data) < 26:
            raise NavContainerError("file is shorter than the 26-byte primary header")
        self.primary_header = self.data[:26]
        self.table_header_offset = struct.unpack_from("<I", self.data, 4)[0]
        if self.table_header_offset + 16 > len(self.data):
            raise NavContainerError("remapping header lies outside the file")
        (self.entry_count, self.table_offset, self.header_field08,
         self.header_field0c) = struct.unpack_from("<IIII", self.data, self.table_header_offset)
        table_size = self.entry_count * 16
        if self.table_offset + table_size > len(self.data):
            raise NavContainerError("remapping table lies outside the file")
        self.entries = []
        for index in range(self.entry_count):
            values = struct.unpack_from("<IHHIHH", self.data, self.table_offset + index * 16)
            entry = RemapEntry(index, *values)
            if entry.physical_offset + entry.physical_size > len(self.data):
                raise NavContainerError(f"physical range of entry {index} lies outside the file")
            self.entries.append(entry)

    def find_entry(self, logical_offset: int, logical_size: int) -> RemapEntry:
        # Firmware searches from the end and takes the first exact offset/size match.
        for entry in reversed(self.entries):
            if entry.logical_offset == logical_offset and entry.logical_size == logical_size:
                return entry
        raise NavContainerError(
            f"no remapping entry for logical offset=0x{logical_offset:x}, size=0x{logical_size:x}"
        )

    def read_block(self, logical_offset: int, logical_size: int) -> tuple[bytes, RemapEntry, dict]:
        entry = self.find_entry(logical_offset, logical_size)
        physical = self.data[entry.physical_offset:entry.physical_offset + entry.physical_size]
        if entry.compression_flag == 0:
            decoded = physical
            stats = None
        else:
            decoded, decode_stats = decompress(physical, logical_size)
            stats = asdict(decode_stats)
        if len(decoded) != logical_size:
            raise NavContainerError(
                f"entry {entry.index}: decoded size {len(decoded)} != logical size {logical_size}"
            )
        declared_size = struct.unpack_from("<H", decoded, 0)[0] if len(decoded) >= 2 else None
        return decoded, entry, {
            "decode_stats": stats,
            "declared_size": declared_size,
            "declared_size_matches": declared_size == logical_size,
        }

    def summary(self) -> dict:
        compressed = sum(entry.compression_flag != 0 for entry in self.entries)
        return {
            "file": str(self.path),
            "file_size": len(self.data),
            "primary_header_hex": self.primary_header.hex(" "),
            "table_header_offset": self.table_header_offset,
            "entry_count": self.entry_count,
            "table_offset": self.table_offset,
            "table_size": self.entry_count * 16,
            "header_field08": self.header_field08,
            "header_field0c": self.header_field0c,
            "compressed_entries": compressed,
            "uncompressed_entries": self.entry_count - compressed,
            "compression_flags": sorted(set(entry.compression_flag for entry in self.entries)),
            "first_entry": asdict(self.entries[0]) if self.entries else None,
            "last_entry": asdict(self.entries[-1]) if self.entries else None,
        }


def parse_int(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--logical-offset", type=parse_int, default=0)
    parser.add_argument("--logical-size", type=parse_int, default=0x1A)
    parser.add_argument("--decode-first", action="store_true", help="decode the selected logical block")
    parser.add_argument("--output-dir", type=Path, help="optionally save each selected decoded block")
    parser.add_argument("--report", type=Path, help="write the full JSON report")
    args = parser.parse_args()

    results = []
    for path in args.files:
        item = {"file": str(path)}
        try:
            container = NavContainer(path)
            item.update(container.summary())
            if args.decode_first:
                decoded, entry, details = container.read_block(args.logical_offset, args.logical_size)
                item["selected_entry"] = asdict(entry)
                item.update(details)
                item["decoded_hex_first_256"] = decoded[:256].hex(" ")
                item["decoded_size"] = len(decoded)
                if args.output_dir:
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                    output = args.output_dir / (path.parent.name + "-" + path.stem + ".bin")
                    output.write_bytes(decoded)
                    item["decoded_output"] = str(output)
        except (NavContainerError, NavDecodeError, OSError, struct.error) as exc:
            item["error"] = str(exc)
        results.append(item)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
