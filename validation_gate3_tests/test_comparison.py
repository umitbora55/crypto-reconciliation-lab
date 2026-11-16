"""New Gate3 research checks; never part of the 875 protected test roster."""
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/validation/audit_gate3_comparison.py'
SPEC = importlib.util.spec_from_file_location('independent_comparison_audit', SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def comparison_records():
    # Pairing must give median9, whereas subtracting medians gives7.
    times = {'production': [1, 2, 10, 11, 12], 'stdlib_integer': [10, 11, 1, 2, 3],
             'sqlite_integer': [10, 11, 1, 2, 3]}
    records = []
    for size, repeat, seed, method in audit.expected_order():
        wall = times[method][repeat]
        records.append({'events': size, 'repeat': repeat, 'seed': seed, 'method': method,
                        'status': 'PASS', 'exit_code': 0, 'timed_out': False,
                        'metrics': {'wall_seconds': wall, 'cpu_seconds': 0.1,
                                    'peak_rss_kib': 128, 'disk_bytes': 4096,
                                    'throughput_events_per_second': size/wall,
                                    'artifacts': {'export.json': {'bytes': 20}},
                                    'phases': {p: {'wall_seconds': 0.001} for p in audit.PHASES}}})
    return records


def literal_receipts():
    rows = [{'record': {'kind': 'opening', 'scope': k, 'amount': '0.00'}}
            for k in ('I0', 'I1', 'I2', 'I3', 'platform', 'external')]
    rows += [{'record': {'kind': 'event', 'ref': 'E0', 'amount': '1.00', 'type': 'deposit',
                         'from_investor': None, 'to_investor': 'I0', 'custody': 'external'}},
             {'record': {'kind': 'event', 'ref': 'E1', 'amount': '0.40', 'type': 'transfer',
                         'from_investor': 'I0', 'to_investor': 'I1', 'custody': None}}]
    rows += [{'record': {'kind': 'report', 'scope': k, 'amount': value}}
             for k, value in {'I0': '0.60', 'I1': '0.40', 'I2': '0.00', 'I3': '0.00',
                              'platform': '0.00', 'external': '1.00'}.items()]
    return {'events': 2, 'rows': rows}


class ComparisonReviewTests(unittest.TestCase):
    def test_missing_duplicate_or_reordered_trials_rejected(self):
        original = comparison_records()
        for records in (original[:-1], original + [original[0]], [original[1], original[0], *original[2:]]):
            with self.subTest(length=len(records)), self.assertRaisesRegex(ValueError, 'trial'):
                audit.verify_roster(records)

    def test_failed_or_skipped_trial_cannot_be_complete(self):
        for field, value in (('status', 'NOT_RUN'), ('exit_code', -9), ('timed_out', True)):
            records = comparison_records()
            records[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'successful exits'):
                audit.verify_roster(records)

    def test_paired_median_is_not_difference_of_unpaired_medians(self):
        summary, comparisons = audit.statistics_from_trials(comparison_records())
        pair = comparisons[0]
        self.assertEqual(pair['median_difference_seconds'], 9)
        self.assertEqual(pair['median_ratio'], 4)
        self.assertEqual(pair['n'], 5)
        self.assertEqual(summary[0]['wall_seconds']['p50'], 3)
        self.assertEqual(summary[0]['wall_seconds']['p95_nearest_rank'], 11)
        self.assertEqual(summary[2]['wall_seconds']['p50'], 10)

    def test_nonfinite_resource_measurement_rejected(self):
        records = comparison_records()
        records[0]['metrics']['cpu_seconds'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'resource metric'):
            audit.statistics_from_trials(records)

    def test_independent_literal_financial_fold(self):
        observed = audit.independent_arithmetic(literal_receipts())
        self.assertEqual(observed['balances'], {'I0': 60, 'I1': 40, 'I2': 0, 'I3': 0})
        self.assertEqual(observed['custody'], {'platform': 0, 'external': 100})
        self.assertEqual(observed['liability'], 100)

    def test_substituted_identity_or_wrong_report_rejected(self):
        original = literal_receipts()
        changed_id = copy.deepcopy(original)
        changed_id['rows'][6]['record']['ref'] = 'E2'
        changed_report = copy.deepcopy(original)
        changed_report['rows'][8]['record']['amount'] = '0.61'
        for data in (changed_id, changed_report):
            with self.subTest(data=data), self.assertRaises(ValueError):
                audit.independent_arithmetic(data)


if __name__ == '__main__':
    unittest.main()
