"""Regression test for the CloneCD patcher, using workspace copies only."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor"))
import pycdlib

SOURCE = ROOT / "inputs/navigation/Tschechien & Polen DX 2013_2014/PL-CZ 2013-2014.img"
INVENTORY = ROOT / "analysis/inventory/Tschechien_&_Polen_DX_2013_2014.json"
TEST = ROOT / "analysis/patch-test"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    original_file = (ROOT / "extracted/czech_poland/CONFIG.SYS").read_bytes()
    modified_file = original_file.replace(b"390.23.16:12:48", b"390.23.16:12:49")
    assert modified_file != original_file and len(modified_file) == len(original_file)
    replacement = TEST / "CONFIG_changed.SYS"
    replacement.write_bytes(modified_file)
    destination = TEST / "czech-changed.img"
    report_path = TEST / "changed-report.json"
    command = [sys.executable, str(ROOT / "tools/clonecd_patch_file.py"), str(SOURCE), str(INVENTORY),
               "CONFIG.SYS", str(replacement), str(destination), "--verification",
               str(ROOT / "analysis/czech-poland-raw-verification.json"), "--report", str(report_path), "--force"]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    report = json.loads(report_path.read_text())
    assert report["changed_sectors"] == [5037]
    lba = report["lba"]
    with SOURCE.open("rb") as original, destination.open("rb") as changed:
        original.seek(lba * 2352)
        changed.seek(lba * 2352)
        original_sector = original.read(2352)
        changed_sector = changed.read(2352)
        expected_data = modified_file + original_sector[16 + len(modified_file):2064]
        assert changed_sector[16:2064] == expected_data
        # Compare every other sector without loading the entire disc.
        original.seek(0)
        changed.seek(0)
        for sector in range(128912):
            before = original.read(2352)
            after = changed.read(2352)
            if sector != lba:
                assert before == after, f"Unexpected changed sector {sector}"
            else:
                assert before[:16] == after[:16] and before[16:16 + len(modified_file)] != after[16:16 + len(modified_file)]
    iso_path = TEST / "czech-changed.iso"
    subprocess.run([sys.executable, str(ROOT / "tools/clonecd_to_iso.py"), str(destination), str(iso_path)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    iso = pycdlib.PyCdlib()
    iso.open(str(iso_path))
    with iso.open_file_from_iso(iso_path="/CONFIG.SYS;1") as stream:
        assert stream.read() == modified_file
    iso.close()
    results = {
        "source_sha256_before_and_after": sha256(SOURCE),
        "noop_raw_sha256": sha256(TEST / "czech-poland.img"),
        "noop_sub_sha256": sha256(TEST / "czech-poland.sub"),
        "noop_iso_sha256": sha256(TEST / "czech-poland.iso"),
        "expected_source_raw_sha256": sha256(SOURCE),
        "expected_source_sub_sha256": sha256(SOURCE.with_suffix(".sub")),
        "expected_source_iso_sha256": sha256(ROOT / "iso/Tschechien_&_Polen_DX_2013_2014.iso"),
        "changed_sector": lba, "all_other_raw_sectors_identical": True,
        "changed_file_extracted_and_verified": True,
        "note": "Only a local same-length metadata patch was tested; no CD-R or HU test.",
    }
    assert results["noop_raw_sha256"] == results["expected_source_raw_sha256"]
    assert results["noop_sub_sha256"] == results["expected_source_sub_sha256"]
    assert results["noop_iso_sha256"] == results["expected_source_iso_sha256"]
    (TEST / "test-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in (destination, destination.with_suffix(".ccd"), destination.with_suffix(".sub"), iso_path):
        path.unlink()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
