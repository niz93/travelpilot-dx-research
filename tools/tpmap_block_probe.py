#!/usr/bin/env python3
"""Validate one TPMAP2 rendering block using the recovered V810 layout.

Block header (16 bytes, little endian):
  uint32 byte_length;
  uint16 table_a_offset, table_a_count;       // 16-byte records
  uint16 table_b_offset, table_b_count;       // 12-byte polyline records
  uint16 table_c_offset, table_c_count;       // 12-byte point records

All offsets are relative to the beginning of the block. Table A/B coordinate
arrays contain packed signed16 pairs. Table C stores one such pair inline.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

TABLE_SPECS = (
    ("a", 4, 6, 16),
    ("b_lines", 8, 10, 12),
    ("c_points", 12, 14, 12),
)


def probe_block(data: bytes, expected_length: int | None = None,
                include_records: bool = True) -> dict:
    result: dict = {
        "accepted": False,
        "reason": None,
        "coordinate_semantics": (
            "tables A and B have offsets to signed16 x/y pairs; "
            "table C has one inline signed16 x/y pair; "
            "absolute coordinates require the tile centre and level shift"
        ),
    }
    if len(data) < 16:
        result["reason"] = "block is shorter than the 16-byte header"
        return result
    block_length = struct.unpack_from("<I", data)[0]
    result["block_length"] = block_length
    if expected_length is not None and block_length != expected_length:
        result["reason"] = "block length prefix differs from the catalogue length"
        return result
    if block_length != len(data):
        result["reason"] = "block length prefix differs from bytes supplied"
        return result

    tables = {}
    for name, offset_position, count_position, stride in TABLE_SPECS:
        offset, count = struct.unpack_from("<HH", data, offset_position)
        table = {
            "offset": offset,
            "count": count,
            "stride": stride,
            "end": offset + count * stride,
        }
        if count and offset < 16:
            result["reason"] = f"table {name} has records outside the data area"
            result["tables"] = tables
            return result
        if count and table["end"] > block_length:
            result["reason"] = f"table {name} exceeds the block"
            result["tables"] = tables
            return result
        if offset >= block_length and (offset or count):
            result["reason"] = f"table {name} starts outside the block"
            result["tables"] = tables
            return result
        tables[name] = table
    result["tables"] = tables

    for table_name, table in tables.items():
        records = []
        for index in range(table["count"]):
            position = table["offset"] + index * table["stride"]
            if table_name == "a":
                flags, kind, unknown3, unknown4, data_offset, data_length, trailing = \
                    struct.unpack_from("<HBBIHHI", data, position)
                record = {
                    "index": index,
                    "flags": flags,
                    "type": kind,
                    "unknown3": unknown3,
                    "unknown4": unknown4,
                    "data_offset": data_offset,
                    "data_length": data_length,
                    "trailing_uint32": trailing,
                }
                if data_length:
                    if data_offset < 16 or data_offset + data_length > block_length:
                        result["reason"] = f"table A record {index} has an out-of-block data range"
                        return result
            elif table_name == "b_lines":
                unknown0, kind, flags, coordinate_offset, point_count, text_offset, trailing = \
                    struct.unpack_from("<HBBHHHH", data, position)
                record = {
                    "index": index,
                    "unknown0": unknown0,
                    "type": kind,
                    "flags": flags,
                    "coordinate_offset": coordinate_offset,
                    "point_count": point_count,
                    "text_offset": text_offset,
                    "trailing_uint16": trailing,
                }
                if point_count:
                    end = coordinate_offset + point_count * 4
                    if coordinate_offset < 16 or end > block_length:
                        result["reason"] = f"line record {index} has an out-of-block coordinate array"
                        return result
                if text_offset >= block_length and text_offset:
                    result["reason"] = f"line record {index} has an out-of-block text offset"
                    return result
            else:
                unknown0, kind, flags, raw_x, raw_y, labels_offset, label_count = \
                    struct.unpack_from("<HBBhhHH", data, position)
                record = {
                    "index": index,
                    "unknown0": unknown0,
                    "type": kind,
                    "flags": flags,
                    "relative_x": raw_x,
                    "relative_y": raw_y,
                    "labels_offset": labels_offset,
                    "label_count": label_count,
                }
                if label_count:
                    cursor = labels_offset
                    if cursor < 16 or cursor >= block_length:
                        result["reason"] = f"point record {index} has an invalid labels offset"
                        return result
                    for label_index in range(label_count):
                        if cursor >= block_length:
                            result["reason"] = f"point record {index} ends inside its label list"
                            return result
                        label_size = data[cursor]
                        if label_size == 0 or cursor + label_size > block_length:
                            result["reason"] = (
                                f"point record {index} label {label_index} has an invalid size"
                            )
                            return result
                        cursor += label_size
            if include_records:
                records.append(record)
        if include_records:
            table["records"] = records

    result["accepted"] = True
    result["reason"] = "code-derived header, tables, and referenced data ranges are valid"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("offset", type=lambda value: int(value, 0))
    parser.add_argument("--length", type=lambda value: int(value, 0))
    parser.add_argument("--no-records", action="store_true")
    args = parser.parse_args()
    with args.file.open("rb") as stream:
        stream.seek(args.offset)
        prefix = stream.read(4)
        if len(prefix) != 4:
            parser.error("cannot read block length")
        length = struct.unpack("<I", prefix)[0]
        if args.length is not None and args.length != length:
            parser.error(f"catalogue length {args.length:#x} differs from block prefix {length:#x}")
        stream.seek(args.offset)
        data = stream.read(length)
    print(json.dumps(probe_block(data, args.length, not args.no_records),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
