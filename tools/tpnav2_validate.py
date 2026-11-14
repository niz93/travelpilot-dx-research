#!/usr/bin/env python3
"""Validate every remapped block in the supplied TPNAV2 containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import asdict
from pathlib import Path

from tpnav2 import NavDecodeError, decompress
from tpnav2_container import NavContainer, NavContainerError


def validate(path: Path, save_first_dir: Path | None = None) -> dict:
    result = {
        "file": str(path),
        "file_size": path.stat().st_size,
        "status": "ok",
        "errors": [],
        "declared_size_mismatches": [],
        "stream_boundary_mismatches": [],
    }
    try:
        container = NavContainer(path)
    except (NavContainerError, OSError, struct.error) as exc:
        result["status"] = "container_error"
        result["errors"].append(str(exc))
        return result

    result.update({
        "table_header_offset": container.table_header_offset,
        "table_offset": container.table_offset,
        "entry_count": container.entry_count,
        "compressed_entries": 0,
        "uncompressed_entries": 0,
        "logical_bytes": 0,
        "physical_bytes": 0,
        "tokens": 0,
        "literal_tokens": 0,
        "backreference_tokens": 0,
    })
    decoded_digest = hashlib.sha256()

    for entry in container.entries:
        result["logical_bytes"] += entry.logical_size
        result["physical_bytes"] += entry.physical_size
        try:
            physical = container.data[entry.physical_offset:entry.physical_offset + entry.physical_size]
            if entry.compression_flag:
                result["compressed_entries"] += 1
                decoded, stats = decompress(physical, entry.logical_size)
                result["tokens"] += stats.tokens
                result["literal_tokens"] += stats.literal_tokens
                result["backreference_tokens"] += stats.backreference_tokens
                boundary_error = []
                if stats.control_bytes_read != stats.literal_offset:
                    boundary_error.append(
                        f"control end 0x{stats.control_bytes_read:x} != literal offset 0x{stats.literal_offset:x}"
                    )
                literal_end = stats.literal_offset + stats.literal_bytes_read
                if literal_end != entry.physical_size:
                    boundary_error.append(
                        f"literal end 0x{literal_end:x} != physical size 0x{entry.physical_size:x}"
                    )
                if boundary_error:
                    result["stream_boundary_mismatches"].append({
                        "entry": entry.index, "messages": boundary_error
                    })
            else:
                result["uncompressed_entries"] += 1
                decoded = physical

            if len(decoded) != entry.logical_size:
                raise NavDecodeError(
                    f"decoded size {len(decoded)} != logical size {entry.logical_size}"
                )
            declared_size = struct.unpack_from("<H", decoded, 0)[0] if len(decoded) >= 2 else None
            if declared_size != entry.logical_size:
                result["declared_size_mismatches"].append({
                    "entry": entry.index,
                    "declared_size": declared_size,
                    "logical_size": entry.logical_size,
                })
            decoded_digest.update(decoded)
            if entry.index == 0:
                result["first_entry"] = asdict(entry)
                result["first_decoded_sha256"] = hashlib.sha256(decoded).hexdigest()
                if save_first_dir:
                    save_first_dir.mkdir(parents=True, exist_ok=True)
                    output = save_first_dir / f"{path.parent.name}-{path.stem}.bin"
                    output.write_bytes(decoded)
                    result["first_decoded_output"] = str(output)
        except (NavDecodeError, struct.error) as exc:
            result["errors"].append({"entry": entry.index, "error": str(exc)})

    result["decoded_sequence_sha256"] = decoded_digest.hexdigest()
    if result["errors"]:
        result["status"] = "decode_errors"
    result["error_count"] = len(result["errors"])
    result["declared_size_mismatch_count"] = len(result["declared_size_mismatches"])
    result["stream_boundary_mismatch_count"] = len(result["stream_boundary_mismatches"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--save-first-dir", type=Path)
    args = parser.parse_args()
    results = []
    for path in args.files:
        item = validate(path, args.save_first_dir)
        results.append(item)
        print(
            f"{path}: entries={item.get('entry_count', 0)}, "
            f"errors={item.get('error_count', len(item['errors']))}, "
            f"size_mismatches={item.get('declared_size_mismatch_count', 0)}, "
            f"boundary_mismatches={item.get('stream_boundary_mismatch_count', 0)}",
            flush=True,
        )
    report = {
        "files": results,
        "totals": {
            "file_count": len(results),
            "entries": sum(item.get("entry_count", 0) for item in results),
            "compressed_entries": sum(item.get("compressed_entries", 0) for item in results),
            "uncompressed_entries": sum(item.get("uncompressed_entries", 0) for item in results),
            "logical_bytes": sum(item.get("logical_bytes", 0) for item in results),
            "errors": sum(len(item["errors"]) for item in results),
            "declared_size_mismatches": sum(
                item.get("declared_size_mismatch_count", 0) for item in results
            ),
            "stream_boundary_mismatches": sum(
                item.get("stream_boundary_mismatch_count", 0) for item in results
            ),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
