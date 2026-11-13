"""Transport expectations are literal; no producer function derives the oracle."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.admission.feed import ingest_feed, snapshot_feed
from crypto_reconciliation_lab.cli import main
from crypto_reconciliation_lab.demo import fixtures, BALANCE_AT, KNOWLEDGE_AT


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.rows, _ = fixtures()
        self.path = self.root / "owned.sqlite3"
        self.store = Store(self.path, self.config)
        self.addCleanup(self.store.close)

    def wire(self, value):
        return (json.dumps(value, sort_keys=True) + "\n").encode()

    def plan(self, lines):
        data = b"".join(lines)
        return {"format": "admission-plan-v1", "input_sha256": hashlib.sha256(data).hexdigest(),
                "input_bytes": len(data), "planned_lines": len(lines), "framing": "utf8-lf-jsonl-v1"}

    def counts(self):
        return {name: self.store.db.execute("SELECT count(*) FROM " + name).fetchone()[0]
                for name in ("records", "receipts", "admission_streams", "delivery_effects", "delivery_attempts", "runs")}

    def deliver(self, lines, stream="S"):
        plan = self.plan(lines)
        return [self.store.ingest_delivery(stream, n, b, plan) for n, b in enumerate(lines, 1)]

    def test_exact_replay_reuses_physical_receipt_and_original_result(self):
        line = self.wire(self.rows[0]); plan = self.plan([line])
        first = self.store.ingest_delivery("S", 1, line, plan)
        retry = self.store.ingest_delivery("S", 1, line, plan, observed_at="2026-12-01T00:00:00Z")
        self.assertTrue(first["ack"] and retry["ack"])
        self.assertEqual(retry["outcome"], "REPLAY")
        self.assertEqual(retry["core_result"], first["core_result"])
        self.assertEqual(retry["core_receipt_row_id"], first["core_receipt_row_id"])
        self.assertEqual(self.counts(), dict(records=1, receipts=1, admission_streams=1, delivery_effects=1, delivery_attempts=2, runs=0))

    def test_legacy_direct_ingest_still_appends_each_physical_receipt(self):
        row = self.rows[0]
        one = self.store.ingest(row["record"], row["received_at"])
        two = self.store.ingest(row["record"], row["received_at"])
        self.assertEqual((one["status"], two["status"]), ("ACCEPTED", "DUPLICATE"))
        self.assertEqual(one["receipt_id"], two["receipt_id"])
        self.assertEqual(self.counts()["receipts"], 2)
        self.assertEqual(self.counts()["delivery_effects"], 0)

    def test_new_transport_sequence_uses_core_duplicate_semantics(self):
        line = self.wire(self.rows[0])
        first, second = self.deliver([line, line])
        self.assertEqual((first["disposition"], second["disposition"]), ("ACCEPTED", "DUPLICATE"))
        self.assertNotEqual(first["core_receipt_row_id"], second["core_receipt_row_id"])
        self.assertEqual(self.counts()["records"], 1)
        self.assertEqual(self.counts()["receipts"], 2)

    def test_economic_conflict_is_terminal_core_result_not_transport_block(self):
        changed = copy.deepcopy(self.rows[0]); changed["record"]["amount"] = "9"
        first, second = self.deliver([self.wire(self.rows[0]), self.wire(changed)])
        self.assertEqual(second["disposition"], "CONFLICT")
        self.assertTrue(second["ack"])
        self.assertFalse(second["blocked"])
        self.assertEqual(self.counts()["records"], 2)

    def test_exact_bytes_distinguish_spacing_and_permanently_block(self):
        line = self.wire(self.rows[0]); plan = self.plan([line, line])
        first = self.store.ingest_delivery("S", 1, line, plan)
        changed = line[:-1] + b" \n"
        conflict = self.store.ingest_delivery("S", 1, changed, plan)
        self.assertEqual(conflict["outcome"], "TRANSPORT_CONFLICT")
        self.assertFalse(conflict["ack"])
        self.assertTrue(conflict["durable"] and conflict["blocked"])
        blocked = self.store.ingest_delivery("S", 2, line, plan)
        self.assertEqual(blocked["outcome"], "BLOCKED")
        self.assertEqual(blocked["committed_prefix"], 1)
        self.assertEqual(self.counts()["receipts"], 1)
        row = self.store.db.execute("SELECT payload,core_receipt_id FROM delivery_effects").fetchone()
        self.assertEqual(bytes(row[0]), line)
        self.assertEqual(row[1], first["core_receipt_row_id"])

    def test_gap_attempt_does_not_bind_plan_or_advance_and_is_retryable(self):
        lines = [self.wire(r) for r in self.rows[:2]]; plan = self.plan(lines)
        gap = self.store.ingest_delivery("S", 2, lines[1], plan)
        self.assertEqual((gap["outcome"], gap["committed_prefix"], gap["ack"]), ("GAP", 0, False))
        self.assertEqual(self.counts()["admission_streams"], 0)
        self.assertEqual(self.counts()["delivery_attempts"], 1)
        self.deliver(lines)
        state = self.store.feed_status("S")
        self.assertEqual((state["status"], state["committed_prefix"], state["gap_count"]), ("COMPLETE", 2, 1))
        self.assertEqual(state["pending_sequences"], [])

    def test_out_of_range_has_no_core_effect(self):
        line = self.wire(self.rows[0])
        response = self.store.ingest_delivery("S", 2, line, self.plan([line]))
        self.assertEqual(response["outcome"], "OUT_OF_RANGE")
        self.assertEqual(self.counts()["records"], 0)

    def test_invalid_financial_record_is_quarantined_and_acked_atomically(self):
        row = copy.deepcopy(self.rows[0]); row["record"]["amount"] = "NaN"
        result, = self.deliver([self.wire(row)])
        self.assertTrue(result["ack"])
        self.assertEqual(result["disposition"], "INVALID")
        self.assertEqual(self.counts()["records"], 0)
        receipt = self.store.db.execute("SELECT record_id,status,error FROM receipts").fetchone()
        self.assertIsNone(receipt[0]); self.assertEqual(receipt[1], "INVALID"); self.assertTrue(receipt[2])
        self.assertEqual(self.store.feed_status("S")["core_invalid_count"], 1)

    def test_numeric_amount_is_core_invalid_not_silently_converted_to_text(self):
        row = copy.deepcopy(self.rows[0]); row["record"]["amount"] = 0.25
        result, = self.deliver([self.wire(row)])
        self.assertEqual(result["disposition"], "INVALID")
        self.assertEqual(self.counts()["receipts"], 1)

    def test_bad_json_and_duplicate_keys_have_inspectable_terminal_dispositions(self):
        lines = [b'{bad}\n', b'{"record":{},"record":{},"received_at":null}\n',
                 b'{"record":NaN,"received_at":null}\n', b'{"record":1e999,"received_at":null}\n', b'\xff\n']
        for response in self.deliver(lines):
            self.assertTrue(response["ack"])
            self.assertEqual(response["disposition"], "REJECTED_FRAME")
            self.assertIsNone(response["core_result"])
        self.assertEqual(self.counts()["receipts"], 0)
        self.assertEqual(self.store.feed_status("S")["frame_rejected_count"], 5)
        self.assertEqual([bytes(x[0]) for x in self.store.db.execute("SELECT payload FROM delivery_effects ORDER BY sequence")], lines)

    def test_snapshot_framing_refusals_write_nothing(self):
        path = self.root / "input.jsonl"
        for payload in (b'', b'{}', b'{}\r\n', b'\n', b'{}\n \n', b'\xef\xbb\xbf{}\n', b'x' * 65536 + b'\n'):
            with self.subTest(payload_length=len(payload)):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    ingest_feed(self.store, path, "S")
        self.assertTrue(all(v == 0 for v in self.counts().values()))

    def test_snapshot_rejects_symlink(self):
        path = self.root / "input.jsonl"; path.write_bytes(self.wire(self.rows[0]))
        link = self.root / "link.jsonl"; link.symlink_to(path)
        with self.assertRaises(ValueError):
            snapshot_feed(link)

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        path = self.root / "unbounded-pipe"
        os.mkfifo(path)
        code = ("from crypto_reconciliation_lab.admission.feed import snapshot_feed\n"
                "import sys\ntry: snapshot_feed(sys.argv[1])\n"
                "except ValueError: sys.exit(0)\nelse: sys.exit(3)\n")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(path)], capture_output=True,
                                text=True, timeout=1)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exclusive_lock_keeps_feed_busy_response_explicit(self):
        path = self.root / "input.jsonl"; path.write_bytes(self.wire(self.rows[0]))
        lock = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(lock.close)
        self.store.db.execute("PRAGMA busy_timeout=20")
        lock.execute("BEGIN EXCLUSIVE")
        try:
            result = ingest_feed(self.store, path, "S", busy_timeout_ms=1)
        finally:
            lock.execute("ROLLBACK")
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["responses"][0]["outcome"], "RETRYABLE_BUSY")
        self.assertEqual(result["delivery_status"]["status"], "UNKNOWN")
        self.assertTrue(all(v == 0 for v in self.counts().values()))

    def test_cli_open_busy_is_explicit_retriable_without_ack(self):
        path = self.root / "input.jsonl"; path.write_bytes(self.wire(self.rows[0]))
        lock = sqlite3.connect(self.path, isolation_level=None); self.addCleanup(lock.close)
        lock.execute("BEGIN EXCLUSIVE")
        output, errors = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = main(["ingest-feed", "--db", str(self.path), "--input", str(path),
                             "--stream-id", "S", "--busy-timeout-ms", "1"])
        finally:
            lock.execute("ROLLBACK")
        self.assertEqual(code, 1, errors.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual((result["status"], result["outcome"], result["ack"]),
                         ("INCOMPLETE", "RETRYABLE_BUSY", False))

    def test_changed_committed_prefix_cannot_replace_first_plan(self):
        path = self.root / "input.jsonl"; original = self.wire(self.rows[0]); path.write_bytes(original)
        ingest_feed(self.store, path, "S")
        path.write_bytes(original[:-1] + b' \n')
        result = ingest_feed(self.store, path, "S")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["responses"][0]["outcome"], "PLAN_CONFLICT")
        stored = self.store.db.execute("SELECT input_sha256,input_bytes FROM admission_streams").fetchone()
        self.assertEqual(tuple(stored), (hashlib.sha256(original).hexdigest(), len(original)))
        self.assertEqual(self.counts()["receipts"], 1)

    def test_shortened_file_with_identical_prefix_is_not_successful_eof(self):
        lines = [self.wire(r) for r in self.rows[:2]]; path = self.root / "input.jsonl"
        path.write_bytes(b''.join(lines)); snapshot = snapshot_feed(path)
        self.store.ingest_delivery("S", 1, lines[0], snapshot.plan)
        path.write_bytes(lines[0])
        result = ingest_feed(self.store, path, "S")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["delivery_status"]["pending_sequences"], [2])
        self.assertEqual(self.counts()["receipts"], 1)

    def test_busy_is_retriable_without_ack_or_fabricated_attempt(self):
        lock = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(lock.close); lock.execute("BEGIN IMMEDIATE")
        line = self.wire(self.rows[0]); plan = self.plan([line])
        result = self.store.ingest_delivery("S", 1, line, plan, busy_timeout_ms=1)
        self.assertEqual(result["outcome"], "RETRYABLE_BUSY")
        self.assertFalse(result["ack"] or result["durable"])
        self.assertIsNone(result["attempt_id"])
        self.assertTrue(all(v == 0 for v in self.counts().values()))
        lock.execute("ROLLBACK")
        self.assertTrue(self.store.ingest_delivery("S", 1, line, plan)["ack"])

    def test_three_precommit_exception_barriers_roll_back_all_layers(self):
        line = self.wire(self.rows[0]); plan = self.plan([line])
        for barrier in ("ingest_before_receipt", "delivery_after_receipt", "delivery_before_commit"):
            def fail(point):
                if point == barrier:
                    raise RuntimeError(barrier)
            with self.subTest(barrier=barrier), self.assertRaisesRegex(RuntimeError, barrier):
                self.store.ingest_delivery("S", 1, line, plan, fault=fail)
            self.assertTrue(all(v == 0 for v in self.counts().values()))

    def test_postcommit_response_loss_is_resolved_by_replay(self):
        line = self.wire(self.rows[0]); plan = self.plan([line])
        def fail(point):
            if point == "delivery_after_commit":
                raise RuntimeError("response lost")
        with self.assertRaisesRegex(RuntimeError, "response lost"):
            self.store.ingest_delivery("S", 1, line, plan, fault=fail)
        self.assertEqual(self.counts()["receipts"], 1)
        retry = self.store.ingest_delivery("S", 1, line, plan)
        self.assertEqual((retry["outcome"], retry["core_receipt_row_id"]), ("REPLAY", 1))

    def test_full_file_replay_preserves_financial_run_and_does_not_evaluate_implicitly(self):
        path = self.root / "input.jsonl"; path.write_bytes(b''.join(self.wire(r) for r in self.rows))
        first = ingest_feed(self.store, path, "S")
        self.assertEqual(first["status"], "COMPLETE"); self.assertEqual(self.counts()["runs"], 0)
        result = reconcile(self.store, BALANCE_AT, KNOWLEDGE_AT)
        self.assertEqual(result["ledgers"]["ASSET_A"]["investor_balances"], {"I1": "7", "I2": "4"})
        self.assertEqual(result["ledgers"]["ASSET_B"]["liability"], "0.5")
        replay = ingest_feed(self.store, path, "S")
        self.assertEqual(len(replay["responses"]), 30)
        self.assertTrue(all(r["outcome"] == "REPLAY" for r in replay["responses"]))
        self.assertEqual(self.counts()["receipts"], 30)
        self.assertEqual(reconcile(self.store, BALANCE_AT, KNOWLEDGE_AT), result)
        self.assertEqual(self.store.read_run(result["run_id"]), result)

    def test_feed_status_is_read_only_and_observation_is_not_financial_time(self):
        line = self.wire(self.rows[0])
        self.store.ingest_delivery("S", 1, line, self.plan([line]), observed_at="2030-01-01T00:00:00Z")
        before = self.store.db.total_changes
        self.assertEqual(self.store.feed_status("S")["status"], "COMPLETE")
        self.assertEqual(self.store.db.total_changes, before)
        received = self.store.db.execute("SELECT received_at FROM receipts").fetchone()[0]
        self.assertTrue(received.startswith("2026-11-10"))

    def test_cli_admission_and_status_are_separate_from_reconciliation(self):
        path = self.root / "input.jsonl"; path.write_bytes(self.wire(self.rows[0]))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["ingest-feed", "--db", str(self.path), "--input", str(path), "--stream-id", "CLI"])
        self.assertEqual(code, 0); self.assertEqual(json.loads(output.getvalue())["financial_evaluation"], "NOT_RUN")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["feed-status", "--db", str(self.path), "--stream-id", "CLI"]), 0)
        self.assertEqual(json.loads(output.getvalue())["committed_prefix"], 1)
        self.assertEqual(self.counts()["runs"], 0)

    def test_invalid_protocol_fields_do_not_create_delivery_history(self):
        line = self.wire(self.rows[0]); plan = self.plan([line])
        for stream, sequence, payload, kwargs in ((" bad", 1, line, {}), ("S", True, line, {}),
                ("S", 0, line, {}), ("S", 1, "text", {}), ("S", 1, line, {"busy_timeout_ms": 5001})):
            with self.subTest(stream=stream, sequence=sequence), self.assertRaises(ValueError):
                self.store.ingest_delivery(stream, sequence, payload, plan, **kwargs)
        bad = dict(plan, planned_lines=True)
        with self.assertRaises(ValueError):
            self.store.ingest_delivery("S", 1, line, bad)
        self.assertTrue(all(v == 0 for v in self.counts().values()))
