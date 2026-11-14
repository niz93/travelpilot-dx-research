"""Regression tests for TPMAP2 hierarchical tile addressing."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from tpmap_geometry import TPMap, sample_indices  # noqa: E402


MAP_PATHS = (
    "extracted/germany/MAP00001.MAP",
    "extracted/czech_poland/MAP00001.MAP",
    "extracted/mre/MAP00001.MAP",
    "extracted/europe_2010_2011/MAP00001.MAP",
    "extracted/czech_poland_2010_2011/MAP00001.MAP",
)


class TileAddressingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in MAP_PATHS if not (ROOT / name).is_file()]
        if missing:
            raise unittest.SkipTest(
                "Private TPMAP2 integration data are absent; run the self-contained tests in tests/."
            )
        cls.maps = {name: TPMap(ROOT / name) for name in MAP_PATHS}

    def test_index_xy_round_trip(self):
        checked = 0
        for tpmap in self.maps.values():
            for level in range(4):
                count = tpmap.descriptors[level]["count"]
                indices = range(count) if count <= 20_000 else sample_indices(count, 4096)
                for index in indices:
                    x, y = tpmap.tile_xy(level, index)
                    self.assertEqual(tpmap.index_at_xy(level, x, y), index)
                    checked += 1
        print(f"Round-trip checks: {checked}")

    def test_known_germany_neighbours(self):
        tpmap = self.maps["extracted/germany/MAP00001.MAP"]
        for centre, expected in (
            (60702, [39791, 39792, 39793, 60701, 60702, 60703, 60711, 60712, 60713]),
            (44814, [44803, 44804, 44805, 44813, 44814, 44815, 44823, 44824, 44825]),
        ):
            x, y = tpmap.tile_xy(3, centre)
            actual = [
                tpmap.index_at_xy(3, x + dx, y + dy)
                for dy in (-1, 0, 1)
                for dx in (-1, 0, 1)
            ]
            self.assertEqual(actual, expected)

    def test_coordinate_bounds(self):
        for tpmap in self.maps.values():
            for level in range(4):
                width, height = tpmap.grid_size(level)
                self.assertEqual(tpmap.index_at_xy(level, width - 1, height - 1),
                                 tpmap.descriptors[level]["count"] - 1)
                for x, y in ((-1, 0), (0, -1), (width, 0), (0, height)):
                    with self.assertRaises(IndexError):
                        tpmap.index_at_xy(level, x, y)


if __name__ == "__main__":
    unittest.main(verbosity=2)
