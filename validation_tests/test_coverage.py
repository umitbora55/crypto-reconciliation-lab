"""Keep version-dependent unittest failure text from becoming false PASS rows."""
import importlib.util
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('coverage_report',Path(__file__).resolve().parents[1]/'scripts/validation/summarize_coverage.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CoverageFailureTests(unittest.TestCase):
    def test_both_unittest_identity_forms_bind_the_same_failure(self):
        identity='test_example.Example.test_failure'
        for text in ('FAIL: test_failure (test_example.Example)', 'FAIL: test_failure (test_example.Example.test_failure)'):
            self.assertEqual(MODULE.failure_ids(text,'FAIL',[identity]),{identity})

    def test_unknown_failure_is_rejected_instead_of_dropped(self):
        with self.assertRaisesRegex(ValueError,'outside executed roster'):
            MODULE.failure_ids('FAIL: test_failure (unknown.Example.test_failure)','FAIL',['test_example.Example.test_failure'])
