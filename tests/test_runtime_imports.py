import importlib
import unittest


class RuntimeImportTests(unittest.TestCase):
    def test_runtime_modules_import_without_optional_packages(self):
        topology = importlib.import_module("topology.topo")
        controller = importlib.import_module("controller.route_controller")
        experiment = importlib.import_module("experiments.phase1_validate")
        self.assertTrue(callable(topology.build))
        self.assertTrue(hasattr(controller, "RouteController"))
        self.assertTrue(callable(experiment.main))


if __name__ == "__main__":
    unittest.main()
