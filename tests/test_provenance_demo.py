"""Exercise the small producer and its real verifier CLI, with literal oracles."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab.provenance.demo import run_demo


def load(path):
    return json.loads(Path(path).read_bytes())


class ProvenanceDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = (Path(cls.temporary.name) / "demonstration").resolve()
        cls.summary = run_demo(cls.root)
        cls.cases = {row["id"]: row for row in cls.summary["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_ten_groups_and_actual_cli_outcomes_are_present(self):
        self.assertEqual(self.summary["status"], "PASS")
        self.assertEqual({row["id"] for row in self.summary["scenario_groups"]}, {
            "clean_two_publishers", "signed_custody_difference", "historical_correction_quarantine",
            "rotation_and_revocation", "exact_replay", "multiple_physical_candidates",
            "missing_full_snapshot", "legacy_and_protected", "external_expectations", "semantic_relations"})
        self.assertEqual(len(self.cases), 24)
        literal = {"clean": (0, []), "signed_mismatch": (0, []),
                   "history_original": (0, []), "history_corrected": (0, []), "history_quarantine": (0, []),
                   "rotation": (0, []), "replay": (0, []),
                   "ambiguous": (3, ["MULTIPLE_RECEIPT_CANDIDATES"]),
                   "missing_snapshot": (3, ["MISSING_SIGNED_SNAPSHOT"]), "prefix_only": (3, ["MISSING_SIGNED_SNAPSHOT"]),
                   "legacy": (3, ["UNSIGNED_LEGACY"]), "broken_protected_link": (2, ["PROTECTED_LINK"]),
                   "protected_downgrade": (2, ["PROFILE_MISMATCH"]), "wrong_run": (2, ["RUN_IDENTITY"]),
                   "wrong_capture": (2, ["CAPTURE_BINDING"]), "wrong_policy": (2, ["POLICY_BINDING"]),
                   "hidden_policy_head": (2, ["POLICY_BINDING"]), "removed_receipt": (2, ["EVIDENCE_SCOPE"]),
                   "changed_receipt": (2, ["RECEIPT_BINDING"]), "removed_quarantine": (2, ["EVIDENCE_SCOPE"]),
                   "removed_correction": (2, ["EVIDENCE_SCOPE"]), "changed_effect": (2, ["DELIVERY_RELATION"]),
                   "changed_endorsement": (2, ["ENDORSEMENT_BINDING"]), "broken_link_and_missing_snapshot": (2, ["PROTECTED_LINK"])}
        self.assertEqual(set(self.cases), set(literal))
        for name, (code, reasons) in literal.items():
            with self.subTest(case=name):
                case = self.cases[name]
                self.assertTrue(case["passed"])
                actual = case["actual"]
                self.assertEqual((actual["exit_code"], actual["reasons"]), (code, reasons))
                self.assertEqual(actual["status"], {0: "VERIFIED_FOR_CAPTURE", 3: "PARTIAL", 2: "FAILED"}[code])

    def test_real_commands_and_output_bytes_back_each_result(self):
        for case in self.cases.values():
            with self.subTest(case=case["id"]):
                command = load(self.root / case["command"])
                self.assertIn("verify-provenance", command["argv"])
                self.assertIn(str(self.root / case["bundle"]), command["argv"])
                self.assertIn(str(self.root / case["expectations"]), command["argv"])
                self.assertEqual(command["exit_code"], case["actual"]["exit_code"])
                for stream in ("stdout", "stderr"):
                    raw = (self.root / command[stream]).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), command[stream + "_sha256"])
                self.assertEqual(load(self.root / command["stdout"]), load(self.root / case["verification"]))

    def test_literal_finance_is_separate_from_signature_acceptance(self):
        for name in ("clean", "signed_mismatch"):
            findings = self.cases[name]["financial"]["findings"]
            expected = {("TOKEN_X", "A", "Aster"): ("7", "7", "0"),
                        ("TOKEN_X", "A", "Birch"): ("4", "4", "0"),
                        ("TOKEN_X", "B", "customer_liability"): ("11", "10", "1") if name == "signed_mismatch" else ("11", "11", "0"),
                        ("TOKEN_Y", "A", "Aster"): ("0.3", "0.3", "0"),
                        ("TOKEN_Y", "A", "Birch"): ("0.2", "0.2", "0"),
                        ("TOKEN_Y", "B", "customer_liability"): ("0.5", "0.5", "0")}
            actual = {(r["asset"], r["comparison"], r["scope"]): (r["expected"], r["reported"], r["difference"]) for r in findings}
            self.assertEqual(actual, expected)
            self.assertEqual(self.cases[name]["actual"]["exit_code"], 0)
        mismatch = [r for r in self.cases["signed_mismatch"]["financial"]["findings"] if r["reconciliation_state"] == "MISMATCH"]
        self.assertEqual([(r["asset"], r["comparison"], r["difference"]) for r in mismatch], [("TOKEN_X", "B", "1")])

    def test_old_run_raw_bytes_remain_and_invalid_signed_record_is_visible(self):
        fixture = self.root / "fixtures/history"
        proof = load(fixture / "fixture-proof.json")
        with sqlite3.connect(fixture / "capture.sqlite3") as db:
            for phase in ("original", "corrected", "quarantine"):
                raw = db.execute("SELECT payload FROM runs WHERE id=?", (proof["runs"][phase],)).fetchone()[0].encode()
                bundle_raw = (self.root / self.cases["history_" + phase]["bundle"] / "run.json").read_bytes()
                self.assertEqual(raw, bundle_raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), proof["saved_payload_sha256"][phase])
        original = self.cases["history_original"]["financial"]["findings"]
        corrected = self.cases["history_corrected"]["financial"]["findings"]
        self.assertEqual([r["expected"] for r in original if r["asset"] == "TOKEN_X"], ["7", "4", "11"])
        self.assertEqual([r["expected"] for r in corrected if r["asset"] == "TOKEN_X"], ["8", "4", "12"])
        quarantine = load(self.root / self.cases["history_quarantine"]["bundle"] / "capture.json")
        rejected = [r for r in quarantine["tables"]["receipts"] if r["error"]]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(json.loads(rejected[0]["raw"])["record"]["amount"], "NaN")
        financial = self.cases["history_quarantine"]["financial"]["findings"]
        self.assertEqual({r["reconciliation_state"] for r in financial if r["asset"] == "TOKEN_Y"}, {"NOT_EVALUATED"})

    def test_replay_and_later_duplicate_do_not_change_saved_finance(self):
        clean = (self.root / self.cases["clean"]["bundle"] / "run.json").read_bytes()
        for name in ("replay", "ambiguous", "rotation"):
            self.assertEqual((self.root / self.cases[name]["bundle"] / "run.json").read_bytes(), clean)
        replay = load(self.root / self.cases["replay"]["bundle"] / "capture.json")["tables"]
        ambiguous = load(self.root / self.cases["ambiguous"]["bundle"] / "capture.json")["tables"]
        self.assertEqual((len(replay["receipts"]), len(replay["delivery_effects"]), len(replay["delivery_attempts"])), (30, 30, 60))
        self.assertEqual(len(ambiguous["receipts"]), 31)
        self.assertEqual(len({row["receipt_hash"] for row in ambiguous["receipts"]}), 30)

    def test_trust_input_is_external_and_all_negative_manifests_are_coherent(self):
        for name, case in self.cases.items():
            bundle = self.root / case["bundle"]
            self.assertFalse((self.root / case["expectations"]).is_relative_to(bundle))
            manifest = load(bundle / "manifest.json")
            actual_names = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() and p.name != "manifest.json"}
            self.assertEqual(set(manifest["files"]), actual_names)
            for relative, identity in manifest["files"].items():
                raw = (bundle / relative).read_bytes()
                self.assertEqual(identity, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, (name, relative))
            self.assertFalse(any(p.suffix in (".sqlite3", ".db") for p in bundle.rglob("*")))
        self.assertEqual(self.summary["trust_role"], "TEST-ONLY_CONTROLLED_FIXTURE_OPERATOR")
        self.assertEqual(self.summary["run_creation_authorization_cut"], "NOT_RECORDED")

    def test_four_epochs_are_known_before_export_and_original_decisions_stay_separate(self):
        proof = load(self.root / "fixtures/rotation/fixture-proof.json")
        expected = load(self.root / self.cases["rotation"]["expectations"])
        self.assertEqual([r["epoch"] for r in proof["known_policy_epochs"]], [1, 2, 3, 4])
        self.assertEqual(expected["policies"], proof["known_policy_epochs"])
        capture = load(self.root / self.cases["rotation"]["bundle"] / "capture.json")["tables"]
        original_ids = {r["decision_id"] for r in capture["auth_delivery_links"]}
        original = [r for r in capture["auth_decisions"] if r["id"] in original_ids]
        self.assertEqual({r["epoch"] for r in original}, {1})
        replay = [r for r in capture["auth_decisions"] if r["id"] not in original_ids]
        self.assertTrue(replay)
        self.assertEqual({r["epoch"] for r in replay}, {4})
        self.assertEqual({r["decision"] for r in replay}, {"HISTORICAL_REPLAY"})


if __name__ == "__main__":
    unittest.main()
