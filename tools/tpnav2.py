#!/usr/bin/env python3
"""TPNAV2 block decompressor recovered from NAVECE_M.EXE V810 code.

Evidence: functions 0xffd5dcb4, 0xffd5ddc2 and 0xffd5de16.
The compressed stream has a control-bit stream and a separate literal stream.
This module does not yet parse the outer NAV container or its remapping table.
"""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path


class NavDecodeError(ValueError):
    """Raised when a compressed NAV block is malformed or truncated."""


@dataclass(frozen=True)
class DecodeStats:
    output_size: int
    literal_offset: int
    control_bytes_read: int
    literal_bytes_read: int
    tokens: int
    literal_tokens: int
    backreference_tokens: int


class ControlBitReader:
    """LSB-first control words, with a 16-bit first word for small outputs."""

    def __init__(self, data: bytes, output_size: int):
        if len(data) < 4:
            raise NavDecodeError("compressed block is shorter than its first word")
        self.data = data
        first_word = struct.unpack_from("<I", data, 0)[0]
        self.small_output = output_size <= 0x10000
        self.literal_offset = (first_word >> 16) if self.small_output else first_word
        self.word = first_word
        self.bit_pos = 0
        self.bits_left = 16 if self.small_output else 32
        self.next_word_offset = 4

    def read(self, count: int) -> int:
        if not 0 <= count <= 32:
            raise NavDecodeError(f"invalid control-bit read width: {count}")
        value = 0
        value_shift = 0
        needed = count
        while needed:
            if self.bits_left == 0:
                if self.next_word_offset + 4 > len(self.data):
                    raise NavDecodeError("truncated control-bit stream")
                self.word = struct.unpack_from("<I", self.data, self.next_word_offset)[0]
                self.next_word_offset += 4
                self.bit_pos = 0
                self.bits_left = 32
            take = min(needed, self.bits_left)
            part = (self.word >> self.bit_pos) & ((1 << take) - 1)
            value |= part << value_shift
            value_shift += take
            self.bit_pos += take
            self.bits_left -= take
            needed -= take
        return value

    @property
    def bytes_read(self) -> int:
        return self.next_word_offset


def decompress(data: bytes, output_size: int) -> tuple[bytes, DecodeStats]:
    """Decompress one physical TPNAV2 block to exactly output_size bytes."""
    if output_size < 0:
        raise NavDecodeError("negative output size")
    bits = ControlBitReader(data, output_size)
    if bits.literal_offset > len(data):
        raise NavDecodeError(
            f"literal offset 0x{bits.literal_offset:x} exceeds compressed block size 0x{len(data):x}"
        )
    literal_pos = bits.literal_offset
    output = bytearray()
    tokens = literal_tokens = backreference_tokens = 0

    def require_output(count: int) -> None:
        if len(output) + count > output_size:
            raise NavDecodeError(
                f"token overruns output: {len(output)} + {count} > {output_size}"
            )

    def copy_literals(count: int) -> None:
        nonlocal literal_pos
        require_output(count)
        if literal_pos + count > len(data):
            raise NavDecodeError("truncated literal stream")
        output.extend(data[literal_pos:literal_pos + count])
        literal_pos += count

    def copy_backreference(distance: int, count: int) -> None:
        require_output(count)
        if distance <= 0 or distance > len(output):
            raise NavDecodeError(
                f"invalid backreference distance {distance} at output offset {len(output)}"
            )
        # The V810 copy routine advances byte by byte; overlapping matches repeat.
        for _ in range(count):
            output.append(output[-distance])

    while len(output) < output_size:
        tokens += 1
        token = bits.read(2)
        if token == 0:
            copy_literals(1)
            literal_tokens += 1
        elif token == 1:
            count = bits.read(2) + 2
            distance = bits.read(4) * 2 + 2
            copy_backreference(distance, count)
            backreference_tokens += 1
        elif token == 2:
            if bits.read(1) == 0:
                count = bits.read(2) + 2
                distance = bits.read(11) * 2 + 0x222
                copy_backreference(distance, count)
                backreference_tokens += 1
            else:
                count = bits.read(3) + 2
                copy_literals(count)
                literal_tokens += 1
        else:
            if bits.read(1) == 0:
                count = bits.read(2) + 2
                distance = bits.read(8) * 2 + 0x22
                copy_backreference(distance, count)
                backreference_tokens += 1
            elif bits.read(1) == 0:
                count = bits.read(5) + 6
                distance = bits.read(4) * 2 + 2
                copy_backreference(distance, count)
                backreference_tokens += 1
            elif bits.read(1) == 0:
                count = bits.read(5) + 6
                distance = bits.read(8) * 2 + 0x22
                copy_backreference(distance, count)
                backreference_tokens += 1
            elif bits.read(1) == 0:
                count = bits.read(5) + 6
                distance = bits.read(11) * 2 + 0x222
                copy_backreference(distance, count)
                backreference_tokens += 1
            else:
                count = bits.read(8) + 10
                copy_literals(count)
                literal_tokens += 1

    stats = DecodeStats(
        output_size=output_size,
        literal_offset=bits.literal_offset,
        control_bytes_read=bits.bytes_read,
        literal_bytes_read=literal_pos - bits.literal_offset,
        tokens=tokens,
        literal_tokens=literal_tokens,
        backreference_tokens=backreference_tokens,
    )
    return bytes(output), stats


def parse_int(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode one TPNAV2 compressed block")
    parser.add_argument("file", type=Path)
    parser.add_argument("--offset", type=parse_int, required=True, help="physical block offset")
    parser.add_argument("--output-size", type=parse_int, required=True, help="logical decoded size")
    parser.add_argument("--compressed-size", type=parse_int, help="physical size; default: rest of file")
    parser.add_argument("--output", type=Path, help="write decoded bytes to this file")
    args = parser.parse_args()

    source = args.file.read_bytes()
    end = len(source) if args.compressed_size is None else args.offset + args.compressed_size
    if args.offset < 0 or end < args.offset or end > len(source):
        parser.error("requested compressed range lies outside the input file")
    decoded, stats = decompress(source[args.offset:end], args.output_size)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(decoded)
    result = {
        "file": str(args.file),
        "offset": args.offset,
        "compressed_range_size": end - args.offset,
        "stats": stats.__dict__,
        "decoded_hex": decoded[:128].hex(" "),
        "decoded_ascii": "".join(chr(value) if 32 <= value < 127 else "." for value in decoded[:128]),
        "output": str(args.output) if args.output else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
