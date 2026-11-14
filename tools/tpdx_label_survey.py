#!/usr/bin/env python3
"""Survey TPMAP2 point labels across map blocks to find city tie points.

Table C points carry inline label lists (label_count labels at labels_offset).
City names give precise (internal_x, internal_y) <-> WGS84 tie pairs once
matched against known city coordinates, which then define the datum
converter.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpmap_geometry import TPMap
from tpmap_block_probe import probe_block


def survey_points(path: Path, levels: list[int]) -> dict:
    tpmap = TPMap(path)
    texts = {}
    n_points = 0
    for level in levels:
        count = tpmap.descriptors[level]["count"]
        for index in range(count):
            try:
                data, _ = tpmap.read_block(level, index)
            except Exception:
                continue
            parsed = probe_block(data, len(data), include_records=True)
            if not parsed.get("accepted"):
                continue
            frame = tpmap.tile_frame(level, index)
            for rec in parsed["tables"]["c_points"]["records"]:
                n_points += 1
                if not rec["label_count"]:
                    continue
                ax, ay = tpmap.absolute_point(frame, rec["relative_x"], rec["relative_y"])
                cursor = rec["labels_offset"]
                decoded = []
                for _ in range(rec["label_count"]):
                    if cursor >= len(data):
                        break
                    size = data[cursor]
                    if size <= 1 or cursor + size > len(data):
                        break
                    payload = data[cursor + 1:cursor + size]
                    cursor += size
                    # heuristics: text may start with a marker byte and end at NUL
                    for body in (payload, payload[1:]):
                        cut = body.split(b"\0", 1)[0]
                        if cut and all(0x20 <= b <= 0x7E for b in cut):
                            decoded.append(cut.decode("ascii"))
                            break
                        if cut and all(b >= 0x20 for b in cut):
                            decoded.append(cut.decode("latin-1", "replace"))
                            break
                for text in decoded:
                    texts.setdefault(text.strip(), []).append(
                        {"x": ax, "y": ay, "level": level, "index": index,
                         "type": rec["type"], "flags": rec["flags"]})
    return {"file": str(path), "points": n_points, "texts": texts}


def main() -> None:
    targets = [
        (Path("extracted/mre/MAP00001.MAP"), [0, 1, 2, 3]),
        (Path("extracted/germany/MAP00001.MAP"), [0, 1, 2]),
        (Path("extracted/czech_poland/MAP00001.MAP"), [0, 1, 2]),
    ]
    out = {}
    for path, levels in targets:
        if not path.exists():
            print("missing:", path)
            continue
        r = survey_points(path, levels)
        out[path.parent.name] = {"points": r["points"],
                                 "unique_texts": len(r["texts"])}
        (Path("analysis") / f"tpdx-labels-{path.parent.name}.json").write_text(
            json.dumps({"points": r["points"], "texts": r["texts"]},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        sample = sorted(r["texts"])[:40]
        print(path.parent.name, "points:", r["points"],
              "unique texts:", len(r["texts"]))
        print("  sample:", sample)


if __name__ == "__main__":
    main()
