#!/usr/bin/env python3
"""Three-way function matching across NAVECE executable generations.

Compares function bodies of the NEC V810 navigation executables found on DX
discs of different years (e.g. NAVECE 182.01 from a 2001 disc, 289.25 from a
2003 disc, 390.23 from a 2010 disc). Input is the plain-text function
manifest produced by the Ghidra post-script `FnHashExport` (one line per
function: `addr hash size name mn;mon;ics`), not JSON despite the suggested
`.json` file name.

Usage:

    python tools/fw_match_three_way.py \
        --fnmne-2001 fnmne-2001.json \
        --fnmne-2003 fnmne-2003.json \
        --fnmne-2010 fnmne-2010.json \
        --out-md fw-match3-report.md --out-json fw-match3.json

Optional:

    --gate-2010 ADDR --gate-2003 ADDR   addresses (hex, no 0x) of the
        bounds-gate function pair to trace across all three binaries
        (defaults: ffcf8b1c / ffcea6d4, the 2010/2003 pair used in this
        research).

The script reports exact-hash match percentages between generations, a
presence chain for named 2010 anchors, and fuzzy best matches
(difflib.SequenceMatcher over mnemonic streams) for 2001 functions with no
exact 2010 counterpart. Pure standard library; no third-party dependencies.
"""

import argparse
import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


def load(path):
    recs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split(" ", 4)
        if len(parts) < 5:
            continue
        addr, h, size, fname, mnem = parts
        recs.append({
            "addr": addr.split(":")[1],
            "hash": h,
            "size": int(size),
            "name": fname,
            "mn": mnem.split(";"),
        })
    return recs


def histogram(mn):
    return Counter(mn)


