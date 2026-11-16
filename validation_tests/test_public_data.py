"""Finite SYNTHETIC tests: none of these fixtures is a downloaded public record."""
import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validation.fetch_public_data import plan, verify_offline, fetch

from validation_lab.public_data import (
    MAX_INT, FTD_FIELDS, cashflow_check, fiscal_api_rows, ftd_profile,
    map_dts_day, validate_cached_sources, whole_number,
)


def cash(**changes):
    return dict({"record_date": "2025-01-02", "opening": "100", "deposits": "40",
                 "withdrawals": "30", "closing": "110"}, **changes)


def ftd(*lines):
    return "|".join(FTD_FIELDS) + "\n" + "\n".join(lines) + "\n"


def mapping():
    return {"review_status": "OFFICIAL_DOCUMENTATION_VERIFIED", "reference": "SYNTHETIC_TEST_ONLY_NOT_SOURCE_DOCUMENTATION",
            "fields": {name: {"table": "test", "where": {"account_type": name}, "field": "value"}
                       for name in ("opening", "deposits", "withdrawals", "closing")}}


def request_evidence(root, selected_ids=None):
    requests = [r for r in plan() if selected_ids is None or r["id"] in selected_ids]
    protocol = {"requests": requests}
    (root / "protocol.json").write_text(json.dumps(protocol))
    register = {"protocol_sha256": hashlib.sha256((root / "protocol.json").read_bytes()).hexdigest(),
                "sources": [dict(r, status="DATA_UNAVAILABLE", data_class="NOT_OBSERVED") for r in requests]}
    write_register(root, register)
    return register


def write_register(root, register):
    (root / "source-register.json").write_text(json.dumps(register))


