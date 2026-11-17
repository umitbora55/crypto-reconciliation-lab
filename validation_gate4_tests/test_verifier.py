"""Independent evidence-reader attacks; all timing fixtures are synthetic tests."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/validation/audit_gate4_evidence.py'
spec = importlib.util.spec_from_file_location('gate4_independent_auditor', SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class IndependentVerifierTests(unittest.TestCase):
    def test_integer_oracle_has_fixed_external_balances(self):
        for (size, seed), (_, _, _, residual) in audit.INPUTS.items():
            result = audit.independent_fold(audit.expected_shape(size, seed), size)
            self.assertEqual(result['balances'], {'I0':10000, 'I1':10000+residual, 'I2':10000, 'I3':10000})
            self.assertEqual(result['liability'], 40000+residual)
            self.assertEqual(set(result['outcomes'].values()), {'MATCHED'})

    def test_same_count_substituted_event_is_rejected(self):
        data = audit.expected_shape(10000, 11)
        data[6]['record']['ref'] = 'SUBSTITUTED_E0'
        with self.assertRaisesRegex(ValueError, 'identity/order'):
            audit.independent_fold(data, 10000)

    def test_same_count_duplicate_event_is_rejected(self):
        data = audit.expected_shape(10000, 11)
        data[7]['record']['ref'] = 'E0'
        with self.assertRaisesRegex(ValueError, 'identity/order'):
            audit.independent_fold(data, 10000)

    def test_receipt_order_pin_rejects_permutation(self):
        rows = audit.expected_shape(10000, 11)
        index = audit.receipt_index(rows)
        self.assertEqual(audit.digest([x['receipt_id'] for x in index]), audit.INPUTS[10000,11][2])
        index[6], index[7] = index[7], index[6]
        self.assertNotEqual(audit.digest([x['receipt_id'] for x in index]), audit.INPUTS[10000,11][2])

    def test_bad_money_types_precision_and_nonfinite_are_rejected(self):
        for value in (1, 1.0, True, None, '1.001', '-1.00', 'NaN', '1e2', '01.00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.cents(value)

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.json'
            path.write_text('{"status":"FAIL","status":"PASS"}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                audit.load(path)

    def test_empty_duplicate_substituted_pass_rosters_rejected(self):
        good = audit.synthetic_trial_fixture()
        for rows in ([], good[:-1], [*good[:-1],good[0]], [dict(t, id='replacement') if i==0 else t for i,t in enumerate(good)],
                     [dict(t, exit_code=False) if i==0 else t for i,t in enumerate(good)],
                     [dict(t, pair=True) if i==0 else t for i,t in enumerate(good)]):
            with self.subTest(length=len(rows)), self.assertRaises(ValueError):
                audit.verify_trial_population(rows)

    def test_falsified_benchmark_summary_is_rejected(self):
        trials = audit.synthetic_trial_fixture()
        correct = audit.statistics_from_trials(trials)
        audit.verify_reported_statistics(trials, correct)
        falsified = deepcopy(correct)
        falsified['profiles'][0]['baseline_parent_wall_seconds']['p50'] = 0.00001
        with self.assertRaisesRegex(ValueError, 'reported summary'):
            audit.verify_reported_statistics(trials, falsified)

    def test_nonfinite_or_negative_raw_timing_is_rejected(self):
        for value in (float('nan'), float('inf'), -1, 0, True):
            rows = audit.synthetic_trial_fixture()
            rows[0]['parent_wall_seconds'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.statistics_from_trials(rows)

    def test_small_sample_p95_is_observed_maximum(self):
        result = audit.statistics_from_trials(audit.synthetic_trial_fixture())
        for row in result['profiles']:
            self.assertEqual(row['n_pairs'], 7)
            for method in ('baseline_parent_wall_seconds', 'candidate_parent_wall_seconds'):
                self.assertEqual(row[method]['p95_nearest_rank'], row[method]['max'])


if __name__ == '__main__':
    unittest.main()
