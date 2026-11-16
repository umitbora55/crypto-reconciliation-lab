"""Independent literals, disagreement sensitivity and scope boundaries."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from validation_lab.benchmark import (
    analytic_oracle, cents, reference_database, reference_ingest, python_calculate,
    sql_calculate, validate_narrow, with_findings, workload, run_one, project_production, benchmark,
)


class BenchmarkContractTests(unittest.TestCase):
    def test_literal_cycle_and_suffix_balances(self):
        self.assertEqual(analytic_oracle(3, 11)["balances"], {"I0": 10000, "I1": 10000, "I2": 10000, "I3": 10000})
        self.assertEqual(analytic_oracle(1, 11)["balances"], {"I0": 10012, "I1": 10000, "I2": 10000, "I3": 10000})
        self.assertEqual(analytic_oracle(2, 11)["balances"], {"I0": 10000, "I1": 10012, "I2": 10000, "I3": 10000})
        self.assertEqual(analytic_oracle(4, 11)["liability"], 40029)

    def test_integer_boundary_and_invalid_decimal(self):
        self.assertEqual(cents("0.01"), 1)
        self.assertEqual(cents("10.2"), 1020)
        for value in ("0.001", "NaN", "1e3", "-0.01", "1.", "١", 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cents(value)

    def test_missing_manifest_and_same_count_duplicate_rejected(self):
        data = workload(4, 11)
        missing = copy.deepcopy(data)
        missing["rows"].pop()
        with self.assertRaisesRegex(ValueError, "manifest"):
            validate_narrow(missing)
        duplicate = copy.deepcopy(data)
        duplicate["rows"][7] = copy.deepcopy(duplicate["rows"][6])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_narrow(duplicate)

    def test_unsupported_revision_and_time_cut_rejected(self):
        data = workload(4, 11)
        data["balance_at"] = "2026-01-01T23:00:00Z"
        with self.assertRaisesRegex(ValueError, "time cut"):
            validate_narrow(data)
        data = workload(4, 11)
        next(e["record"] for e in data["rows"] if e["record"]["kind"] == "report")["version"] = 2
        with self.assertRaisesRegex(ValueError, "revision"):
            validate_narrow(data)

    def test_two_algorithms_match_literal_and_negative_report(self):
        data = workload(2, 11)
        validate_narrow(data)
        with tempfile.TemporaryDirectory() as tmp:
            db = reference_database(Path(tmp) / "test.sqlite3")
            self.addCleanup(db.close)
            reference_ingest(db, data)
            sql = sql_calculate(db)
            py = python_calculate(e["record"] for e in data["rows"])
            expected = {"balances": {"I0": 10000, "I1": 10012, "I2": 10000, "I3": 10000},
                        "liability": 40012, "custody": {"platform": 0, "external": 40012}}
            self.assertEqual(sql, expected)
            self.assertEqual(py, expected)
            report = next(e["record"] for e in data["rows"] if e["record"].get("stream") == "external_custody" and e["record"]["kind"] == "report")
            report["amount"] = "400.11"
            result = with_findings(sql, data)
            self.assertEqual(result["differences"]["customer_liability"], 1)
            self.assertEqual(result["outcomes"]["customer_liability"], "MISMATCH")

    def test_production_and_references_execute_same_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "input.json"
            path.write_text(json.dumps(workload(4, 11)))
            expected = {"I0": 10000, "I1": 10029, "I2": 10000, "I3": 10000}
            answers = []
            for method in ("stdlib_integer", "sqlite_integer", "production"):
                metrics = run_one(method, path, root / method)
                self.assertEqual(metrics["common_output"]["balances"], expected)
                self.assertEqual(metrics["status"], "PASS")
                answers.append(metrics["common_output"])
            self.assertEqual(answers[0], answers[1])
            self.assertEqual(answers[1], answers[2])

    def test_oracle_detects_consistently_changed_report(self):
        data = workload(4, 11)
        next(e["record"] for e in data["rows"] if e["record"].get("scope") == "I1" and e["record"]["kind"] == "report")["amount"] = "100.30"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(AssertionError):
                run_one("production", path, Path(tmp) / "production")

    def test_empty_and_duplicate_profiles_cannot_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, profiles in enumerate(([], [100, 100])):
                with self.assertRaises(ValueError):
                    benchmark(Path(tmp) / str(index), profiles)

    def test_declared_event_count_cannot_inflate_throughput(self):
        data = workload(3, 11)
        data["events"] = 300
        with self.assertRaisesRegex(ValueError, "event-count"):
            validate_narrow(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(data))
            for method in ("production", "stdlib_integer", "sqlite_integer"):
                with self.assertRaisesRegex(ValueError, "event-count"):
                    run_one(method, path, Path(tmp) / method)

    def test_partial_program_cannot_signal_success_to_parent(self):
        from validation_lab.benchmark import main
        with patch("sys.argv", ["benchmark", "--output", "/unused-not-created"]), \
             patch("validation_lab.benchmark.benchmark", return_value={"status": "PARTIAL"}):
            self.assertEqual(main(), 3)


if __name__ == "__main__":
    unittest.main()
