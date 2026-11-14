#!/usr/bin/env python3
"""Run the TPNAV2 node/link parser across decoded regional survey blocks."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from tpnav2_graph import GraphFormatError, parse_graph


def is_candidate(block: dict) -> bool:
    sections = {item["bit"]: item for item in block.get("sections", [])}
    for bit in (6, 7, 10):
        item = sections.get(bit)
        if item is None or not item.get("known_records_in_bounds", True):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--decoded-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    survey = json.loads(args.survey.read_text(encoding="utf-8"))
    files = []
    for file_result in survey["files"]:
        source = Path(file_result["file"])
        block_dir = args.decoded_dir / f"{source.parent.name}-{source.stem}"
        items = []
        for block in file_result["blocks"]:
            if not is_candidate(block["block"]):
                continue
            entry = block["entry"]
            paths = sorted(block_dir.glob(f"entry-{entry['index']:04d}-*.bin"))
            item = {"entry": entry}
            if not paths:
                item["status"] = "missing_decoded_block"
            else:
                try:
                    graph = parse_graph(paths[0].read_bytes(), str(paths[0]))
                    item.update({
                        "status": "ok",
                        "logical_size": entry["logical_size"],
                        "node_count": graph["validation"]["node_count"],
                        "link_count": graph["validation"]["link_count"],
                        "node_link_reference_count": graph["validation"]["node_link_reference_count"],
                        "endpoint_conflict_count": len(graph["validation"]["endpoint_conflicts"]),
                        "error_count": len(graph["validation"]["errors"]),
                        "topologically_consistent": graph["validation"]["topologically_consistent"],
                        "errors": graph["validation"]["errors"][:20],
                    })
                except (GraphFormatError, struct.error, OSError) as exc:
                    item.update({"status": "parse_error", "error": str(exc)})
            items.append(item)
        consistent = sum(item.get("topologically_consistent", False) for item in items)
        parse_errors = sum(item["status"] != "ok" for item in items)
        files.append({
            "file": file_result["file"],
            "candidate_count": len(items),
            "consistent_count": consistent,
            "error_count": parse_errors,
            "nodes": sum(item.get("node_count", 0) for item in items),
            "links": sum(item.get("link_count", 0) for item in items),
            "node_link_references": sum(item.get("node_link_reference_count", 0) for item in items),
            "blocks": items,
        })
        print(
            f"{file_result['file']}: candidates={len(items)}, "
            f"consistent={consistent}, errors={parse_errors}"
        )
    report = {"files": files}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report={args.report}")


if __name__ == "__main__":
    main()
