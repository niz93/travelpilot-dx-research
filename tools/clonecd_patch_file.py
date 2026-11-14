#!/usr/bin/env python3
"""Replace one same-sized ISO file inside a copy of a CloneCD Mode 1 image.

Preserves every unaffected raw sector, refuses sectors with nonstandard service
fields, copies .ccd/.sub, and regenerates EDC/ECC only where user data changed.
This is an experimental low-level patcher, not evidence of HU compatibility.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from iso_to_clonecd import rebuild, tables


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_img", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("iso_file", help="case-insensitive ISO path, with or without ;1")
    parser.add_argument("replacement", type=Path)
    parser.add_argument("destination_img", type=Path)
    parser.add_argument("--verification", type=Path, help="JSON from iso_to_clonecd.py")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = args.destination_img.resolve()
    if args.source_img.resolve() == destination:
        parser.error("source and destination must be different; the source is never modified")
    if not args.force and (destination.exists() or destination.with_suffix(".sub").exists()
                           or destination.with_suffix(".ccd").exists()):
        parser.error("destination already exists; choose another path or use --force")
    files = json.loads(args.inventory.read_text(encoding="utf-8"))["files"]
    wanted = args.iso_file.upper().replace("\\", "/")
    if not wanted.startswith("/"):
        wanted = "/" + wanted
    matches = [entry for entry in files if entry["path"].upper().split(";")[0] == wanted]
    if len(matches) != 1:
        parser.error(f"Expected one matching ISO file, got {len(matches)}")
    entry = matches[0]
    replacement = args.replacement.read_bytes()
    if len(replacement) != entry["size"]:
        parser.error(f"Replacement must be exactly {entry['size']} bytes, got {len(replacement)}")
    first = entry["lba"]
    last = entry["lba"] + (entry["size"] + 2047) // 2048 - 1
    if args.verification:
        report = json.loads(args.verification.read_text(encoding="utf-8"))
        recorded = report.get("mismatching_sectors", [])
        if report.get("sectors_different", len(recorded)) > len(recorded):
            parser.error("Verification report is truncated; full raw-image verification is required")
        special = {item["lba"] for item in recorded}
        overlap = sorted(special.intersection(range(first, last + 1)))
        if overlap:
            parser.error(f"Refusing to regenerate special sectors: {overlap[:20]}")
    args.destination_img.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.source_img, destination)
    crc, log, mul_alpha = tables()
    changed_sectors = []
    with args.source_img.open("rb") as source, destination.open("r+b") as output:
        for lba in range(first, last + 1):
            source.seek(lba * 2352)
            raw = source.read(2352)
            if len(raw) != 2352:
                raise OSError(f"Short source at LBA {lba}")
            offset = (lba - first) * 2048
            sector_data = replacement[offset:offset + 2048]
            if len(sector_data) < 2048:
                sector_data = sector_data + raw[16 + len(sector_data):2064]
            if sector_data == raw[16:2064]:
                continue
            rebuilt = rebuild(np.frombuffer(sector_data, dtype=np.uint8)[None, :],
                              lba, crc, log, mul_alpha).tobytes()
            if raw[:16] != rebuilt[:16] or rebuilt[16:2064] != sector_data:
                raise ValueError(f"Unexpected source header or sector layout at LBA {lba}")
            output.seek(lba * 2352)
            output.write(rebuilt)
            changed_sectors.append(lba)
    companions = []
    for suffix in (".ccd", ".sub"):
        source = args.source_img.with_suffix(suffix)
        if source.is_file():
            target = destination.with_suffix(suffix)
            shutil.copyfile(source, target)
            companions.append({"file": str(target), "sha256": digest(target)})
    result = {
        "source_img": str(args.source_img), "destination_img": str(destination),
        "iso_path": entry["path"], "lba": first, "last_lba": last,
        "file_size": entry["size"], "changed_sectors": changed_sectors,
        "original_file_sha256": digest(args.replacement) if not changed_sectors else None,
        "replacement_sha256": hashlib.sha256(replacement).hexdigest(),
        "companions_preserved": companions,
        "warning": "Experimental; burning and head-unit compatibility have not been validated.",
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
