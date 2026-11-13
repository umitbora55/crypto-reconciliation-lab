"""S5-F2 supplemental regression: one saved pointer has one finding meaning."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab.triage.contracts import validate_features
from crypto_reconciliation_lab.triage.features import build_features
from test_triage_features import public_fixture


class CrossReferenceConsistencyTests(unittest.TestCase):
    def test_current_pointer_cannot_name_different_asset_findings_in_one_run(self):
        with tempfile.TemporaryDirectory(prefix="stage51-cross-ref-") as temporary:
            root = Path(temporary)
            database, _, _ = public_fixture(root / "public")
            features = build_features(root / "public", root / "features")
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            invalid = deepcopy(features)
            first, second = invalid["units"]
            self.assertEqual((first["asset"], second["asset"]), ("ASSET_A", "ASSET_B"))
            first_ref, second_ref = first["finding_refs"][0], second["finding_refs"][0]
            self.assertEqual(first_ref["run_id"], second_ref["run_id"])
            self.assertEqual(first_ref["payload_sha256"], second_ref["payload_sha256"])
            self.assertEqual(first_ref["payload_file"], second_ref["payload_file"])
            old_pointer = second_ref["pointer"]
            self.assertEqual((first_ref["pointer"], old_pointer), ("/findings/0", "/findings/3"))
            second_ref["pointer"] = first_ref["pointer"]
            # Keep the second unit internally consistent: only the cross-unit
            # binding now exposes two distinct asset findings at the same pointer.
            for proof in second["feature_provenance"].values():
                for source in proof["sources"]:
                    if source["run_id"] == second_ref["run_id"] and source["pointer"] == old_pointer:
                        source["pointer"] = first_ref["pointer"]
                        source["evidence_pointer"] = first_ref["pointer"] + "/evidence_ids"
            with self.assertRaises(ValueError):
                validate_features(invalid)
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
