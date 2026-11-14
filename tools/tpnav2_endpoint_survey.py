#!/usr/bin/env python3
"""Survey unresolved TPNAV2 endpoints and their structural context."""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path

from tpnav2_graph import GraphFormatError, parse_graph


def is_candidate(block: dict) -> bool:
    sections = {item["bit"]: item for item in block.get("sections", [])}
    for bit in (6, 7, 10):
        item = sections.get(bit)
        if item is None or not item.get("known_records_in_bounds", True):
            return False
    return True


def structural_class(link: dict, endpoint: str) -> dict:
    raw = link["raw_" + endpoint]
    return {
        "raw_hex": f"0x{raw:04x}",
        "masked": raw & 0x3FF,
        "unused_mask": raw & ~0x3FF,
        "has_0x400": bool(raw & 0x0400),
        "has_0x800": bool(raw & 0x0800),
        "has_0x1000": bool(raw & 0x1000),
        "has_0x2000": bool(raw & 0x2000),
        "link_flags_hex": f"0x{link['flags']:04x}",
        "field04_le32": link["field04_le32"],
        "shape_count": len(link["shape_points"]),
        "subsection_flags": sorted(link["subsections"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--decoded-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    survey = json.loads(args.survey.read_text(encoding="utf-8"))
    files = []
    value_counter: Counter[tuple[str, str, str, int]] = Counter()
    total_blocks = 0
    total_graphs = 0
    total_unresolved = 0

    for file_result in survey["files"]:
        source = Path(file_result["file"])
        block_dir = args.decoded_dir / f"{source.parent.name}-{source.stem}"
        file_summary = {
            "file": str(source),
            "candidate_count": 0,
            "parsed_count": 0,
            "unresolved_endpoint_count": 0,
            "unresolved_blocks": 0,
            "blocks": [],
        }
        for block in file_result["blocks"]:
            if not is_candidate(block["block"]):
                continue
            file_summary["candidate_count"] += 1
            total_blocks += 1
            entry = block["entry"]
            paths = sorted(block_dir.glob(f"entry-{entry['index']:04d}-*.bin"))
            item = {"entry": entry}
            if not paths:
                item["status"] = "missing_decoded_block"
                file_summary["blocks"].append(item)
                continue
            try:
                graph = parse_graph(paths[0].read_bytes(), str(paths[0]))
            except (GraphFormatError, struct.error, OSError) as exc:
                item["status"] = "parse_error"
                item["error"] = str(exc)
                file_summary["blocks"].append(item)
                continue

            total_graphs += 1
            item["status"] = "ok"
            item["node_count"] = graph["validation"]["node_count"]
            item["link_count"] = graph["validation"]["link_count"]
            unresolved = []
            for link in graph["links"]:
                for endpoint in ("first", "second"):
                    resolved = link["resolved_" + endpoint]
                    if 1 <= resolved <= graph["validation"]["node_count"]:
                        continue
                    context = structural_class(link, endpoint)
                    context.update({
                        "endpoint": endpoint,
                        "link_index": link["index"],
                        "source": link[endpoint + "_source"],
                        "resolved_masked": resolved,
                    })
                    unresolved.append(context)
                    key = (
                        context["raw_hex"],
                        context["unused_mask_hex"] if "unused_mask_hex" in context else f"0x{context['unused_mask']:04x}",
                        context["link_flags_hex"],
                        context["shape_count"] > 0,
                    )
                    value_counter[key] += 1
            item["unresolved_endpoints"] = unresolved
            item["unresolved_endpoint_count"] = len(unresolved)
            file_summary["unresolved_endpoint_count"] += len(unresolved)
            if unresolved:
                file_summary["unresolved_blocks"] += 1
                total_unresolved += len(unresolved)
            file_summary["parsed_count"] += 1
            file_summary["blocks"].append(item)

        files.append(file_summary)
        print(
            f"{source}: candidates={file_summary['candidate_count']}, "
            f"parsed={file_summary['parsed_count']}, "
            f"unresolved={file_summary['unresolved_endpoint_count']}"
        )

    value_summary = [
        {
            "raw_hex": raw,
            "unused_mask_hex": unused,
            "link_flags_hex": flags,
            "has_shape_points": has_shape,
            "count": count,
        }
        for (raw, unused, flags, has_shape), count in value_counter.most_common()
    ]
    result = {
        "candidate_blocks": total_blocks,
        "parsed_graphs": total_graphs,
        "unresolved_endpoint_count": total_unresolved,
        "value_summary": value_summary,
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_blocks": total_blocks,
        "parsed_graphs": total_graphs,
        "unresolved_endpoint_count": total_unresolved,
        "distinct_structural_values": len(value_summary),
    }, indent=2))
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
