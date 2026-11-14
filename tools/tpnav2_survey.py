#!/usr/bin/env python3
"""Decode TPNAV2 entries and survey their common header and section tables."""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from tpnav2_container import NavContainer


KNOWN_SECTION_STRIDES = {2: 0x18, 3: 0x18, 6: 6, 7: 0x0C}


def decode_entry(container: NavContainer, entry) -> bytes:
    physical = container.data[entry.physical_offset:entry.physical_offset + entry.physical_size]
    if not entry.compression_flag:
        return physical
    decoded, _ = __import__("tpnav2").decompress(physical, entry.logical_size)
    return decoded


def parse_block(data: bytes) -> dict:
    if len(data) < 0x1A:
        return {"size": len(data), "short_header": True, "hex": data.hex(" ")}
    coord_offset, coord_count = struct.unpack_from("<HH", data, 0x12)
    flags, section_table_offset = struct.unpack_from("<HH", data, 0x16)
    coord_stride = 6 if data[2] & 0x40 else 4
    sections = []
    for bit in range(16):
        mask = 1 << bit
        if not flags & mask:
            continue
        pair_index = len(sections)
        pair_offset = section_table_offset + pair_index * 4
        item = {"bit": bit, "mask": mask, "pair_offset": pair_offset}
        if pair_offset + 4 <= len(data):
            offset, count = struct.unpack_from("<HH", data, pair_offset)
            stride = KNOWN_SECTION_STRIDES.get(bit)
            item.update({"offset": offset, "count": count, "record_stride": stride})
            if stride is not None:
                end = offset + count * stride
                item["known_records_end"] = end
                item["known_records_in_bounds"] = count == 0 or end <= len(data)
        else:
            item["pair_in_bounds"] = False
        sections.append(item)
    coord_end = coord_offset + coord_count * coord_stride
    return {
        "size": len(data),
        "short_header": False,
        "byte02": data[2],
        "byte03": data[3],
        "field04_le32": struct.unpack_from("<I", data, 4)[0],
        "base_x": struct.unpack_from("<i", data, 8)[0],
        "base_y": struct.unpack_from("<i", data, 0x0C)[0],
        "header_field0e": data[0x0E],
        "header_field0f": data[0x0F],
        "coordinate_shift": data[0x10],
        "field11": data[0x11],
        "coordinate_offset": coord_offset,
        "coordinate_count": coord_count,
        "coordinate_stride": coord_stride,
        "coordinate_records_in_bounds": coord_count == 0 or coord_end <= len(data),
        "section_flags": flags,
        "section_table_offset": section_table_offset,
        "sections": sections,
        "header_hex": data[:0x1A].hex(" "),
    }


def survey(path: Path, decoded_dir: Path | None) -> dict:
    container = NavContainer(path)
    blocks = []
    header_field_counts = Counter()
    flags_counts = Counter()
    for entry in container.entries:
        decoded = decode_entry(container, entry)
        item = {"entry": asdict(entry), "block": parse_block(decoded)}
        blocks.append(item)
        block = item["block"]
        if not block["short_header"]:
            header_field_counts[(block["header_field0e"], block["header_field0f"])] += 1
            flags_counts[block["section_flags"]] += 1
        if decoded_dir is not None:
            target_dir = decoded_dir / f"{path.parent.name}-{path.stem}"
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"entry-{entry.index:04d}-lo{entry.logical_offset:08x}.bin").write_bytes(decoded)
    return {
        "file": str(path),
        "entry_count": len(blocks),
        "header_field_0e_0f_counts": [
            {"field0e": key[0], "field0f": key[1], "count": count}
            for key, count in sorted(header_field_counts.items())
        ],
        "section_flags_counts": [
            {"flags": flags, "count": count} for flags, count in sorted(flags_counts.items())
        ],
        "blocks": blocks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decoded-dir", type=Path)
    args = parser.parse_args()
    results = [survey(path, args.decoded_dir) for path in args.files]
    report = {"files": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(f"\n{result['file']}: {result['entry_count']} entries")
        print("  raw header fields +0x0e/+0x0f:", ", ".join(
            f"0x{item['field0e']:02x}/0x{item['field0f']:02x}={item['count']}"
            for item in result["header_field_0e_0f_counts"]
        ))
        print("  flags:", ", ".join(
            f"0x{item['flags']:04x}={item['count']}" for item in result["section_flags_counts"]
        ))


if __name__ == "__main__":
    main()
