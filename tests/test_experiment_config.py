import unittest

from experiments.phase1_validate import _arguments, build_experiment_config


class ExperimentConfigTests(unittest.TestCase):
    def test_config_records_controls_and_provenance(self):
        args = _arguments(["--reps", "2", "--seed", "7", "--udp_mbit", "6", "--dur", "3"])
        config = build_experiment_config(args, "/usr/bin/controller", "bw+delay+loss")
        self.assertEqual(config["sampling"]["repetitions_per_route"], 2)
        self.assertEqual(config["sampling"]["route_order_seed"], 7)
        self.assertTrue(config["measurement_policy"]["configured_parameters_are_not_measurements"])
        self.assertFalse(config["measurement_policy"]["synthetic_data_used"])
        self.assertEqual(len(config["topology"]["candidate_paths"]), 3)

    def test_config_rejects_invalid_controls(self):
        args = _arguments(["--reps", "0"])
        with self.assertRaises(ValueError):
            build_experiment_config(args, "controller", "bw+delay+loss")


if __name__ == "__main__":
    unittest.main()
