import csv
import tempfile
import unittest
from pathlib import Path

from analyze_results import main
from experiments.schema import CSV_COLUMNS
from topology.core import CANDIDATE_PATHS, configured_path_params


def row(route, path, run_id):
    params = configured_path_params(path)
    return {
        "run_id": str(run_id), "status": "ok", "route": route,
        "path": "-".join(map(str, path)), "seed": "0",
        "shaping_mode": "bw+delay+loss", **{k: str(v) for k, v in params.items()},
        "ping_rtt_avg_ms": "20", "ping_loss_pct": "0",
        "udp_offered_mbit": "8", "udp_throughput_mbit": "7",
        "udp_loss_pct": "0", "udp_jitter_ms": "0.5",
        "tcp_throughput_mbit": "6", "wall_s": "1",
    }


class AnalysisTests(unittest.TestCase):
    def _write(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_real_analyzer_writes_descriptive_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "measurements.csv"
            output_dir = root / "analysis"
            rows = [row(name, path, index) for index, (name, path) in enumerate(CANDIDATE_PATHS.items(), 1)]
            self._write(input_path, rows)
            self.assertEqual(main(["--input", str(input_path), "--out-dir", str(output_dir)]), 0)
            for name in ("summary_by_route.csv", "summary_overall.csv", "analysis_report.md", "throughput_by_route.svg", "latency_by_route.svg"):
                self.assertTrue((output_dir / name).is_file())

    def test_real_analyzer_rejects_missing_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "measurements.csv"
            self._write(input_path, [row("P1_1-2-4-6", (1, 2, 4, 6), 1)])
            self.assertEqual(main(["--input", str(input_path), "--out-dir", str(root / "analysis")]), 2)


if __name__ == "__main__":
    unittest.main()
