import copy
import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.demo import BALANCE_AT, KNOWLEDGE_AT, LATER_KNOWLEDGE_AT, fixtures, run_demos
from crypto_reconciliation_lab.model import CONTEXT, amount, timestamp


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config, self.rows, _ = fixtures()
        self.stores = []
        self.addCleanup(self.close_stores)

    def close_stores(self):
        for store in self.stores:
            store.close()

    def store(self, rows=None, name=None):
        store = Store(Path(self.temp.name) / (name or f"db{len(self.stores)}.sqlite3"), self.config)
        self.stores.append(store)
        for row in self.rows if rows is None else rows:
            store.ingest(row["record"], row["received_at"])
        return store

    def evaluate(self, store, knowledge=KNOWLEDGE_AT):
        return reconcile(store, BALANCE_AT, knowledge)

    def find(self, result, asset="ASSET_A", comparison="B", scope=None):
        return next(r for r in result["findings"] if r["asset"] == asset and r["comparison"] == comparison and (scope is None or r["scope"] == scope))

    def event(self, ref="A1"):
        return next(r for r in self.rows if r["record"].get("ref") == ref)

    def report(self, stream="external_custody", asset="ASSET_A", scope=None):
        return next(r for r in self.rows if r["record"]["kind"] == "report" and r["record"]["stream"] == stream and r["record"]["asset"] == asset and (scope is None or r["record"]["scope"] == scope))

    def test_clean_independent_literals(self):
        result = self.evaluate(self.store())
        self.assertEqual(result["ledgers"]["ASSET_A"]["investor_balances"], {"I1": "7", "I2": "4"})
        self.assertEqual(result["ledgers"]["ASSET_A"]["liability"], "11")
        self.assertEqual(result["ledgers"]["ASSET_A"]["custody_rollforward"], {"platform": "2", "external": "9"})
        self.assertEqual(result["ledgers"]["ASSET_B"]["investor_balances"], {"I1": "0.3", "I2": "0.2"})
        self.assertEqual(result["ledgers"]["ASSET_B"]["liability"], "0.5")
        self.assertEqual(result["ledgers"]["ASSET_B"]["custody_rollforward"], {"platform": "0.05", "external": "0.45"})
        self.assertTrue(all(r["data_state"] == "COMPLETE" and r["reconciliation_state"] == "MATCHED" for r in result["findings"]))

    def test_internal_transfer_preserves_totals_and_custody(self):
        result = self.evaluate(self.store())
        first = result["ledgers"]["ASSET_A"]["trace"][0]
        self.assertEqual(first["balances_after"], {"I1": "5", "I2": "5"})
        self.assertEqual(first["custody_delta"], "0")
        self.assertIsNone(first["custody_location"])

    def test_duplicate_same_receipt_and_rerun_are_idempotent(self):
        store = self.store()
        before = self.evaluate(store)
        receipt_count = store.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        for row in self.rows:
            self.assertEqual(store.ingest(row["record"], row["received_at"])["status"], "DUPLICATE")
        self.assertEqual(self.evaluate(store), before)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], receipt_count * 2)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_received_time_and_decimal_spelling_do_not_change_event_identity(self):
        store = self.store()
        raw = copy.deepcopy(self.event()["record"])
        raw["amount"] = "1.00000000"
        raw["occurred_at"] = "2026-11-10T04:00:00+03:00"
        self.assertEqual(store.ingest(raw, KNOWLEDGE_AT)["status"], "DUPLICATE")
        result = self.evaluate(store)
        self.assertEqual(result["ledgers"]["ASSET_A"]["liability"], "11")
        self.assertEqual(len(result["ledgers"]["ASSET_A"]["event_ids"]), 3)
        self.assertEqual(self.find(result)["reconciliation_state"], "MATCHED")

    def test_event_conflict_is_visible_and_temporal(self):
        store = self.store()
        before = self.evaluate(store)
        raw = copy.deepcopy(self.event()["record"])
        raw["amount"] = "2"
        self.assertEqual(store.ingest(raw, LATER_KNOWLEDGE_AT)["status"], "CONFLICT")
        self.assertEqual(self.evaluate(store), before)
        after = self.evaluate(store, LATER_KNOWLEDGE_AT)
        self.assertEqual(self.find(after)["data_state"], "CONFLICT")
        self.assertEqual(self.find(after)["reconciliation_state"], "NOT_EVALUATED")
        self.assertEqual(len(after["ledgers"]["ASSET_A"]["event_ids"]), 2)
        self.assertTrue(any(x["code"] == "EVENT_ID_CONFLICT" for x in self.find(after)["issues"]))

    def test_order_independence_same_knowledge_cut(self):
        shuffled = copy.deepcopy(self.rows)
        random.Random(17).shuffle(shuffled)
        self.assertEqual(self.evaluate(self.store()), self.evaluate(self.store(shuffled)))

    def test_late_event_manifest_and_immutable_history(self):
        config, initial, later = fixtures("late_event")
        store = self.store(initial)
        before = self.evaluate(store)
        finding = self.find(before)
        self.assertEqual((finding["data_state"], finding["reconciliation_state"], finding["difference"]), ("INCOMPLETE", "NOT_EVALUATED", "1"))
        count = next(i for i in finding["issues"] if i["code"] == "MANIFEST_COUNT")
        self.assertEqual((count["expected_count"], count["observed_unique_valid_count"]), (3, 2))
        store.ingest(later[0]["record"], later[0]["received_at"])
        self.assertEqual(self.find(self.evaluate(store, LATER_KNOWLEDGE_AT))["reconciliation_state"], "MATCHED")
        self.assertEqual(store.read_run(before["run_id"]), before)
        self.assertEqual(self.evaluate(store), before)

    def test_duplicates_do_not_fill_missing_delivery(self):
        _, initial, _ = fixtures("late_event")
        store = self.store(initial)
        for _ in range(5):
            store.ingest(self.event()["record"], KNOWLEDGE_AT)
        finding = self.find(self.evaluate(store))
        self.assertEqual(finding["data_state"], "INCOMPLETE")
        self.assertEqual(next(i for i in finding["issues"] if i["code"] == "MANIFEST_COUNT")["observed_unique_valid_count"], 2)

    def test_custody_difference_does_not_change_investor_check(self):
        _, rows, _ = fixtures("custody_difference")
        result = self.evaluate(self.store(rows))
        finding = self.find(result)
        self.assertEqual((finding["data_state"], finding["reconciliation_state"], finding["expected"], finding["reported"], finding["difference"]), ("COMPLETE", "MISMATCH", "11", "10", "1"))
        self.assertEqual(self.find(result, comparison="A")["reconciliation_state"], "MATCHED")

    def test_report_revision_preserves_old_version_and_knowledge(self):
        _, rows, later = fixtures("corrected_report")
        store = self.store(rows)
        before = self.evaluate(store)
        store.ingest(later[0]["record"], later[0]["received_at"])
        after = self.evaluate(store, LATER_KNOWLEDGE_AT)
        self.assertEqual(self.find(after)["reconciliation_state"], "MATCHED")
        self.assertEqual(self.find(before)["difference"], "1")
        self.assertEqual(self.evaluate(store), before)
        self.assertEqual(store.read_run(before["run_id"]), before)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM records WHERE kind='report'").fetchone()[0], 9)

    def test_same_report_version_conflict_does_not_overwrite(self):
        store = self.store()
        raw = copy.deepcopy(self.report()["record"])
        raw["amount"] = "8"
        self.assertEqual(store.ingest(raw, KNOWLEDGE_AT)["status"], "CONFLICT")
        result = self.evaluate(store)
        self.assertEqual(self.find(result)["data_state"], "CONFLICT")
        self.assertEqual(self.find(result, comparison="A")["reconciliation_state"], "MATCHED")

    def test_newer_version_supersedes_conflicted_old_version(self):
        store = self.store()
        raw = copy.deepcopy(self.report()["record"])
        store.ingest({**raw, "amount": "8"}, KNOWLEDGE_AT)
        store.ingest({**raw, "version": 2}, LATER_KNOWLEDGE_AT)
        self.assertEqual(self.find(self.evaluate(store, LATER_KNOWLEDGE_AT))["reconciliation_state"], "MATCHED")

    def test_version_order_not_retransmission_order(self):
        store = self.store()
        raw = copy.deepcopy(self.report()["record"])
        store.ingest({**raw, "version": 2, "amount": "8"}, KNOWLEDGE_AT)
        store.ingest(raw, LATER_KNOWLEDGE_AT)
        self.assertEqual(self.find(self.evaluate(store, LATER_KNOWLEDGE_AT))["difference"], "1")

    def test_missing_custody_is_not_deficit(self):
        missing = self.report()
        result = self.evaluate(self.store([r for r in self.rows if r != missing]))
        finding = self.find(result)
        self.assertEqual((finding["data_state"], finding["reconciliation_state"]), ("INCOMPLETE", "NOT_EVALUATED"))
        self.assertIsNone(finding["difference"])
        self.assertIsNone(finding["reported"])
        self.assertEqual(self.find(result, comparison="A")["reconciliation_state"], "MATCHED")

    def test_stale_custody_is_not_same_time_comparison(self):
        self.report()["record"]["balance_at"] = "2026-11-09T23:59:59Z"
        finding = self.find(self.evaluate(self.store()))
        self.assertEqual((finding["data_state"], finding["reconciliation_state"]), ("STALE", "NOT_EVALUATED"))
        self.assertIsNone(finding["difference"])

    def test_future_economic_event_is_excluded(self):
        store = self.store()
        raw = copy.deepcopy(self.event()["record"])
        raw.update(ref="FUTURE", occurred_at="2026-11-11T00:00:00Z", business_day="2026-11-11")
        store.ingest(raw, KNOWLEDGE_AT)
        result = self.evaluate(store)
        self.assertEqual(self.find(result)["reconciliation_state"], "MATCHED")
        self.assertEqual(len(result["ledgers"]["ASSET_A"]["event_ids"]), 3)

    def test_no_manifest_means_unknown_not_asserted_missing_event(self):
        rows = [r for r in self.rows if not (r["record"]["kind"] == "manifest" and r["record"]["stream"] == "event")]
        result = self.evaluate(self.store(rows))
        finding = self.find(result)
        self.assertEqual(finding["data_state"], "INCOMPLETE")
        self.assertTrue(any(i["code"] == "MANIFEST_ABSENT" for i in finding["issues"]))
        self.assertFalse(any(i["code"] == "MANIFEST_COUNT" for i in finding["issues"]))

    def test_manifest_must_cover_exact_economic_interval(self):
        for row in self.rows:
            if row["record"]["kind"] == "manifest" and row["record"]["stream"] == "event":
                row["record"]["coverage_to"] = "2026-11-10T12:00:00Z"
        self.assertEqual(self.find(self.evaluate(self.store()))["data_state"], "INCOMPLETE")

    def test_manifest_conflict_is_visible(self):
        store = self.store()
        raw = copy.deepcopy(next(r["record"] for r in self.rows if r["record"]["kind"] == "manifest" and r["record"]["stream"] == "event" and r["record"]["asset"] == "ASSET_A"))
        raw["expected_count"] = 4
        store.ingest(raw, KNOWLEDGE_AT)
        self.assertEqual(self.find(self.evaluate(store))["data_state"], "CONFLICT")

    def test_unknown_asset_invalid_record_blocks_completeness(self):
        store = self.store()
        raw = copy.deepcopy(self.event()["record"])
        raw["asset"] = "UNKNOWN"
        response = store.ingest(raw, KNOWLEDGE_AT)
        self.assertEqual(response["status"], "INVALID")
        result = self.evaluate(store)
        self.assertTrue(all(r["data_state"] == "INCOMPLETE" for r in result["findings"]))
        self.assertIn(response["receipt_id"], result["evidence"])

    def test_invalid_amounts_are_retained_and_do_not_fill_manifest(self):
        for value in ("NaN", "Infinity", None, "", "0.000000001", "-1", "0", 0.1, "1e1", "9" * 41):
            with self.subTest(value=value):
                rows = copy.deepcopy(self.rows)
                next(r for r in rows if r["record"].get("ref") == "A3")["record"]["amount"] = value
                store = self.store(rows)
                result = self.evaluate(store)
                self.assertEqual(self.find(result)["data_state"], "INCOMPLETE")
                self.assertEqual(len(result["ledgers"]["ASSET_A"]["event_ids"]), 2)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM receipts WHERE status='INVALID'").fetchone()[0], 1)
                self.assertEqual(self.find(result, asset="ASSET_B")["reconciliation_state"], "MATCHED")

    def test_missing_amount_is_not_zero(self):
        del self.report()["record"]["amount"]
        result = self.evaluate(self.store())
        self.assertIsNone(self.find(result)["reported"])
        self.assertEqual(self.find(result)["data_state"], "INCOMPLETE")

    def test_unsupported_correction_and_reversal_retained(self):
        for kind in ("correction", "reversal"):
            with self.subTest(kind=kind):
                store = self.store()
                raw = copy.deepcopy(self.event()["record"])
                raw["type"] = kind
                response = store.ingest(raw, KNOWLEDGE_AT)
                self.assertEqual(response["status"], "INVALID")
                self.assertIn("not supported", response["error"])
                self.assertEqual(self.find(self.evaluate(store))["reconciliation_state"], "NOT_EVALUATED")

    def test_negative_balances_only_rejected_on_complete_economic_ledger(self):
        # Withdraw first economically, then replenish: final positive is insufficient.
        self.event("A3")["record"].update(amount="6", occurred_at="2026-11-10T00:30:00Z")
        finding = self.find(self.evaluate(self.store()))
        self.assertEqual(finding["data_state"], "CONFLICT")
        self.assertTrue(any(i["code"] == "NEGATIVE_ECONOMIC_BALANCE" for i in finding["issues"]))

    def test_incomplete_negative_is_provisional_not_permanent_rejection(self):
        # I1 starts at 6: deposit 2 economically precedes withdrawal 7, but arrives late.
        rows = copy.deepcopy(self.rows)
        transfer = next(r for r in rows if r["record"].get("ref") == "A1")
        transfer["record"].update(type="withdrawal", from_investor="I1", to_investor=None, custody="external", amount="7", occurred_at="2026-11-10T02:30:00Z")
        deposit = next(r for r in rows if r["record"].get("ref") == "A2")
        deposit["received_at"] = LATER_KNOWLEDGE_AT
        store = self.store(rows)
        before = self.evaluate(store)
        self.assertEqual(self.find(before)["data_state"], "INCOMPLETE")
        self.assertTrue(any(i["code"] == "PROVISIONAL_NEGATIVE_BALANCE" for i in self.find(before)["issues"]))
        after = self.evaluate(store, LATER_KNOWLEDGE_AT)
        self.assertEqual(after["ledgers"]["ASSET_A"]["data_state"], "COMPLETE")
        self.assertEqual(after["ledgers"]["ASSET_A"]["investor_balances"], {"I1": "1", "I2": "3"})
        self.assertEqual(store.read_run(before["run_id"]), before)

    def test_same_time_sequence_and_reference_tiebreak(self):
        # At one time, deposit must precede a larger withdrawal, regardless of reception.
        self.event("A1")["record"].update(type="withdrawal", from_investor="I1", to_investor=None, custody="external", amount="7", occurred_at="2026-11-10T02:00:00Z", sequence=2)
        result = self.evaluate(self.store(list(reversed(self.rows))))
        self.assertEqual(result["ledgers"]["ASSET_A"]["data_state"], "COMPLETE")
        self.assertEqual(result["ledgers"]["ASSET_A"]["investor_balances"]["I1"], "1")

    def test_two_investor_errors_same_total_are_detected(self):
        self.report("investor", scope="I1")["record"]["amount"] = "8"
        self.report("investor", scope="I2")["record"]["amount"] = "3"
        result = self.evaluate(self.store())
        self.assertEqual(self.find(result, comparison="A", scope="I1")["difference"], "-1")
        self.assertEqual(self.find(result, comparison="A", scope="I2")["difference"], "1")
        self.assertEqual(self.find(result)["reconciliation_state"], "MATCHED")
        self.assertEqual(result["ledgers"]["ASSET_A"]["liability"], "11")

    def test_assets_never_offset(self):
        self.report()["record"]["amount"] = "8"
        self.report(asset="ASSET_B")["record"]["amount"] = "1.45"
        result = self.evaluate(self.store())
        self.assertEqual(self.find(result)["difference"], "1")
        self.assertEqual(self.find(result, asset="ASSET_B")["difference"], "-1")
        self.assertEqual(self.find(result, asset="ASSET_B")["reconciliation_state"], "MISMATCH")

    def test_invalid_later_report_does_not_silently_pass_using_old(self):
        store = self.store()
        before = self.evaluate(store)
        store.ingest({**self.report()["record"], "version": 2, "amount": None}, LATER_KNOWLEDGE_AT)
        self.assertEqual(self.evaluate(store), before)
        self.assertEqual(self.find(self.evaluate(store, LATER_KNOWLEDGE_AT))["data_state"], "INCOMPLETE")

    def test_sqlite_restart_and_immutability(self):
        store = self.store(name="restart.sqlite3")
        before = self.evaluate(store)
        with self.assertRaises(sqlite3.IntegrityError):
            store.db.execute("DELETE FROM runs")
        store.close()
        self.stores.remove(store)
        restarted = Store(Path(self.temp.name) / "restart.sqlite3")
        self.stores.append(restarted)
        self.assertEqual(restarted.read_run(before["run_id"]), before)
        self.assertEqual(self.evaluate(restarted), before)
        self.assertEqual(restarted.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_configuration_cannot_change_on_restart(self):
        self.store(name="config.sqlite3")
        changed = copy.deepcopy(self.config)
        changed["assets"]["ASSET_A"] = 2
        with self.assertRaisesRegex(ValueError, "immutable"):
            Store(Path(self.temp.name) / "config.sqlite3", changed)

    def test_quantities_stored_as_canonical_json_strings(self):
        store = self.store()
        for row in store.db.execute("SELECT payload FROM records"):
            payload = json.loads(row[0])
            if "amount" in payload:
                self.assertIsInstance(payload["amount"], str)
                self.assertNotIn(payload["amount"], ("0.10", "0.20"))

    def test_decimal_context_traps_precision_loss(self):
        with localcontext(CONTEXT):
            with self.assertRaises((Inexact, Rounded)):
                Decimal("1e40") + Decimal("1e-40")
        self.assertEqual(amount("0.10", 2), "0.1")
        with self.assertRaises(ValueError):
            amount("0.100", 2)

    def test_timezone_and_strict_timestamps(self):
        self.assertEqual(timestamp("2026-11-11T04:00:00+03:00"), "2026-11-11T01:00:00.000000Z")
        for bad in ("2026-11-11T04:00:00", "2026-11-11", "2026-11-11T04:00:00.0000001Z"):
            with self.assertRaises(ValueError):
                timestamp(bad)

    def test_evidence_is_complete_and_persistent(self):
        store = self.store()
        result = self.evaluate(store)
        for finding in result["findings"]:
            self.assertTrue(set(finding["evidence_ids"]) <= set(result["evidence"]))
            self.assertTrue(set(finding["event_ids"] + finding["report_ids"]) <= set(finding["evidence_ids"]))
            for field in ("scope", "asset", "expected", "reported", "difference_direction", "balance_at", "knowledge_at", "rule_version"):
                self.assertIn(field, finding)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 6)

    def test_all_four_demos_and_repeated_run(self):
        output = Path(self.temp.name) / "demo"
        summary = run_demos(output)
        self.assertEqual(len(summary), 6)
        self.assertTrue(all(r["verified"] for r in summary))
        original = (output / "summary.json").read_bytes()
        run_demos(output)
        self.assertEqual((output / "summary.json").read_bytes(), original)
        self.assertIn("Expected status", (output / "late_event" / "initial.md").read_text())

    def test_scenario_tags_are_not_accepted_by_engine(self):
        store = self.store()
        raw = {**self.event()["record"], "scenario": "clean"}
        self.assertEqual(store.ingest(raw, KNOWLEDGE_AT)["status"], "INVALID")


    def test_platform_customer_wallet_movements_are_explicit(self):
        self.event("A2")["record"]["custody"] = "platform"
        self.event("A3")["record"]["custody"] = "platform"
        self.report("platform_custody")["record"]["amount"] = "3"
        self.report()["record"]["amount"] = "8"
        result = self.evaluate(self.store())
        self.assertEqual(result["ledgers"]["ASSET_A"]["custody_rollforward"], {"platform": "3", "external": "8"})
        self.assertEqual(self.find(result)["reconciliation_state"], "MATCHED")

    def test_reference_tiebreak_is_economic_not_receipt_order(self):
        self.event("A1")["record"].update(type="withdrawal", from_investor="I1", to_investor=None, custody="external", amount="7", occurred_at="2026-11-10T02:00:00Z", sequence=1)
        result = self.evaluate(self.store(list(reversed(self.rows))))
        self.assertEqual(result["ledgers"]["ASSET_A"]["trace"][0]["balances_after"]["I1"], "-1")
        self.assertEqual(self.find(result)["data_state"], "CONFLICT")

    def test_manifest_excess_unique_events_is_conflict(self):
        store = self.store()
        raw = {**self.event()["record"], "ref": "EXTRA"}
        store.ingest(raw, KNOWLEDGE_AT)
        finding = self.find(self.evaluate(store))
        self.assertEqual(finding["data_state"], "CONFLICT")
        count = next(i for i in finding["issues"] if i["code"] == "MANIFEST_COUNT")
        self.assertEqual((count["expected_count"], count["observed_unique_valid_count"]), (3, 4))

    def test_invalid_configuration_types_fail_explicitly(self):
        for key, value in (("investors", None), ("assets", []), ("platform", [])):
            with self.subTest(key=key):
                config = {**self.config, key: value}
                with self.assertRaises(ValueError):
                    Store(":memory:", config)


