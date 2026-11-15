"""Small-profile maintenance coverage must retain actual fixed test identities."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('execution_subset', Path(__file__).resolve().parents[1] / 'scripts/release_execution_maintenance.py')
subset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subset)


def complete(profile):
    expected = list(subset.cases(profile))
    return {'format': 'execution-maintenance-tests-v1', 'profile': profile, 'status': 'PASS',
            'origin': '/remote/env/lib/site-packages/crypto_reconciliation_lab/__init__.py',
            'isolated': True, 'expected_ids': expected, 'discovered_ids': list(expected),
            'executed_ids': list(expected), 'executed': len(expected), 'skips': 0,
            'failures': 0, 'errors': 0, 'expected_failures': 0, 'unexpected_successes': 0}


class ExecutionMaintenanceSubsetTests(unittest.TestCase):
    def test_complete_fixed_core_and_auth_subsets_are_accepted(self):
        for profile in ('core', 'auth-only'):
            row = complete(profile)
            self.assertEqual(subset.validate_result(row, profile, row['origin'])['status'], 'PASS')

    def test_missing_or_substituted_identity_fails_despite_unchanged_counts(self):
        for field in ('expected_ids', 'discovered_ids', 'executed_ids'):
            row = complete('core')
            row[field][-1] = 'test_other.Other.test_unchecked'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'fixed subset'):
                subset.validate_result(row, 'core', row['origin'])

    def test_wrong_import_origin_isolation_and_skips_are_rejected(self):
        for field, value in (('origin', '/wrong/source.py'), ('isolated', False),
                             ('skips', 1), ('errors', 1), ('failures', 1),
                             ('expected_failures', 1), ('unexpected_successes', 1)):
            row = complete('core'); origin = row['origin']; row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'fixed subset'):
                subset.validate_result(row, 'core', origin)

    def test_core_subset_cannot_be_relabelled_as_auth_coverage(self):
        row = complete('core'); row['profile'] = 'auth-only'
        with self.assertRaisesRegex(ValueError, 'fixed subset'):
            subset.validate_result(row, 'auth-only', row['origin'])


if __name__ == '__main__':
    unittest.main()
