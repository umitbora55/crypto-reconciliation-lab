"""New research tests; not members of the 875 historical application IDs."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gate3_trust_audit", ROOT / "scripts/validation/audit_gate3_trust.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class TrustAuditTests(unittest.TestCase):
    def test_candidate_cannot_supply_its_own_anchor(self):
        anchor = {"origin": "LAB_TEST_ONLY", "public_key_hex": "a" * 64, "manifest_sha256": "b" * 64}
        for field in ("public_key_hex", "manifest_sha256", "origin"):
            candidate = {**anchor, field: "forged"}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "EXTERNAL_CONTEXT_MISMATCH"):
                audit.check_context(candidate, anchor)
        audit.check_context(copy.deepcopy(anchor), anchor)

    def test_non_lab_origin_is_not_promoted(self):
        anchor = {"origin": "INSTITUTIONAL"}
        with self.assertRaisesRegex(ValueError, "NOT_LAB_CONTEXT"):
            audit.check_context(anchor, anchor)

    def test_missing_or_substituted_raw_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_bytes(b"original")
            entries = [{"path": str(path), "bytes": 8, "sha256": audit.digest(b"original")}]
            audit.verify_files(entries)
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "INPUT_IDENTITY"):
                audit.verify_files(entries)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "MISSING_OR_SYMLINK_INPUT"):
                audit.verify_files(entries)

    def test_duplicate_input_scope_is_rejected(self):
        entry = {"path": "never-read", "bytes": 0, "sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "DUPLICATE_INPUT"):
            audit.verify_files([entry, entry])

    def test_label_types_and_false_negative_denominators(self):
        rows = [{"truth": True, "alert": False}, {"truth": False, "alert": False},
                {"truth": True, "alert": True}, {"truth": False, "alert": True}]
        self.assertEqual(audit.confusion(rows, "truth", "alert"), {"TP": 1, "FP": 1, "TN": 1, "FN": 1})
        with self.assertRaisesRegex(ValueError, "NON_BOOLEAN_LABEL"):
            audit.confusion([{"truth": "false", "alert": False}], "truth", "alert")

    def test_event_identity_is_exact_string_and_content_sensitive(self):
        row = {"kind": "event", "asset": "COIN", "occurred_at": "2026-01-05T01:00:00Z",
               "sequence": 1, "source": "P", "platform": "P", "business_day": "2026-01-05", "ref": "9007199254740993"}
        original = audit.independent_events(json.dumps({"rows": [{"record": row}]}).encode())
        self.assertEqual(original[0]["event_id"], '["P","P","2026-01-05","9007199254740993"]')
        altered = audit.independent_events(json.dumps({"rows": [{"record": {**row, "ref": "9007199254740992"}}]}).encode())
        self.assertNotEqual(original, altered)


if __name__ == "__main__":
    unittest.main()
