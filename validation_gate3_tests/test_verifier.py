"""New Gate 3 finite-evidence tests; excluded from the protected 875 IDs."""
import copy
import hashlib
import io
import json
import unittest
import zipfile

from validation_lab import gate3_verifier as guard, identity_reference as identity


class EvidenceVerifierTests(unittest.TestCase):
    def test_missing_raw_and_candidate_self_hash_do_not_replace_external_pin(self):
        original = b"original external capture"
        pin = hashlib.sha256(original).hexdigest()
        guard.verify_raw(original, pin)
        for changed in (None, b"", original + b" "):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                guard.verify_raw(changed, pin)

    def treasury(self):
        names = ["Treasury General Account (TGA) Opening Balance",
                 "Total TGA Deposits (Table II)",
                 "Total TGA Withdrawals (Table II) (-)",
                 "Treasury General Account (TGA) Closing Balance"]
        rows = [{"record_date": "2026-11-12", "table_nbr": "I",
                 "sub_table_name": "Cash Balance Details", "account_type": name,
                 "src_line_nbr": str(i), "open_today_bal": amount,
                 "close_today_bal": "null"}
                for i, (name, amount) in enumerate(zip(names, ["100", "20", "30", "90"]), 1)]
        detail = [{"record_date": "2026-11-12", "account_type": name,
                   "transaction_type": kind, "transaction_today_amt": amount}
                  for name, kind, amount in
                  [("Treasury General Account Total Deposits", "Deposits", "20"),
                   ("Treasury General Account Total Withdrawals", "Withdrawals", "30")]]
        raw = json.dumps({"data": rows, "meta": {"total-count": 4, "total-pages": 1}}).encode()
        expected = {"date": "2026-11-12", "lines": ["1", "2", "3", "4"],
                    "accounts": names, "amounts": ["100", "20", "30", "90"],
                    "field": "open_today_bal", "publication_vintage": "UNKNOWN",
                    "expected_residual": 0}
        kwargs = {"raw_bytes": raw, "expected_raw_sha256": hashlib.sha256(raw).hexdigest(),
                  "expected": expected}
        return rows, detail, kwargs

    def test_balanced_source_substitution_is_rejected_even_when_equation_still_matches(self):
        rows, detail, kwargs = self.treasury()
        self.assertEqual(guard.verify_treasury(rows, detail, "2026-11-12", **kwargs)["residual_million_usd"], 0)
        changed = copy.deepcopy(rows)
        changed[0]["open_today_bal"] = "101"
        changed[3]["open_today_bal"] = "91"
        with self.assertRaises(ValueError):
            guard.verify_treasury(changed, detail, "2026-11-12", **kwargs)

    def test_valid_post_transition_null_never_becomes_amount_or_known_vintage(self):
        rows, detail, kwargs = self.treasury()
        for claims in ({"field": "close_today_bal"}, {"publication_vintage": "2026-11-01"}):
            with self.subTest(claims=claims), self.assertRaises(ValueError):
                guard.verify_treasury(rows, detail, "2026-11-12", **kwargs, **claims)

    def test_self_consistent_source_hash_does_not_override_external_row_identity(self):
        rows, detail, kwargs = self.treasury()
        rows[0]["src_line_nbr"] = "99"
        raw = json.dumps({"data": rows, "meta": {"total-count": 4, "total-pages": 1}}).encode()
        kwargs.update(raw_bytes=raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            guard.verify_treasury(rows, detail, "2026-11-12", **kwargs)

    def test_valid_lab_signature_cannot_replace_separately_selected_context(self):
        events = [{"event_id": "original", "content": b"literal"}]
        scope = {"publisher": "LAB", "dataset": "D", "partition": "P",
                 "event_day": "2026-01-05", "balance_cut": "2026-01-05T23:00:00Z",
                 "record_kind": "event"}
        manifest = identity.make_manifest(events, scope)
        expected = identity.context_for(manifest)
        forged = [{"event_id": "substituted", "content": b"literal"}]
        replacement = identity.make_manifest(forged, scope)
        context = identity.context_for(replacement, 2, "LAB-KEY-2")
        envelope = identity.sign_manifest(replacement, 2, "LAB-KEY-2")
        self.assertEqual(identity.verify_reference(envelope, forged, context)["outcome"], "MATCH")
        with self.assertRaises(ValueError):
            guard.verify_identity(envelope, forged, context, expected)

    def test_original_symbol_warning_is_retained_but_decoded_substitution_is_rejected(self):
        text = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n20240102|34638F105|F105SPINOFF|2|Example|.\n"
        original = text + "Trailer record count 1\nTrailer total quantity of shares 2\n"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("sample.txt", original)
        raw = stream.getvalue()
        url = "https://www.sec.gov/files/data/fails-deliver-data/sample.zip"
        landing = ('<a href="' + url + '">sample</a>').encode()
        kwargs = {"expected_raw_sha256": hashlib.sha256(raw).hexdigest(), "expected_url": url}
        result = guard.verify_sec(raw, url, landing, **kwargs)
        self.assertEqual(len(result["symbol_bound_warnings"]), 1)
        self.assertEqual(result["rows"], 1)
        with self.assertRaises(ValueError):
            guard.verify_sec(raw, url, landing, candidate_text=text.replace("34638F105", "000000001"), **kwargs)


if __name__ == "__main__":
    unittest.main()