class CliTests(unittest.TestCase):
    def call(self, *args):
        return subprocess.run([sys.executable, "-m", "crypto_reconciliation_lab", *args], text=True, capture_output=True)

    def test_demo_cli_and_generic_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            completed = self.call("demo", "--output", str(output))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("corrected_report/later: PASS", completed.stdout)
            for scenario, expected in (("clean", 0), ("custody_difference", 1)):
                result = self.call("reconcile", "--db", str(output / scenario / "evidence.sqlite3"), "--balance-at", BALANCE_AT, "--knowledge-at", KNOWLEDGE_AT, "--output", str(output / "check"))
                self.assertEqual(result.returncode, expected, result.stderr)
                run_id = result.stdout.strip()
                shown = self.call("show", "--db", str(output / scenario / "evidence.sqlite3"), "--run-id", run_id, "--output", str(output / "readback"))
                self.assertEqual(shown.returncode, expected, shown.stderr)
                self.assertEqual((output / "check.json").read_bytes(), (output / "readback.json").read_bytes())
            broken = self.call("reconcile", "--db", str(output / "missing.sqlite3"), "--balance-at", BALANCE_AT, "--knowledge-at", KNOWLEDGE_AT, "--output", str(output / "error"))
            self.assertEqual(broken.returncode, 2)

    def test_local_ingestion_keeps_malformed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, rows, _ = fixtures()
            (root / "config.json").write_text(json.dumps(config))
            (root / "input.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + '{broken json\n')
            db = str(root / "test.sqlite3")
            self.assertEqual(self.call("init", "--db", db, "--config", str(root / "config.json")).returncode, 0)
            ingestion = self.call("ingest", "--db", db, "--input", str(root / "input.jsonl"))
            self.assertEqual(ingestion.returncode, 1, ingestion.stderr)
            store = Store(db)
            try:
                result = reconcile(store, BALANCE_AT, KNOWLEDGE_AT)
                self.assertTrue(all(f["data_state"] == "INCOMPLETE" for f in result["findings"]))
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM receipts WHERE status='INVALID'").fetchone()[0], 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
