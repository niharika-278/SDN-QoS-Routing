import csv
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from statistics import mean, median, stdev

from synthetic_demo.analyze_synthetic_data import (
    DISCLOSURE,
    EXPECTED_ROW_COUNT,
    analysis_artifact_names,
)
from synthetic_demo.generate_synthetic_data import (
    DEFAULT_SEED,
    DEFAULT_TRIALS,
    generate,
    write_csv,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "synthetic_demo" / "synthetic_phase1_metrics.csv"
ANALYZER = ROOT / "synthetic_demo" / "analyze_synthetic_data.py"


class SyntheticAnalysisTests(unittest.TestCase):
    def _run_analyzer(self, input_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ANALYZER), "--input", str(input_path), "--out-dir", str(output_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_deterministic_regeneration_matches_existing_36_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.csv"
            second = root / "second.csv"
            write_csv(generate(DEFAULT_SEED, DEFAULT_TRIALS), first)
            write_csv(generate(DEFAULT_SEED, DEFAULT_TRIALS), second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), RAW_CSV.read_bytes())
            with RAW_CSV.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(sum(1 for _ in csv.DictReader(handle)), EXPECTED_ROW_COUNT)

    def test_descriptive_statistics_are_recalculated_from_raw_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.csv"
            shutil.copyfile(RAW_CSV, input_path)
            output_dir = root / "analysis"
            result = self._run_analyzer(input_path, output_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            with input_path.open(newline="", encoding="utf-8") as handle:
                raw_rows = list(csv.DictReader(handle))
            values = [
                float(row["ping_rtt_avg_ms"])
                for row in raw_rows
                if row["route"] == "P1_1-2-4-6"
            ]
            with (output_dir / "synthetic_descriptive_summary.csv").open(newline="", encoding="utf-8") as handle:
                summaries = list(csv.DictReader(handle))
            summary = next(
                row
                for row in summaries
                if row["route"] == "P1_1-2-4-6" and row["metric_field"] == "ping_rtt_avg_ms"
            )
            self.assertEqual(int(summary["n"]), len(values))
            self.assertAlmostEqual(float(summary["mean"]), mean(values), places=6)
            self.assertAlmostEqual(float(summary["sample_sd"]), stdev(values), places=6)
            self.assertAlmostEqual(float(summary["min"]), min(values), places=6)
            self.assertAlmostEqual(float(summary["median"]), median(values), places=6)
            self.assertAlmostEqual(float(summary["max"]), max(values), places=6)

            # A changed raw trial must change the recalculated output; existing
            # generated summaries are never treated as the source of truth.
            changed_path = root / "changed.csv"
            with input_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                changed_rows = list(reader)
                fieldnames = reader.fieldnames
            changed = next(row for row in changed_rows if row["route"] == "P1_1-2-4-6")
            changed["ping_rtt_avg_ms"] = f"{float(changed['ping_rtt_avg_ms']) + 10.0:.6f}"
            with changed_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(changed_rows)
            changed_output = root / "changed-analysis"
            result = self._run_analyzer(changed_path, changed_output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with (changed_output / "synthetic_descriptive_summary.csv").open(newline="", encoding="utf-8") as handle:
                changed_summary = next(
                    row
                    for row in csv.DictReader(handle)
                    if row["route"] == "P1_1-2-4-6" and row["metric_field"] == "ping_rtt_avg_ms"
                )
            self.assertNotEqual(changed_summary["mean"], summary["mean"])

    def test_malformed_and_incomplete_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with RAW_CSV.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fieldnames = reader.fieldnames
                rows = list(reader)

            incomplete = root / "incomplete.csv"
            with incomplete.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows[:-1])
            result = self._run_analyzer(incomplete, root / "incomplete-output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("exactly 36 rows", result.stdout)

            malformed = root / "malformed.csv"
            rows[0]["measurement_status"] = "MEASURED"
            with malformed.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            result = self._run_analyzer(malformed, root / "malformed-output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not-measured label", result.stdout)

    def test_output_package_is_consistent_and_does_not_modify_raw_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "analysis"
            before = hashlib.sha256(RAW_CSV.read_bytes()).hexdigest()
            result = self._run_analyzer(RAW_CSV, output_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            first = {name: (output_dir / name).read_bytes() for name in analysis_artifact_names()}
            result = self._run_analyzer(RAW_CSV, output_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            second = {name: (output_dir / name).read_bytes() for name in analysis_artifact_names()}
            self.assertEqual(first, second)
            self.assertEqual(before, hashlib.sha256(RAW_CSV.read_bytes()).hexdigest())

    def test_every_generated_artifact_has_the_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "analysis"
            result = self._run_analyzer(RAW_CSV, output_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in analysis_artifact_names():
                content = (output_dir / name).read_text(encoding="utf-8")
                self.assertIn(DISCLOSURE, content, name)


if __name__ == "__main__":
    unittest.main()
