import csv
import tempfile
import unittest
from pathlib import Path

from experiments.schema import (
    CSV_COLUMNS,
    MeasurementValidationError,
    partition_results,
    read_valid_csv,
    validate_csv_schema,
    validate_result_row,
    validate_results,
    write_valid_csv,
)


def valid_row():
    return {
        "run_id": "1",
        "status": "ok",
        "route": "P1_1-2-4-6",
        "path": "1-2-4-6",
        "seed": "0",
        "shaping_mode": "bw+delay+loss",
        "cfg_bottleneck_bw_mbit": "5",
        "cfg_oneway_delay_ms": "15",
        "cfg_loss_pct_per_direction": "0",
        "ping_rtt_avg_ms": "31.2",
        "ping_loss_pct": "0",
        "udp_offered_mbit": "8",
        "udp_throughput_mbit": "7.8",
        "udp_loss_pct": "0",
        "udp_jitter_ms": "0.4",
        "tcp_throughput_mbit": "4.9",
        "wall_s": "2.1",
    }


class SchemaTests(unittest.TestCase):
    def test_schema_and_valid_row(self):
        self.assertEqual(validate_csv_schema(CSV_COLUMNS), CSV_COLUMNS)
        normalized = validate_result_row(valid_row())
        self.assertEqual(normalized["run_id"], 1)
        self.assertEqual(normalized["udp_throughput_mbit"], 7.8)
        self.assertEqual(validate_results([valid_row()])[0]["path"], "1-2-4-6")

    def test_bad_schema_failed_and_missing_rows_are_rejected(self):
        with self.assertRaises(MeasurementValidationError):
            validate_csv_schema(("run_id", "status"))
        failed = valid_row()
        failed["status"] = "FAILED"
        with self.assertRaises(MeasurementValidationError):
            validate_result_row(failed)
        incomplete = valid_row()
        incomplete["udp_jitter_ms"] = ""
        with self.assertRaises(MeasurementValidationError):
            validate_result_row(incomplete)
        no_mode = valid_row()
        no_mode["shaping_mode"] = ""
        with self.assertRaises(MeasurementValidationError):
            validate_result_row(no_mode)
        accepted, rejected = partition_results([failed, incomplete])
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 2)
        with self.assertRaises(MeasurementValidationError):
            validate_results([])

    def test_validated_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            write_valid_csv(path, [valid_row()])
            with path.open(newline="") as handle:
                self.assertEqual(tuple(csv.DictReader(handle).fieldnames), CSV_COLUMNS)
            self.assertEqual(read_valid_csv(path)[0]["route"], "P1_1-2-4-6")


if __name__ == "__main__":
    unittest.main()