class PublicDataContracts(unittest.TestCase):
    def test_exact_independent_arithmetic(self):
        result = cashflow_check(cash())
        self.assertEqual((result["status"], result["integer_calculated_closing"], result["sql_calculated_closing"]), ("EXACT", 110, 110))

    def test_wrong_closing_is_mismatch(self):
        result = cashflow_check(cash(closing="109"))
        self.assertEqual((result["status"], result["residual_million_usd"]), ("MISMATCH", 1))

    def test_zero_is_present(self):
        self.assertEqual(cashflow_check(cash(opening="0", deposits="0", withdrawals="0", closing="0"))["status"], "EXACT")

    def test_missing_never_zero(self):
        for absent in (None, "", "null", "None"):
            with self.subTest(absent=absent), self.assertRaises(ValueError):
                cashflow_check(cash(deposits=absent))

    def test_nonintegral_and_float_rejected(self):
        for value in (1.1, 1, True, "1.5", "1e3", "1,000", " 1", "١"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                whole_number(value)

    def test_negative_flow_rejected(self):
        with self.assertRaises(ValueError):
            cashflow_check(cash(withdrawals="-1"))

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            cashflow_check(cash(fake="1"))

    def test_rounding_requires_reviewed_reference(self):
        with self.assertRaises(ValueError):
            cashflow_check(cash(closing="109"), tolerance=1)

    def test_rounding_boundary_is_separate_status(self):
        self.assertEqual(cashflow_check(cash(closing="108"), tolerance=2, rounding_reference="SYNTHETIC_POLICY")["status"], "WITHIN_ROUNDING")
        self.assertEqual(cashflow_check(cash(closing="107"), tolerance=2, rounding_reference="SYNTHETIC_POLICY")["status"], "MISMATCH")

    def test_sql_integer_boundary_no_float(self):
        self.assertEqual(cashflow_check(cash(opening=str(MAX_INT), deposits="0", withdrawals="0", closing=str(MAX_INT)))["status"], "EXACT")
        with self.assertRaisesRegex(ValueError, "OVERFLOW"):
            cashflow_check(cash(opening=str(MAX_INT), deposits="1"))

    def test_invalid_dates_rejected(self):
        for value in ("2025-02-30", "2025-1-2", "20250102", "2025-01-02T00:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cashflow_check(cash(record_date=value))

    def test_source_mapping_requires_verified_contract(self):
        with self.assertRaisesRegex(ValueError, "DOCUMENTATION_UNVERIFIED"):
            map_dts_day({}, "2025-01-02", {})

    def test_mapping_selects_exact_account_not_month_column(self):
        rows = [{"record_date": "2025-01-02", "account_type": name, "value": value, "month_value": "999"}
                for name, value in cash().items() if name != "record_date"]
        self.assertEqual(map_dts_day({"test": rows}, "2025-01-02", mapping()), cash())

    def test_duplicate_or_missing_source_grain_rejected(self):
        rows = [{"record_date": "2025-01-02", "account_type": name, "value": value}
                for name, value in cash().items() if name != "record_date"]
        for candidate in (rows + [rows[0]], rows[1:]):
            with self.subTest(count=len(candidate)), self.assertRaisesRegex(ValueError, "SOURCE_GRAIN"):
                map_dts_day({"test": candidate}, "2025-01-02", mapping())

    def test_null_deprecated_balance_not_imputed(self):
        rows = [{"record_date": "2025-01-02", "account_type": name, "value": None if name == "closing" else value}
                for name, value in cash().items() if name != "record_date"]
        with self.assertRaises(ValueError):
            map_dts_day({"test": rows}, "2025-01-02", mapping())

    def test_api_complete_nonempty_page(self):
        rows = [{"record_date": "2025-01-02", "value": "1"}]
        self.assertEqual(fiscal_api_rows(json.dumps({"data": rows, "meta": {"total-count": 1, "total-pages": 1}})), rows)

    def test_api_empty_partial_duplicate_keys_rejected(self):
        payloads = ['{"data":[],"meta":{"total-count":0,"total-pages":0}}',
                    '{"data":[{"record_date":"2025-01-02"}],"meta":{"total-count":10001,"total-pages":2}}',
                    '{"data":[],"data":[{"record_date":"2025-01-02"}],"meta":{"total-count":1,"total-pages":1}}']
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                fiscal_api_rows(payload)

    def test_ftd_valid_two_dates_two_instruments(self):
        result = ftd_profile(ftd("20250102|000000001|TEST_A|25|Synthetic A|10.00", "20250103|000000002|TEST_B|0|Synthetic B|."))
        self.assertEqual((result["rows"], result["distinct_dates"], result["distinct_cusips"], result["invalid_rows"]), (2, 2, 2, 0))
        self.assertEqual(result["new_failure_count"], "NOT_IDENTIFIABLE")
        self.assertEqual(result["missing_price_rows"], 1)

    def test_ftd_negative_quantity_retained_as_issue(self):
        result = ftd_profile(ftd("20250102|000000001|TEST_A|-1|Synthetic A|10.00"))
        self.assertEqual(result["issues"][0]["record"]["QUANTITY (FAILS)"], "-1")
        self.assertEqual(result["issues"][0]["problems"], ["QUANTITY_DOMAIN"])

    def test_ftd_duplicate_grain_warned(self):
        line = "20250102|000000001|TEST_A|25|Synthetic A|10.00"
        result = ftd_profile(ftd(line, line))
        self.assertEqual(result["duplicate_keys"][0]["count"], 2)
        self.assertEqual(result["status"], "QUALITY_ISSUES")

    def test_ftd_invalid_schema_empty_and_date(self):
        for text in ("DATE|CUSIP\n", "|".join(FTD_FIELDS) + "\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                ftd_profile(text)
        result = ftd_profile(ftd("20250230|000000001|TEST_A|1|Synthetic A|10.00"))
        self.assertIn("SETTLEMENT_DATE", result["issues"][0]["problems"])

    def test_ftd_wrong_unicode_instrument_and_quantity(self):
        result = ftd_profile(ftd("20250102|00000000İ|TEST_A|1.5|Synthetic A|10.00"))
        self.assertEqual(result["issues"][0]["problems"], ["CUSIP_FORMAT", "QUANTITY_DOMAIN"])

    def test_unavailable_data_does_not_become_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request_evidence(root)
            result = validate_cached_sources(root, root / "result.json")
            self.assertEqual(result["status"], "REAL_DATA_UNVERIFIED")
            self.assertEqual(result["real_financial_equalities_verified"], 0)
            with self.assertRaises(FileExistsError):
                validate_cached_sources(root, root / "result.json")

    def test_downloaded_hash_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "body").write_text("changed")
            register = request_evidence(root)
            register["sources"][0].update(status="DOWNLOADED", data_class="SOURCE_DOCUMENTATION", path="body", bytes=7, sha256="0" * 64)
            write_register(root, register)
            with self.assertRaises(ValueError):
                validate_cached_sources(root, root / "result.json")

    def test_inventory_complete_unavailable_evidence_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request_evidence(root)
            self.assertEqual(len(verify_offline(root)["sources"]), len(plan()))

    def test_inventory_empty_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"] = []
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_missing_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"].pop()
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_duplicate_same_count_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"][-1] = register["sources"][0].copy()
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_unexpected_id_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"][-1]["id"] = "unregistered-source"
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_source_url_substitution_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"][0]["url"] = "https://example.invalid/substituted"
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_consistently_rehashed_protocol_url_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            protocol = json.loads((root / "protocol.json").read_text())
            protocol["requests"][0]["url"] = "https://www.sec.gov/substituted"
            register["sources"][0]["url"] = "https://www.sec.gov/substituted"
            (root / "protocol.json").write_text(json.dumps(protocol))
            register["protocol_sha256"] = hashlib.sha256((root / "protocol.json").read_bytes()).hexdigest()
            write_register(root, register)
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_inventory_consistent_truncation_needs_external_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request_evidence(root, selected_ids=[plan()[0]["id"]])
            with self.assertRaises(ValueError):
                verify_offline(root)

    def test_cached_validation_enforces_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = request_evidence(root)
            register["sources"] = []
            write_register(root, register)
            with self.assertRaises(ValueError):
                validate_cached_sources(root, root / "result.json")

    def test_direct_fetch_obeys_no_network_before_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new"
            with patch.dict(os.environ, {"NO_NETWORK": "1"}), patch("scripts.validation.fetch_public_data.urllib.request.build_opener", side_effect=AssertionError("unexpected network opener")) as opener:
                with self.assertRaisesRegex(ValueError, "NO_NETWORK"):
                    fetch(target)
                opener.assert_not_called()
            self.assertFalse(target.exists())

    def test_sec_fetch_needs_official_landing_link_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new"
            with patch.dict(os.environ, {"NO_NETWORK": "0"}), patch("scripts.validation.fetch_public_data.urllib.request.build_opener", side_effect=AssertionError("unexpected network opener")) as opener:
                with self.assertRaisesRegex(ValueError, "SEC_LINK"):
                    fetch(target, selected_ids=["sec-ftd-202401a"])
                opener.assert_not_called()
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
