import unittest

from topology.core import (
    CANDIDATE_PATHS,
    configured_link_params,
    configured_path_params,
    deterministic_candidate_paths,
    select_candidate_path,
    topology_neighbors,
    validate_path,
    PathValidationError,
)


class TopologyTests(unittest.TestCase):
    def test_candidates_are_deterministic_and_connected(self):
        self.assertEqual(
            [name for name, _ in deterministic_candidate_paths()],
            ["P1_1-2-4-6", "P2_1-2-5-6", "P3_1-3-4-6"],
        )
        neighbors = topology_neighbors()
        for path in CANDIDATE_PATHS.values():
            self.assertEqual(validate_path(path), tuple(path))
            for left, right in zip(path, path[1:]):
                self.assertIn(right, neighbors[left])
                self.assertIn(left, neighbors[right])

    def test_selection_and_invalid_paths(self):
        self.assertEqual(select_candidate_path("P2_1-2-5-6"), (1, 2, 5, 6))
        for invalid in ((2, 1, 6), (1, 2, 6), (1, 2, 1, 6), (1, "2", 4, 6)):
            with self.assertRaises(PathValidationError):
                validate_path(invalid)
        with self.assertRaises(PathValidationError):
            select_candidate_path("unknown")

    def test_configured_parameters_are_not_measurements(self):
        self.assertEqual(configured_link_params(2, 5), {"bw_mbit": 10, "delay_ms": 10, "loss_pct": 2})
        self.assertEqual(
            configured_path_params((1, 2, 4, 6)),
            {
                "cfg_bottleneck_bw_mbit": 5,
                "cfg_oneway_delay_ms": 15,
                "cfg_loss_pct_per_direction": 0.0,
            },
        )
        self.assertEqual(configured_path_params((1, 2, 5, 6))["cfg_loss_pct_per_direction"], 2.0)


if __name__ == "__main__":
    unittest.main()
