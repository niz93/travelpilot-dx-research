#!/usr/bin/env python3
"""Rebuild CD-ROM Mode 1/2352 sectors from a 2048-byte-sector ISO.

The input ISO is never modified. A CloneCD .img can be compared with the
rebuilt sectors without creating another large file. Subchannel data is not
part of ISO 9660 and must be retained separately.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np

RAW = 2352
ISO = 2048
CHUNK = 128
SYNC = bytes((0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0))


def bcd(value: int) -> int:
    return (value // 10) * 16 + value % 10


def tables() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    crc = np.arange(256, dtype=np.uint32)
    for _ in range(8):
        crc = np.where(crc & 1, (crc >> 1) ^ 0xD8018001, crc >> 1)
    log = np.zeros(256, dtype=np.uint8)
    multiply_alpha = np.zeros(256, dtype=np.uint8)
    for value in range(256):
        doubled = (value << 1) ^ (0x11D if value & 0x80 else 0)
        multiply_alpha[value] = doubled
        log[value ^ doubled] = value
    return crc, log, multiply_alpha


def ecc(data: np.ndarray, major: int, minor: int, multiplier: int,
        increment: int, log: np.ndarray, mul_alpha: np.ndarray) -> np.ndarray:
    size = major * minor
    majors = np.arange(major)
    indices = ((majors // 2) * multiplier + (majors & 1)
               + np.arange(minor)[:, None] * increment) % size
    ecc_a = np.zeros((len(data), major), dtype=np.uint8)
    ecc_b = np.zeros_like(ecc_a)
    for column in indices:
        temporary = data[:, column]
        ecc_a = mul_alpha[ecc_a ^ temporary]
        ecc_b ^= temporary
    parity = log[mul_alpha[ecc_a] ^ ecc_b]
    return np.concatenate((parity, parity ^ ecc_b), axis=1)


def rebuild(source: np.ndarray, first_lba: int, crc: np.ndarray,
            log: np.ndarray, mul_alpha: np.ndarray) -> np.ndarray:
    sectors = np.zeros((len(source), RAW), dtype=np.uint8)
    sectors[:, :12] = np.frombuffer(SYNC, dtype=np.uint8)
    for lba in range(first_lba, first_lba + len(source)):
        absolute = lba + 150
        sectors[lba - first_lba, 12] = bcd((absolute // 75) // 60)
        sectors[lba - first_lba, 13] = bcd((absolute // 75) % 60)
        sectors[lba - first_lba, 14] = bcd(absolute % 75)
    sectors[:, 15] = 1
    sectors[:, 16:2064] = source
    remainder = np.zeros(len(source), dtype=np.uint32)
    for column in range(2064):
        remainder = (remainder >> 8) ^ crc[(remainder ^ sectors[:, column]) & 255]
    sectors[:, 2064:2068] = remainder.astype("<u4").view(np.uint8).reshape(-1, 4)
    sectors[:, 2076:2248] = ecc(sectors[:, 12:2076], 86, 24, 2, 86,
                                 log, mul_alpha)
    sectors[:, 2248:2352] = ecc(sectors[:, 12:2248], 52, 43, 86, 88,
                                 log, mul_alpha)
    return sectors


def main() -> None:
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="ISO input")
    parser.add_argument("destination", type=Path, nargs="?", help="raw .img output")
    parser.add_argument("--verify-original", type=Path, help="compare with existing .img")
    parser.add_argument("--limit", type=int, help="process only this many sectors (test)")
    parser.add_argument("--report", type=Path, help="JSON comparison report")
    args = parser.parse_args()
    if not args.destination and not args.verify_original:
        parser.error("supply a destination and/or --verify-original")
    if args.source.stat().st_size % ISO:
        parser.error("input size is not a multiple of 2048")
    sector_count = args.source.stat().st_size // ISO
    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit must be positive")
        sector_count = min(sector_count, args.limit)
    if args.destination:
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        output = args.destination.open("wb")
    else:
        output = None
    reference = args.verify_original.open("rb") if args.verify_original else None
    fields = (("sync", 0, 12), ("header", 12, 16), ("user_data", 16, 2064),
              ("edc", 2064, 2068), ("reserved", 2068, 2076),
              ("ecc_p", 2076, 2248), ("ecc_q", 2248, 2352))
    statistics = {"source": str(args.source), "reference": str(args.verify_original) if reference else None,
                  "sectors_processed": sector_count, "sectors_identical": 0,
                  "sectors_different": 0, "mismatches_by_field": {}, "mismatching_sectors": []}
    crc, log, mul_alpha = tables()
    try:
        with args.source.open("rb") as stream:
            for first in range(0, sector_count, CHUNK):
                count = min(CHUNK, sector_count - first)
                block = stream.read(count * ISO)
                if len(block) != count * ISO:
                    raise OSError(f"Short ISO read at sector {first}")
                raw = rebuild(np.frombuffer(block, dtype=np.uint8).reshape(count, ISO),
                              first, crc, log, mul_alpha)
                if output:
                    output.write(raw.tobytes())
                if reference:
                    expected = reference.read(count * RAW)
                    if len(expected) != count * RAW:
                        raise ValueError(f"Short reference read at sector {first}")
                    difference = np.frombuffer(expected, dtype=np.uint8).reshape(count, RAW) != raw
                    for local in range(count):
                        row = difference[local]
                        if not row.any():
                            statistics["sectors_identical"] += 1
                            continue
                        statistics["sectors_different"] += 1
                        changed = []
                        for name, start, end in fields:
                            if row[start:end].any():
                                statistics["mismatches_by_field"][name] = statistics["mismatches_by_field"].get(name, 0) + 1
                                changed.append(name)
                        if len(statistics["mismatching_sectors"]) < 1000:
                            item = {"lba": first + local, "fields": changed}
                            if "edc" in changed:
                                item["original_edc"] = expected[local * RAW + 2064:local * RAW + 2068].hex()
                                item["rebuilt_edc"] = raw[local, 2064:2068].tobytes().hex()
                            statistics["mismatching_sectors"].append(item)
                if first % (CHUNK * 200) == 0:
                    print(f"Sectors {first}/{sector_count}", flush=True)
    finally:
        if output:
            output.close()
        if reference:
            reference.close()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(statistics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.report}")
    print(f"Processed {sector_count} sectors; ISO input unchanged")
    if args.destination:
        print(f"Created {args.destination}")
    if reference:
        print(f"Identical: {statistics['sectors_identical']}; different: {statistics['sectors_different']}")
        print(f"Fields with differences: {statistics['mismatches_by_field']}")


if __name__ == "__main__":
    main()
