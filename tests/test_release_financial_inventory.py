"""Mandatory financial scope checks; frozen bytes are the independent oracle."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

from crypto_reconciliation_lab.demo import run_demos

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_financial_inventory_helper',
                                             PROJECT / 'scripts/release_financial_scope.py')
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


class FinancialInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.reports = Path(cls.temporary.name) / 'reports'
        run_demos(cls.reports)
        cls.reference = scope.load_financial_reference(PROJECT / scope.REFERENCE_PATH)

    def test_complete_real_demo_reports_bind_all_twelve_frozen_files(self):
        result = scope.compare_required_reports(self.reports, self.reference, 'stage1')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['expected_count'], 12)
        self.assertEqual(result['compared_count'], 12)
        self.assertEqual(result['count'], 12)
        self.assertEqual(result['files'], self.reference['reports']['stage1']['files'])
        self.assertEqual(result['reference_identity']['sha256'],
                         '4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e')
        self.assertEqual(result['excluded_producer_ancillary_files'], [
            'clean/config.json', 'corrected_report/config.json', 'custody_difference/config.json',
            'late_event/config.json', 'summary.json', 'summary.md'])
        self.assertTrue(result['full_bytes_and_run_ids_equal'])

    def test_missing_renamed_extra_and_one_byte_changed_outputs_fail(self):
        for mutation in ('missing', 'renamed', 'extra', 'byte'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                reports = Path(temporary) / 'reports'
                shutil.copytree(self.reports, reports)
                target = reports / 'clean/initial.json'
                if mutation == 'missing':
                    target.unlink()
                elif mutation == 'renamed':
                    target.rename(reports / 'clean/other.json')
                elif mutation == 'extra':
                    (reports / 'extra.json').write_text('{}')
                else:
                    target.write_bytes(target.read_bytes() + b' ')
                with self.assertRaises(ValueError):
                    scope.compare_required_reports(reports, self.reference, 'stage1')

    def test_in_memory_reference_cannot_shrink_or_substitute_after_preflight(self):
        for mutation in ('empty', 'same-count', 'bool-size', 'float-count'):
            with self.subTest(mutation=mutation):
                reference = deepcopy(self.reference)
                files = reference['reports']['stage1']['files']
                if mutation == 'empty':
                    files.clear()
                elif mutation == 'same-count':
                    files['other/initial.json'] = files.pop('clean/initial.json')
                elif mutation == 'bool-size':
                    files['clean/initial.json']['bytes'] = True
                else:
                    reference['matrix']['cases'] = 69.0
                with self.assertRaisesRegex(ValueError, 'FINANCIAL_REFERENCE:'):
                    scope.compare_required_reports(self.reports, reference, 'stage1')

    def test_matrix_requires_exact_names_integer_zeros_and_integer_evaluation_count(self):
        counters = dict.fromkeys(('clean_false_mismatch', 'false_definitive', 'healthy_scope_block',
            'missed_mismatch', 'missing_evidence', 'missing_reason', 'structural_error',
            'unnecessary_not_evaluated', 'wrong_amount', 'wrong_state'), 0)
        result = {'status': 'PASS', 'evaluations': 162, 'counters': counters}
        scope.validate_matrix_result(result)
        for mutation in ('wrong-name', 'bool-zero', 'float-count', 'missing', 'nonzero'):
            with self.subTest(mutation=mutation):
                altered = deepcopy(result)
                if mutation == 'wrong-name':
                    altered['counters']['unrelated'] = altered['counters'].pop('wrong_state')
                elif mutation == 'bool-zero':
                    altered['counters']['wrong_state'] = False
                elif mutation == 'float-count':
                    altered['evaluations'] = 162.0
                elif mutation == 'missing':
                    del altered['counters']['wrong_state']
                else:
                    altered['counters']['wrong_state'] = 1
                with self.assertRaises(ValueError):
                    scope.validate_matrix_result(altered)
