"""Exercise real runner lifecycle accounting with finite adversarial suites.

Only discovery and source inventory are replaced by tiny fixed fixtures; the
runner, TextTestRunner, TestResult callbacks and rejection path execute normally.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.validation import run_gate4_tests as runner


def make_case(mode, body_calls):
    class Probe(unittest.TestCase):
        def id(self):
            return 'probe.Probe.test_body'

        def test_body(self):
            body_calls.append('ran')
            self.assertEqual(21, 3 * 7)

        def run(self, result=None):
            if mode == 'normal':
                return super().run(result)
            result.startTest(self)
            if mode == 'no_outcome':
                result.stopTest(self)
                return result
            if mode == 'substituted_success':
                substituted = make_case('normal', [])
                substituted.id = lambda: 'probe.Substituted.test_body'
                result.addSuccess(substituted)
            else:
                result.addSuccess(self)
            if mode == 'duplicate_success':
                result.addSuccess(self)
            if mode != 'missing_stop':
                result.stopTest(self)
            if mode == 'duplicate_stop':
                result.stopTest(self)
            return result

    return Probe('test_body')


class RunnerEvidenceTests(unittest.TestCase):
    def exercise(self, mode='normal', mutate=None):
        body_calls = []
        case = make_case(mode, body_calls)
        expected = [case.id()]
        sources = {'fixed-fixture.py': {'bytes': 1, 'sha256': 'a' * 64}}
        record = {'format': 'gate4-test-inventory-v1', 'created_utc': '2026-11-17T00:00:00Z',
                  'historical_base': runner.BASE, 'historical_files': 445,
                  'expected_ids': expected, 'expected_count': 1, 'source_files': sources}
        if mutate:
            mutate(record)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps(record))
            suite = unittest.TestSuite([case])
            with patch.object(runner, 'static_ids', return_value=expected), \
                    patch.object(runner, 'source_inventory', return_value=sources), \
                    patch.object(runner.unittest.defaultTestLoader, 'discover', return_value=suite), \
                    patch.object(runner.sys, 'path', list(runner.sys.path)), \
                    contextlib.redirect_stderr(io.StringIO()):
                summary = runner.run(inventory, root / 'result')
            return summary, body_calls

    def test_real_success_executes_body_and_all_lifecycle_identities_match(self):
        summary, body_calls = self.exercise()
        self.assertEqual(summary['status'], 'PASS')
        self.assertEqual(body_calls, ['ran'])
        for key in ('expected_ids', 'discovered_ids', 'executed_ids', 'successful_ids', 'completed_ids'):
            self.assertEqual(summary[key], ['probe.Probe.test_body'])

    def test_same_no_outcome_substitute_cannot_be_a_passing_test(self):
        summary, body_calls = self.exercise('no_outcome')
        self.assertEqual(body_calls, [])
        self.assertEqual(summary['executed'], 1)
        self.assertFalse(any(summary['counters'].values()))
        self.assertEqual(summary['successful_ids'], [])
        self.assertEqual(summary['status'], 'FAIL')

    def test_missing_stop_is_not_complete_success(self):
        summary, _ = self.exercise('missing_stop')
        self.assertEqual(summary['completed_ids'], [])
        self.assertEqual(summary['status'], 'FAIL')

    def test_duplicate_success_is_not_collapsed_to_a_set(self):
        summary, _ = self.exercise('duplicate_success')
        self.assertEqual(len(summary['successful_ids']), 2)
        self.assertEqual(summary['status'], 'FAIL')

    def test_duplicate_completion_is_not_collapsed_to_a_set(self):
        summary, _ = self.exercise('duplicate_stop')
        self.assertEqual(len(summary['completed_ids']), 2)
        self.assertEqual(summary['status'], 'FAIL')

    def test_same_count_substituted_success_identity_is_rejected(self):
        summary, _ = self.exercise('substituted_success')
        self.assertEqual(len(summary['successful_ids']), len(summary['expected_ids']))
        self.assertNotEqual(summary['successful_ids'], summary['expected_ids'])
        self.assertEqual(summary['status'], 'FAIL')

    def test_wrong_historical_population_and_base_are_rejected(self):
        for field, value in [('historical_files', 444), ('historical_base', '0' * 40)]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                self.exercise(mutate=lambda record: record.update({field: value}))

    def test_boolean_and_float_manifest_counts_are_not_integer_identity(self):
        for field, value in [('expected_count', True), ('expected_count', 1.0), ('historical_files', 445.0)]:
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                self.exercise(mutate=lambda record: record.update({field: value}))

    def test_empty_duplicate_or_missing_inventory_identity_is_rejected(self):
        mutations = [lambda record: record.update(expected_ids=[], expected_count=0),
                     lambda record: record.update(expected_ids=record['expected_ids'] * 2, expected_count=2),
                     lambda record: record.pop('expected_count')]
        for ordinal, mutation in enumerate(mutations):
            with self.subTest(ordinal=ordinal), self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                self.exercise(mutate=mutation)


if __name__ == '__main__':
    unittest.main()
