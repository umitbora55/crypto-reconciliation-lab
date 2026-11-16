"""Finite synthetic controls for the Gate 2 public-data adapter."""
import io
import unittest
import zipfile

from validation_lab.gate2_public_data import ACCOUNT_ROLES, direct_day, sec_zip_text, adapted_input


def source_rows():
    values = {"opening": "100", "deposits": "40", "withdrawals": "30", "closing": "110"}
    operating = [{"record_date": "2025-01-02", "account_type": label, "table_nbr": "I", "sub_table_name": "Cash Balance Details",
                  "open_today_bal": values[role], "open_month_bal": "999", "close_today_bal": "null"}
                 for role, label in ACCOUNT_ROLES.items()]
    detail = [{"record_date": "2025-01-02", "account_type": "Treasury General Account Total " + kind,
               "transaction_type": kind, "transaction_today_amt": values[role]}
              for role, kind in (("deposits", "Deposits"), ("withdrawals", "Withdrawals"))]
    return operating, detail


def zipped(text, name="cnsfails-test"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, text)
    return stream.getvalue()


HEADER = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
BODY = "20250102|000000001|TEST|25|SYNTHETIC|10.00\n"
TRAILERS = "Trailer record count 1\nTrailer total quantity of shares 25\n"


class Gate2PublicContracts(unittest.TestCase):
    def test_direct_exact_and_cross_table(self):
        rows, detail = source_rows()
        result = direct_day(rows, detail, "2025-01-02")
        self.assertEqual(result["status"], "EXACT")
        self.assertEqual(result["decimal_calculated_closing"], "110")
        self.assertTrue(all(r["equal_to_table_i"] for r in result["table_ii_cross_checks"].values()))

    def test_daily_not_monthly_and_null_not_zero(self):
        rows, detail = source_rows()
        result = direct_day(rows, detail, "2025-01-02")
        self.assertEqual(result["opening"], 100)
        rows[0]["open_today_bal"] = "null"
        with self.assertRaises(ValueError):
            direct_day(rows, detail, "2025-01-02")

    def test_missing_or_duplicate_role_rejected(self):
        rows, detail = source_rows()
        for candidate in (rows[1:], rows + [rows[0]]):
            with self.subTest(count=len(candidate)), self.assertRaises(ValueError):
                direct_day(candidate, detail, "2025-01-02")

    def test_signed_negative_total_is_not_abs(self):
        rows, detail = source_rows()
        rows[2]["open_today_bal"] = "-30"
        with self.assertRaises(ValueError):
            direct_day(rows, detail, "2025-01-02")

    def test_rounding_diagnostic_is_not_exact(self):
        rows, detail = source_rows()
        rows[3]["open_today_bal"] = "109"
        result = direct_day(rows, detail, "2025-01-02")
        self.assertEqual(result["status"], "MISMATCH")
        self.assertEqual(result["residual_million_usd"], 1)
        self.assertEqual(result["rounding_diagnostic"], "WITHIN_FIXED_2_MILLION_BOUND")

    def test_legacy_not_relabelled_direct(self):
        result = direct_day([], [], "2019-01-02")
        self.assertEqual(result["status"], "NOT_RUN_LEGACY_FOUR_TOTALS_ABSENT")
        self.assertNotIn("normalized", result)

    def test_cross_table_disagreement_retained(self):
        rows, detail = source_rows()
        detail[0]["transaction_today_amt"] = "41"
        result = direct_day(rows, detail, "2025-01-02")
        self.assertEqual(result["table_ii_cross_checks"]["deposits"]["difference"], 1)
        self.assertFalse(result["table_ii_cross_checks"]["deposits"]["equal_to_table_i"])

    def test_adapter_labels_authored_semantics(self):
        data = adapted_input({"record_date": "2025-01-02", "opening": "100", "deposits": "40", "withdrawals": "30", "closing": "110"})
        self.assertEqual(data["data_class"], "REAL_PUBLIC_ADAPTED")
        self.assertEqual(len(data["rows"]), len(data["lineage"]))
        self.assertEqual(sum(r["record"]["kind"] == "event" for r in data["rows"]), 2)

    def test_sec_trailers_checked_not_financial_rows(self):
        text, member = sec_zip_text(zipped(HEADER + BODY + TRAILERS))
        self.assertEqual(text, HEADER + BODY)
        self.assertEqual(member["trailer"]["record_count"], 1)
        self.assertEqual(member["trailer"]["quantity_sum"], 25)

    def test_sec_wrong_trailer_count_rejected(self):
        with self.assertRaises(ValueError):
            sec_zip_text(zipped(HEADER + BODY + TRAILERS.replace("count 1", "count 0")))

    def test_sec_wrong_trailer_total_rejected(self):
        with self.assertRaises(ValueError):
            sec_zip_text(zipped(HEADER + BODY + TRAILERS.replace("shares 25", "shares 26")))

    def test_sec_missing_trailers_rejected(self):
        with self.assertRaises(ValueError):
            sec_zip_text(zipped(HEADER + BODY))

    def test_sec_zip_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            sec_zip_text(zipped(HEADER + BODY + TRAILERS, "../escape"))


if __name__ == "__main__":
    unittest.main()
