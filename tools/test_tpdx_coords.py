#!/usr/bin/env python3
"""Tests for the WGS84 <-> internal-unit converter (tools/tpdx_coords.py)."""
from __future__ import annotations
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpdx_coords import Datum, _DATUM_PATH


class DatumTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _DATUM_PATH.exists():
            raise unittest.SkipTest("analysis/tpdx-datum.json not fitted yet")
        cls.d = Datum()

    def test_roundtrip_exact(self):
        for lon, lat in [(13.405, 52.52), (21.0122, 52.2297), (-7.93, 37.02),
                         (24.94, 60.17)]:
            x, y = self.d.to_internal(lon, lat)
            lon2, lat2 = self.d.to_wgs84(x, y)
            self.assertAlmostEqual(lon, lon2, places=7)
            self.assertAlmostEqual(lat, lat2, places=7)

    def test_scale_and_known_point(self):
        # ~9.3 mm per unit N-S at the fitted scale
        m = self.d.meters_per_unit_lat()
        self.assertTrue(0.0085 < m < 0.010)
        # Berlin lands inside the Germany MAP bounds
        x, y = self.d.to_internal(13.405, 52.52)
        self.assertTrue(67_765_038 <= x <= 181_581_671)
        self.assertTrue(558_345_748 <= y <= 657_368_604)
        # Warszawa lands inside the Czech/Poland MAP bounds
        x, y = self.d.to_internal(21.0122, 52.2297)
        self.assertTrue(139_758_373 <= x <= 292_601_667)
        self.assertTrue(579_224_061 <= y <= 657_368_604)

    def test_axis_order_y_is_latitude(self):
        # increasing lat must increase Y
        _, y1 = self.d.to_internal(10.0, 40.0)
        _, y2 = self.d.to_internal(10.0, 55.0)
        self.assertLess(y1, y2)

    def test_link_weight_consistency(self):
        # the confirmed rule: field04 = round(length_units / 316.3);
        # a 316.3-unit link must give exactly 1
        d = self.Datum_like()

    def Datum_like(self):
        d = self.d
        pts = [(10.0, 50.0), (10.0, 50.0 + 316.3 / d.Ky)]
        self.assertEqual(d.link_weight_field04(pts), 1)
        return d


if __name__ == "__main__":
    unittest.main()
