"""Self-contained tests that require no proprietary source disc."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tpmap_geometry import TPMap, sample_indices  # noqa: E402
from tpnav2 import decompress  # noqa: E402
from tpnav2_graph import coordinate  # noqa: E402


def synthetic_map() -> TPMap:
    tpmap = TPMap.__new__(TPMap)
    tpmap.bounds = (0, 0, 1199, 799)
    tpmap.descriptors = [
        {"configuration": bytes((0, 0, 0, 12)), "count": 1},
        {"configuration": bytes((1, 3, 4, 11)), "count": 12},
        {"configuration": bytes((2, 10, 10, 7)), "count": 1200},
        {"configuration": bytes((3, 10, 10, 4)), "count": 120000},
    ]
    return tpmap


class TPMapSyntheticTest(unittest.TestCase):
    def test_address_round_trip(self) -> None:
        tpmap = synthetic_map()
        for level in range(4):
            count = tpmap.descriptors[level]["count"]
            indices = range(count) if count <= 1200 else sample_indices(count, 512)
            for index in indices:
                x, y = tpmap.tile_xy(level, index)
                self.assertEqual(tpmap.index_at_xy(level, x, y), index)

    def test_out_of_range_grid_coordinates(self) -> None:
        tpmap = synthetic_map()
        for level in range(4):
            width, height = tpmap.grid_size(level)
            for x, y in ((-1, 0), (0, -1), (width, 0), (0, height)):
                with self.assertRaises(IndexError):
                    tpmap.index_at_xy(level, x, y)

    def test_sample_indices_cover_endpoints(self) -> None:
        self.assertEqual(sample_indices(120000, 512).__len__(), 512)
        self.assertIn(0, sample_indices(120000, 512))
        self.assertIn(119999, sample_indices(120000, 512))


class TPNAV2SyntheticTest(unittest.TestCase):
    def test_literal_only_stream(self) -> None:
        # One control word, five literal tokens. The literal stream starts at +4.
        decoded, stats = decompress(struct.pack("<HH", 0, 4) + b"ABCDE", 5)
        self.assertEqual(decoded, b"ABCDE")
        self.assertEqual(stats.literal_tokens, 5)
        self.assertEqual(stats.backreference_tokens, 0)
        self.assertEqual(stats.control_bytes_read, 4)
        self.assertEqual(stats.literal_bytes_read, 5)

    def test_wide_coordinate_layout(self) -> None:
        header = {"coordinate_shift": 2, "base_x": 100, "base_y": 200,
                  "wide_coordinates": True}
        result = coordinate(bytes((0x56, 0x34, 0x12, 0xCD, 0xAB, 0x90)), 0, header)
        self.assertEqual(result["delta_x"], 0x123456)
        self.assertEqual(result["delta_y"], 0x90ABCD)
        self.assertEqual(result["x"], 100 + (0x123456 << 2))
        self.assertEqual(result["y"], 200 + (0x90ABCD << 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
