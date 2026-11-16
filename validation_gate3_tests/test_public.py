"""Gate3 research-only checks; no protected historical test IDs are added."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('independent_gate3_public_audit', ROOT / 'scripts/validation/audit_gate3_public.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)

# Literal oracle selected before auditor execution; original Nov12 JSON rows28..31.
VALUES = ['912134', '316534', '295541', '933127']
LABELS = ['Treasury General Account (TGA) Opening Balance', 'Total TGA Deposits (Table II)',
          'Total TGA Withdrawals (Table II) (-)', 'Treasury General Account (TGA) Closing Balance']


def fixture():
    return [{'record_date': '2026-11-12', 'table_nbr': 'I', 'table_nm': 'Operating Cash Balance',
             'sub_table_name': 'Cash Balance Details', 'src_line_nbr': str(i + 1),
             'account_type': LABELS[i], 'open_today_bal': VALUES[i], 'close_today_bal': 'null'} for i in range(4)]


class Gate3PublicAuditTests(unittest.TestCase):
    def test_seven_independent_literal_residual_boundaries(self):
        expected = [(933127, 0, True, True), (933126, 1, False, True), (933128, -1, False, True),
                    (933125, 2, False, True), (933129, -2, False, True),
                    (933124, 3, False, False), (933130, -3, False, False)]
        for closing, residual, strict, diagnostic in expected:
            with self.subTest(closing=closing):
                rows = fixture()
                rows[3]['open_today_bal'] = str(closing)
                actual = AUDIT.modern_equation(rows, '2026-11-12')
                self.assertEqual((actual['residual_million_usd'], actual['strict_equal'], actual['research_only_within_two']),
                                 (residual, strict, diagnostic))

    def test_withdrawal_sign_is_subtraction(self):
        rows = fixture()
        # Wrongly adding withdrawals would give1,524,209; residual must be -591,082.
        rows[3]['open_today_bal'] = '1524209'
        actual = AUDIT.modern_equation(rows, '2026-11-12')
        self.assertEqual(actual['calculated_closing'], 933127)
        self.assertEqual(actual['residual_million_usd'], -591082)
        self.assertFalse(actual['research_only_within_two'])
        rows[2]['open_today_bal'] = '-295541'
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.modern_equation(rows, '2026-11-12')

    def test_null_amount_never_becomes_zero(self):
        for value in [None, 'null', '', 0]:
            with self.subTest(value=value):
                rows = fixture()
                rows[3]['open_today_bal'] = value
                with self.assertRaises(AUDIT.AuditError):
                    AUDIT.modern_equation(rows, '2026-11-12')

    def test_exact_source_identity_is_required(self):
        for field, replacement in [('src_line_nbr', '8'), ('account_type', LABELS[0]),
                                   ('record_date', '2026-11-11'), ('sub_table_name', 'Type of account'),
                                   ('table_nbr', 'II')]:
            with self.subTest(field=field):
                rows = fixture()
                rows[3][field] = replacement
                with self.assertRaises(AUDIT.AuditError):
                    AUDIT.modern_equation(rows, '2026-11-12')

    def test_missing_or_duplicate_selected_rows_rejected(self):
        for rows in [fixture()[:-1], fixture() + [fixture()[0]], fixture()[:3] + [fixture()[0]]]:
            with self.assertRaises(AUDIT.AuditError):
                AUDIT.modern_equation(rows, '2026-11-12')

    def test_transition_column_and_date_are_explicit(self):
        rows = fixture()
        self.assertTrue(AUDIT.modern_equation(rows, '2026-11-12')['strict_equal'])
        rows[3]['close_today_bal'] = '933127'
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.modern_equation(rows, '2026-11-12')
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.modern_equation(fixture(), '2022-04-17')

    def test_raw_missing_substitution_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            entry = {'path': 'row.body', 'bytes': 4, 'sha256': AUDIT.sha(b'good')}
            with self.assertRaises(AUDIT.InputUnavailable):
                AUDIT.bound_bytes(root, entry)
            (root / 'row.body').write_bytes(b'evil')
            with self.assertRaises(AUDIT.AuditError):
                AUDIT.bound_bytes(root, entry)
            with self.assertRaises(AUDIT.AuditError):
                AUDIT.bound_bytes(root, {**entry, 'path': '../row.body'})
            (root / 'row.body').write_bytes(b'good')
            self.assertEqual(AUDIT.bound_bytes(root, entry), b'good')

    def test_sec_trailer_and_duplicate_identity_checks(self):
        header = 'SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n'
        row = '20240102|C00948114|AGRIW|4784|AGRIFORCE|.\n'
        body = header + row + 'Trailer record count 1\nTrailer total quantity of shares 4784\n'
        self.assertEqual(AUDIT.parse_sec_text(body)['missing_prices'], 1)
        for changed in [body.replace('count 1', 'count 2'), body.replace('shares 4784', 'shares 4785')]:
            with self.assertRaises(AUDIT.AuditError):
                AUDIT.parse_sec_text(changed)
        duplicated = AUDIT.parse_sec_text(header + row + row, require_trailers=False)
        self.assertEqual(duplicated['duplicates'], [['20240102', 'C00948114']])

    def test_sec_symbol_bound_is_a_warning_not_natural_label(self):
        header = 'SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n'
        parsed = AUDIT.parse_sec_text(header + '20240102|34638F105|ABCDEFGHIJ|1|EXAMPLE|1.00\n', False)
        self.assertEqual(parsed['symbol_warnings'], [])
        parsed = AUDIT.parse_sec_text(header + '20240102|34638F105|F105SPINOFF|1|EXAMPLE|1.00\n', False)
        self.assertEqual(len(parsed['symbol_warnings']), 1)
        self.assertEqual(parsed['issues'], [])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(AUDIT.AuditError):
            AUDIT.read_json('{"record_date":"2026-11-12","record_date":"2026-11-11"}')

    def test_auditor_uses_only_stdlib_and_no_dynamic_helpers(self):
        tree = ast.parse((ROOT / 'scripts/validation/audit_gate3_public.py').read_text())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(n.name.split('.')[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module.split('.')[0])
        self.assertEqual(set(modules), {'__future__', 'argparse', 'collections', 'csv', 'datetime', 'hashlib',
                                       'html', 'io', 'json', 'pathlib', 're', 'sys', 'zipfile'})


if __name__ == '__main__':
    unittest.main()