def fuzzy_best(rec, cands, topn=1):
    hist = histogram(rec["mn"])
    best = []
    for c in cands:
        if abs(len(c["mn"]) - len(rec["mn"])) > max(20, len(rec["mn"]) // 2):
            continue
        # cheap histogram prefilter: overlap of mnemonic distribution
        ch = c.get("_hist")
        if ch is None:
            ch = histogram(c["mn"])
            c["_hist"] = ch
        inter = sum((hist & ch).values())
        if inter < 0.5 * min(sum(hist.values()), sum(ch.values())):
            continue
        ratio = SequenceMatcher(None, rec["mn"], c["mn"]).ratio()
        best.append((ratio, c))
    best.sort(key=lambda x: -x[0])
    return best[:topn]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fnmne-2001", required=True, help="function manifest, oldest generation")
    ap.add_argument("--fnmne-2003", required=True, help="function manifest, middle generation")
    ap.add_argument("--fnmne-2010", required=True, help="function manifest, newest generation")
    ap.add_argument("--out-md", default="fw-match3-report.md")
    ap.add_argument("--out-json", default="fw-match3.json")
    ap.add_argument("--gate-2010", default="ffcf8b1c",
                    help="hex address of the bounds-gate function in the 2010 binary")
    ap.add_argument("--gate-2003", default="ffcea6d4",
                    help="hex address of the bounds-gate function in the 2003 binary")
    args = ap.parse_args()

    y1 = load(args.fnmne_2001)
    y3 = load(args.fnmne_2003)
    y0 = load(args.fnmne_2010)

    by_hash_3 = {r["hash"]: r for r in y3}
    by_hash_0 = {r["hash"]: r for r in y0}

    exact13 = [r for r in y1 if r["hash"] in by_hash_3]
    exact10 = [r for r in y1 if r["hash"] in by_hash_0]
    common_all = [r for r in y1
                  if r["hash"] in by_hash_3 and r["hash"] in by_hash_0]

    # named anchors from the newest generation propagate to the oldest via
    # the middle generation's exact chain
    anchors = [r for r in y0 if not r["name"].startswith("FUN_")]
    anchor_rows = []
    named01 = {r["name"]: r for r in y1 if not r["name"].startswith("FUN_")}
    for a in anchors:
        row = {"name2010": a["name"], "addr2010": a["addr"], "size": a["size"]}
        e3 = by_hash_3.get(a["hash"])
        if e3:
            row["addr2003"] = e3["addr"]
            e1 = next((r for r in y1 if r["hash"] == a["hash"]), None)
            row["addr2001"] = e1["addr"] if e1 else None
            row["match"] = "exact" if e1 else "exact-2003-only"
        else:
            row["match"] = "changed"
        anchor_rows.append(row)

    # the bounds-gate pair: trace exact presence in all three binaries
    gate10 = next((r for r in y0 if r["addr"] == args.gate_2010), None)
    gate03 = next((r for r in y3 if r["addr"] == args.gate_2003), None)
    gate_report = {}
    for label, g in (("2010", gate10), ("2003", gate03)):
        if not g:
            continue
        for other_label, pool in (("oldest", y1), ("middle", y3), ("newest", y0)):
            hit = next((r for r in pool if r["hash"] == g["hash"]), None)
            if hit:
                gate_report[f"{label}-exact-in-{other_label}"] = hit["addr"]
        f = fuzzy_best(g, [r for r in y1 if r["hash"] != g["hash"]], 3)
        gate_report[f"{label}-fuzzy-oldest"] = [
            {"addr": c["addr"], "sim": round(s, 3), "size": len(c["mn"])}
            for s, c in f]

    # fuzzy for all oldest-generation functions unmatched to the newest
    unmatched1 = [r for r in y1 if r["hash"] not in by_hash_0]
    fuzzy10 = {}
    for r in unmatched1:
        b = fuzzy_best(r, [c for c in y0 if c["hash"] not in by_hash_0], 1)
        if b and b[0][0] >= 0.85:
            fuzzy10[r["addr"]] = {
                "sim": round(b[0][0], 3), "name2010": b[0][1]["name"],
                "addr2010": b[0][1]["addr"], "size2001": len(r["mn"]),
                "size2010": len(b[0][1]["mn"])}

    stats = {
        "functions": {"oldest": len(y1), "middle": len(y3), "newest": len(y0)},
        "exact_oldest_in_middle": len(exact13),
        "exact_oldest_in_newest": len(exact10),
        "exact_all_three": len(common_all),
        "named_anchors_newest": len(anchors),
        "named_in_oldest_binary": len(named01),
        "gate": gate_report,
        "fuzzy_oldest_vs_newest_ge85": fuzzy10,
        "anchor_rows": anchor_rows,
    }
    Path(args.out_json).write_text(
        json.dumps(stats, indent=1, ensure_ascii=False), encoding="utf-8")

    md = ["# NAVECE three-way function match (oldest / middle / newest)", ""]
    md.append(f"- functions: oldest={len(y1)} middle={len(y3)} newest={len(y0)}")
    md.append(f"- exact: oldest∩middle={len(exact13)} ({len(exact13)*100//len(y1)}%), "
              f"oldest∩newest={len(exact10)} ({len(exact10)*100//len(y1)}%), "
              f"all three={len(common_all)}")
    md.append("")
    md.append(f"## Bounds-gate pair (newest {args.gate_2010} / middle {args.gate_2003})")
    md.append("```json")
    md.append(json.dumps(gate_report, indent=1))
    md.append("```")
    md.append("")
    md.append("## Named anchors (non-FUN symbols of the newest generation) — presence chain")
    present = sum(1 for r in anchor_rows if r.get("addr2001"))
    md.append(f"{present}/{len(anchor_rows)} anchors exact-matched into the oldest binary")
    for r in anchor_rows:
        md.append(f"- {r['name2010']} @newest {r['addr2010']} "
                  f"→ middle {r.get('addr2003','—')} → oldest {r.get('addr2001','—')} [{r['match']}]")
    md.append("")
    md.append("## Fuzzy oldest→newest (sim≥0.85, not exact)")
    for a, f in sorted(fuzzy10.items(), key=lambda x: -x[1]["sim"])[:60]:
        md.append(f"- oldest:{a} ({f['size2001']}i) ≈ {f['name2010']} @newest {f['addr2010']} "
                  f"({f['size2010']}i) sim={f['sim']}")
    Path(args.out_md).write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:8]))
    print(f"written: {args.out_md}, {args.out_json}")


if __name__ == "__main__":
    main()
