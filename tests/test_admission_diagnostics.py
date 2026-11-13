"""Malformed duplicate-key diagnostics must preserve terminal delivery evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from crypto_reconciliation_lab import Store


CONFIG = {"platform": "P1", "custodian": "C1", "investors": ["I1", "I2"],
          "assets": {"ASSET_A": 8, "ASSET_B": 2}, "opening_at": "2026-11-10T00:00:00.000000Z"}
LONE_KEYS = (r"\ud800", r"\udfff", r"before\ud800after")
CONTROL_KEYS = ("ascii", "Türkçe", r"\ud83d\ude00", r"\u0000", r"\n")


def three_lines(key):
    # Literal opening records, independent of the production demo/calculator.
    valid = []
    for scope, amount in (("I1", "6"), ("I2", "4")):
        record = {"kind": "opening", "asset": "ASSET_A", "source": "P1", "platform": "P1",
                  "scope": scope, "balance_at": CONFIG["opening_at"], "amount": amount}
        valid.append((json.dumps({"record": record, "received_at": CONFIG["opening_at"]},
                                 sort_keys=True) + "\n").encode("utf-8"))
    invalid = ('{"record":{"' + key + '":1,"' + key + '":2},"received_at":null}\n').encode("utf-8")
    return [valid[0], invalid, valid[1]]


def declared_plan(lines):
    payload = b"".join(lines)
    return {"format": "admission-plan-v1", "input_sha256": hashlib.sha256(payload).hexdigest(),
            "input_bytes": len(payload), "planned_lines": 3, "framing": "utf8-lf-jsonl-v1"}


class AdmissionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def store(self, name):
        store = Store(self.root / (name + ".sqlite3"), CONFIG)
        self.addCleanup(store.close)
        return store

    def check_state(self, store, lines, attempts):
        state = store.feed_status("SURROGATE")
        self.assertEqual((state["status"], state["committed_prefix"], state["pending_sequences"]),
                         ("COMPLETE", 3, []))
        self.assertFalse(state["blocked"])
        self.assertEqual((state["frame_rejected_count"], state["core_invalid_count"]), (1, 0))
        self.assertEqual(state["financial_evaluation"], "NOT_RUN")
        effects = state["effects"]
        self.assertEqual([r["disposition"] for r in effects], ["ACCEPTED", "REJECTED_FRAME", "ACCEPTED"])
        self.assertEqual([r["sequence"] for r in effects], [1, 2, 3])
        self.assertEqual([r["payload_hex"] for r in effects], [line.hex() for line in lines])
        self.assertEqual([r["payload_sha256"] for r in effects], [hashlib.sha256(line).hexdigest() for line in lines])
        self.assertEqual([r["core_receipt_id"] for r in effects], [1, None, 2])
        self.assertIsNone(effects[1]["core_receipt_hash"])
        self.assertIsNone(effects[1]["core_result"])
        self.assertIn("duplicate JSON key", effects[1]["reason"])
        effects[1]["reason"].encode("utf-8", errors="strict")
        json.dumps(state, ensure_ascii=False).encode("utf-8", errors="strict")
        for name, expected in (("records", 2), ("receipts", 2), ("delivery_effects", 3),
                               ("delivery_attempts", attempts), ("runs", 0), ("findings", 0), ("evidence", 0)):
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0], expected, name)
        payloads = [json.loads(r[0]) for r in store.db.execute("SELECT payload FROM records ORDER BY payload")]
        self.assertEqual({r["scope"]: r["amount"] for r in payloads}, {"I1": "6", "I2": "4"})
        first_attempts = state["attempts"][:3]
        self.assertEqual([r["outcome"] for r in first_attempts], ["COMMITTED"] * 3)
        self.assertEqual([(r["effect_stream_id"], r["effect_sequence"]) for r in first_attempts],
                         [("SURROGATE", 1), ("SURROGATE", 2), ("SURROGATE", 3)])
        self.assertEqual(first_attempts[1]["reason"], effects[1]["reason"])
        self.assertEqual(first_attempts[1]["payload_hex"], lines[1].hex())
        self.assertEqual(first_attempts[1]["payload_sha256"], hashlib.sha256(lines[1]).hexdigest())
        for name, value in declared_plan(lines).items():
            if name != "format":
                self.assertEqual(state["plan"][name], value)
        self.assertEqual(store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        return state

    def check_api_roundtrip(self, key, index):
        store = self.store(str(index)); lines = three_lines(key); plan = declared_plan(lines)
        first = [store.ingest_delivery("SURROGATE", n, line, plan) for n, line in enumerate(lines, 1)]
        self.assertTrue(all(r["ack"] and r["durable"] for r in first))
        before = self.check_state(store, lines, 3)
        retry = [store.ingest_delivery("SURROGATE", n, line, plan) for n, line in enumerate(lines, 1)]
        self.assertEqual([r["outcome"] for r in retry], ["REPLAY"] * 3)
        self.assertEqual([r["core_receipt_row_id"] for r in retry], [r["core_receipt_row_id"] for r in first])
        self.assertEqual([r["core_result"] for r in retry], [r["core_result"] for r in first])
        after = self.check_state(store, lines, 6)
        self.assertEqual(after["effects"], before["effects"])
        self.assertEqual(after["attempts"][:3], before["attempts"])
        self.assertEqual(after["replay_count"], 3)
        self.assertEqual([r["outcome"] for r in after["attempts"][3:]], ["REPLAY"] * 3)

    def test_lone_surrogate_api_rejection_is_durable_and_exact_replay_reuses_it(self):
        for index, key in enumerate(LONE_KEYS):
            with self.subTest(key=key):
                self.check_api_roundtrip(key, index)

    def test_unicode_and_control_duplicate_key_rejections_remain_terminal(self):
        for index, key in enumerate(CONTROL_KEYS):
            with self.subTest(key=key):
                self.check_api_roundtrip(key, index)

    def test_real_cli_surrogate_rejection_completes_and_replays_with_controlled_exit(self):
        for index, key in enumerate(LONE_KEYS):
            with self.subTest(key=key):
                store = self.store(str(index)); lines = three_lines(key)
                feed = self.root / (str(index) + ".jsonl"); feed.write_bytes(b"".join(lines))
                argv = [sys.executable] + (["-I"] if sys.flags.isolated else []) + [
                    "-B", "-m", "crypto_reconciliation_lab", "ingest-feed", "--db", str(self.root / (str(index) + ".sqlite3")),
                    "--input", str(feed), "--stream-id", "SURROGATE"]
                env = dict(os.environ); env.pop("PYTHONPATH", None); env.pop("PYTHONHOME", None)
                snapshots = []
                for attempt in (1, 2):
                    done = subprocess.run(argv, capture_output=True, env=env, timeout=10)
                    self.assertEqual(done.returncode, 1, done.stderr.decode("utf-8"))
                    self.assertEqual(done.stderr, b"")
                    report = json.loads(done.stdout)
                    self.assertEqual(report["status"], "COMPLETE")
                    self.assertEqual(report["financial_evaluation"], "NOT_RUN")
                    self.assertEqual([r["outcome"] for r in report["responses"]],
                                     ["COMMITTED" if attempt == 1 else "REPLAY"] * 3)
                    snapshots.append(self.check_state(store, lines, attempt * 3))
                self.assertEqual(snapshots[1]["effects"], snapshots[0]["effects"])
                self.assertEqual(snapshots[1]["replay_count"], 3)
