"""Regression tests for the TPNAV2 node/link cluster parser."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from tpnav2_container import NavContainer  # noqa: E402
from tpnav2_graph import coordinate, parse_graph  # noqa: E402


def read_entry(path: str, entry_index: int) -> bytes:
    container = NavContainer(ROOT / path)
    entry = container.entries[entry_index]
    decoded, _, _ = container.read_block(entry.logical_offset, entry.logical_size)
    return decoded


class Tpnav2GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (
            "extracted/czech_poland_2010_2011/NAV20001.DAT",
            "extracted/germany/NAV20051.DAT",
            "extracted/germany/NAV20050.DAT",
        )
        if any(not (ROOT / name).is_file() for name in required):
            raise unittest.SkipTest(
                "Private TPNAV2 integration data are absent; run the self-contained tests in tests/."
            )
        cls.small = parse_graph(
            read_entry("extracted/czech_poland_2010_2011/NAV20001.DAT", 241),
            "czech-poland-2010-2011/NAV20001.DAT entry 241",
        )
        cls.germany = parse_graph(
            read_entry("extracted/germany/NAV20051.DAT", 158),
            "germany/NAV20051.DAT entry 158",
        )
        cls.local_residual = parse_graph(
            read_entry("extracted/germany/NAV20050.DAT", 95),
            "germany/NAV20050.DAT entry 95",
        )

    def test_small_cluster_header_and_bounds(self):
        header = self.small["header"]
        self.assertEqual(header["declared_size"], 768)
        self.assertEqual(header["base_x"], 174510580)
        self.assertEqual(header["base_y"], 595157514)
        self.assertEqual(header["coordinate_shift"], 1)
        self.assertFalse(header["wide_coordinates"])
        xs = [item["x"] for item in self.small["bounds_coordinates"]]
        ys = [item["y"] for item in self.small["bounds_coordinates"]]
        self.assertEqual((min(xs), max(xs)), (174456634, 174564526))
        self.assertEqual((min(ys), max(ys)), (595135212, 595179816))

    def test_small_cluster_topology(self):
        validation = self.small["validation"]
        self.assertEqual(validation["node_count"], 11)
        self.assertEqual(validation["link_count"], 11)
        self.assertEqual(validation["node_link_reference_count"], 21)
        self.assertEqual(validation["endpoint_conflicts"], [])
        self.assertEqual(validation["errors"], [])
        self.assertTrue(validation["topologically_consistent"])
        edges = sorted((link["resolved_first"], link["resolved_second"])
                       for link in self.small["links"])
        self.assertEqual(edges[0], (1, 1))
        self.assertIn((1, 2), edges)
        self.assertIn((10, 11), edges)
        self.assertEqual(self.small["links"][4]["resolved_first"], 5)
        self.assertEqual(self.small["links"][4]["resolved_second"], 7)
        self.assertEqual(len(self.small["links"][4]["path_coordinates"]), 9)

    def test_coordinate_sources_and_paths(self):
        self.assertEqual(self.small["nodes"][0]["coordinate"]["x"], 174456634)
        self.assertEqual(self.small["nodes"][0]["coordinate"]["y"], 595135212)
        link = self.small["links"][1]
        self.assertEqual(link["first_source"], "node_link_list")
        self.assertEqual(link["second_source"], "node_link_list")
        self.assertEqual(len(link["path_coordinates"]), 3)
        self.assertEqual(link["path_coordinates"][0]["kind"], "first_node")
        self.assertEqual(link["path_coordinates"][-1]["kind"], "second_node")
        loop = self.small["links"][10]
        self.assertEqual((loop["resolved_first"], loop["resolved_second"]), (1, 1))
        self.assertEqual(loop["second_source"], "raw_record")

    def test_germany_cluster_is_consistent(self):
        validation = self.germany["validation"]
        self.assertEqual(validation["node_count"], 346)
        self.assertEqual(validation["link_count"], 356)
        self.assertEqual(validation["node_link_reference_count"], 709)
        self.assertEqual(validation["errors"], [])
        self.assertTrue(validation["topologically_consistent"])
        for node in self.germany["nodes"]:
            self.assertGreaterEqual(len(node["link_references"]), 0)
        for link in self.germany["links"]:
            self.assertTrue(1 <= link["resolved_first"] <= 346)
            self.assertTrue(1 <= link["resolved_second"] <= 346)

    def test_residual_nonlocal_endpoints_are_reported(self):
        validation = self.local_residual["validation"]
        self.assertFalse(validation["topologically_consistent"])
        self.assertEqual(
            validation["errors"],
            [
                "link 4 second node 449 outside 1..4",
                "link 5 second node 449 outside 1..4",
            ],
        )

    def test_wide_coordinate_word_layout(self):
        header = {"coordinate_shift": 2, "base_x": 100, "base_y": 200,
                  "wide_coordinates": True}
        result = coordinate(bytes((0x56, 0x34, 0x12, 0xCD, 0xAB, 0x90)), 0, header)
        self.assertEqual(result["delta_x"], 0x123456)
        self.assertEqual(result["delta_y"], 0x90ABCD)
        self.assertEqual(result["x"], 100 + (0x123456 << 2))
        self.assertEqual(result["y"], 200 + (0x90ABCD << 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
