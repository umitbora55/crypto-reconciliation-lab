"""Literal CLI/demo acceptance, separate from transaction and process tests."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.cli import main
from crypto_reconciliation_lab.execution.demo import build_fixture, run_demo
from crypto_reconciliation_lab.source_auth.crypto import AuthError


LEGACY = ["legacy_unrecorded", "legacy_recorded", "legacy_retry", "legacy_conflict",
          "legacy_new_request", "legacy_multiple", "legacy_show", "legacy_export", "legacy_export_existing"]
PROTECTED = ["protected_recorded", "protected_retry_after_change", "protected_new_request",
             "protected_original_readback", "protected_multiple", "protected_export",
             "signed_mismatch", "signed_mismatch_show"]


class RecordedExecutionDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.report = run_demo(cls.root / "protected", profile="protected")
        cls.legacy_report = run_demo(cls.root / "legacy", profile="legacy")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def result(self, name):
        return json.loads((self.root / "protected" / "commands" / name / "result.json").read_text())

    def cli(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(arguments)
        return code, json.loads(output.getvalue())

    def test_fixture_constructor_only_admits_thirty_rows_without_evaluation(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("crypto_reconciliation_lab.source_auth.crypto.require_auth", side_effect=AssertionError("legacy fixture must not require crypto")):
                fixture = build_fixture(Path(folder) / "input")
            with contextlib.closing(sqlite3.connect(fixture["database"])) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 30)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM recorded_executions").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_configuration").fetchone()[0], 0)

    def test_exact_demo_inventories_and_real_exit_reason_controls(self):
        self.assertEqual(self.legacy_report["case_inventory"], LEGACY)
        self.assertEqual(self.report["case_inventory"], LEGACY + PROTECTED)
        self.assertEqual([row["id"] for row in self.report["cases"]], LEGACY + PROTECTED)
        self.assertEqual(self.report["status"], "PASS")
        self.assertEqual(self.legacy_report["status"], "PASS")
        cases = {row["id"]: row for row in self.report["cases"]}
        for name, expected in {
            "legacy_unrecorded": (0, "NOT_RECORDED", None),
            "legacy_conflict": (2, "ERROR", "EXECUTION_REQUEST_CONFLICT"),
            "legacy_export_existing": (2, "ERROR", "EXECUTION_OUTPUT"),
            "signed_mismatch": (1, "RECORDED", None),
            "signed_mismatch_show": (0, "RECORDED", None),
        }.items():
            with self.subTest(name=name):
                row = cases[name]
                self.assertEqual(tuple(row["actual"][key] for key in ("exit_code", "status", "reason_code")), expected)
                command = json.loads((self.root / "protected" / row["command"]).read_text())
                self.assertEqual(command["exit_code"], expected[0])
                self.assertIn("crypto_reconciliation_lab", command["argv"])
                self.assertTrue(row["passed"])

    def test_clean_and_signed_mismatch_have_independent_literal_financial_values(self):
        clean = self.result("protected_recorded")["financial_result"]
        wrong = self.result("signed_mismatch")["financial_result"]
        for financial in (clean, wrong):
            self.assertEqual(financial["ledgers"]["ASSET_A"]["investor_balances"], {"I1": "7", "I2": "4"})
            self.assertEqual(financial["ledgers"]["ASSET_A"]["liability"], "11")
            self.assertEqual(financial["ledgers"]["ASSET_A"]["custody_rollforward"], {"platform": "2", "external": "9"})
            self.assertEqual(financial["ledgers"]["ASSET_B"]["investor_balances"], {"I1": "0.3", "I2": "0.2"})
            self.assertEqual(financial["ledgers"]["ASSET_B"]["liability"], "0.5")
        self.assertTrue(all(row["reconciliation_state"] == "MATCHED" for row in clean["findings"]))
        difference = [row for row in wrong["findings"] if row["asset"] == "ASSET_A" and row["comparison"] == "B"]
        self.assertEqual(len(difference), 1)
        self.assertEqual({key: difference[0][key] for key in ("expected", "reported", "difference", "data_state", "reconciliation_state")},
                         {"expected": "11", "reported": "10", "difference": "1", "data_state": "COMPLETE", "reconciliation_state": "MISMATCH"})
        self.assertTrue(all(row["reconciliation_state"] == "MATCHED" for row in wrong["findings"] if row["comparison"] == "A"))

    def test_retry_preserves_original_inventory_policy_and_new_request_records_both_candidates(self):
        first = self.result("protected_recorded")
        retry = self.result("protected_retry_after_change")
        second = self.result("protected_new_request")
        saved = self.result("protected_original_readback")
        self.assertTrue(retry["replayed"])
        self.assertEqual(first["execution_id"], retry["execution_id"])
        self.assertEqual(first["context"], retry["context"])
        self.assertEqual(first["context"], saved["context"])
        self.assertNotEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual((len(first["context"]["tables"]["receipts"]), len(second["context"]["tables"]["receipts"])), (30, 31))
        self.assertEqual(first["context"]["observed_policy_head"]["epoch"], 1)
        self.assertEqual(second["context"]["observed_policy_head"]["epoch"], 2)
        self.assertEqual(second["context"]["acceptance_epochs"], [1])
        grouped = {}
        for row in second["context"]["tables"]["receipts"]:
            grouped.setdefault(row["receipt_hash"], []).append(row["id"])
        duplicates = [ids for ids in grouped.values() if len(ids) == 2]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(set(duplicates[0])), 2)
        self.assertIn(31, duplicates[0])

    def test_legacy_read_and_run_lookup_do_not_invent_an_original_execution(self):
        old = self.result("legacy_unrecorded")
        new = self.result("legacy_recorded")
        multiple = self.result("legacy_multiple")
        self.assertEqual(old["status"], "NOT_RECORDED")
        self.assertEqual(old["execution_ids"], [])
        self.assertEqual(old["run_id"], new["run_id"])
        self.assertEqual(new["context"]["claims"]["legacy_signature_status"], "UNSIGNED")
        self.assertEqual(new["context"]["claims"]["run_actor_authorization"], "NOT_DEFINED")
        self.assertEqual(new["context"]["claims"]["source_signature_verification"], "NOT_PERFORMED")
        self.assertEqual(multiple["status"], "MULTIPLE_EXECUTIONS")
        self.assertEqual(len(set(multiple["execution_ids"])), 2)
        self.assertNotIn("execution_id", multiple)

    def test_show_and_export_cli_dispatch_never_constructs_store(self):
        first = self.result("legacy_recorded")
        database = self.root / "protected/legacy-inputs/source.sqlite3"
        before = database.read_bytes()
        with tempfile.TemporaryDirectory() as folder, patch("crypto_reconciliation_lab.cli.Store", side_effect=AssertionError("reader must not construct Store")):
            code, shown = self.cli(["show-execution", "--db", str(database), "--execution-id", first["execution_id"]])
            self.assertEqual(code, 0)
            self.assertEqual(shown["context"], first["context"])
            target = Path(folder) / "export"
            code, exported = self.cli(["export-execution", "--db", str(database), "--execution-id", first["execution_id"], "--output", str(target)])
            self.assertEqual((code, exported["status"]), (0, "EXPORTED"))
            self.assertEqual(json.loads((target / "context.json").read_bytes()), first["context"])
            self.assertEqual(json.loads((target / "run.json").read_bytes())["rule_version"], "stage2-v2")
        self.assertEqual(database.read_bytes(), before)

    def test_export_cli_rejects_database_and_sidecar_namespace_without_writes(self):
        first = self.result("legacy_recorded")
        database = self.root / "protected/legacy-inputs/source.sqlite3"
        before = database.read_bytes()
        for suffix in ("", "-journal", "-wal", "-shm"):
            with self.subTest(suffix=suffix):
                target = Path(str(database) + suffix)
                code, result = self.cli(["export-execution", "--db", str(database), "--execution-id", first["execution_id"], "--output", str(target)])
                self.assertEqual(code, 2)
                self.assertEqual(result["reason_code"], "EXECUTION_OUTPUT")
                if suffix:
                    self.assertFalse(target.exists())
        self.assertEqual(database.read_bytes(), before)

    def test_protected_demo_missing_auth_is_explicit_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "must-not-exist"
            with patch("crypto_reconciliation_lab.source_auth.crypto.require_auth", side_effect=AuthError("AUTH_DEPENDENCY", "fixture absence")):
                code, result = self.cli(["demo-execution-context", "--output", str(target), "--profile", "protected"])
            self.assertEqual(code, 2)
            self.assertEqual(result["reason_code"], "AUTH_DEPENDENCY")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
