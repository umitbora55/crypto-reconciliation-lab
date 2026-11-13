"""S3-F4: independently rehashed trace mutations must fail evidence checks."""
import copy
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab.lab.evidence_contract import identity, minimum_inventory, validate_evidence
from crypto_reconciliation_lab.lab.faults import build_case
from crypto_reconciliation_lab.lab.runner import evaluate
from crypto_reconciliation_lab.lab.scoring import score
from crypto_reconciliation_lab.lab.world import config, generate


class TraceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.world = generate(11, 12, 2)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, name='CLEAN'):
        if name not in self.cache:
            case = build_case(self.world, name)
            results = evaluate(config(self.world), case['rows'], case['phases'], self.root / (name + '.sqlite3'))[0]
            for result, phase in zip(results, case['phases']):
                check = score(result, phase)
                self.assertTrue(check['passed'], check['errors'])
            self.cache[name] = case, results
        case, results = self.cache[name]
        return copy.deepcopy(results[-1]), copy.deepcopy(case['phases'][-1])

    def reject(self, result, phase):
        result['run_id'] = identity({k: v for k, v in result.items() if k != 'run_id'})
        check = score(result, phase)
        self.assertFalse(check['passed'], check)
        self.assertFalse(check['evidence_verified'], check)
        self.assertGreater(check['counters']['missing_evidence'], 0, check)
        self.assertFalse(any('run content-ID mismatch' in str(e) for e in check['errors']), check)
        return check

    def test_rehashed_normal_investor_delta_reproduction(self):
        result, phase = self.fixture()
        row = result['ledgers']['ASSET_A']['trace'][0]
        self.assertEqual(row['investor_deltas']['I001'], '0.00000015')
        row['investor_deltas']['I001'] = '999'
        self.reject(result, phase)

    def test_rehashed_normal_custody_delta_reproduction(self):
        result, phase = self.fixture()
        result['ledgers']['ASSET_A']['trace'][0]['custody_delta'] = '999'
        self.reject(result, phase)

    def test_rehashed_intermediate_balance_reproduction(self):
        result, phase = self.fixture()
        row = result['ledgers']['ASSET_A']['trace'][0]
        self.assertEqual(row['balances_after']['I001'], '0.00002215')
        row['balances_after']['I001'] = '999'
        self.reject(result, phase)

    def test_rehashed_applied_group_null_reproduction(self):
        result, phase = self.fixture('REPLACE_DEPOSIT')
        row = next(t for t in result['ledgers']['ASSET_A']['trace'] if t['correction_group_id'] is not None)
        row['correction_group_id'] = None
        self.reject(result, phase)

    def test_normal_directions_locations_and_decimal_precision(self):
        original, phase = self.fixture()
        seen = set()
        for asset, ledger in original['ledgers'].items():
            for index, trace in enumerate(ledger['trace']):
                event = original['evidence'][trace['event_id']]['record']
                kind = event['type']
                if (asset, kind) in seen:
                    continue
                seen.add((asset, kind))
                for field, value in [('investor_deltas', {'I001': '999'}), ('custody_location', 'platform' if trace['custody_location'] != 'platform' else 'external'), ('custody_delta', '0.001' if asset == 'ASSET_B' else '0.000000001')]:
                    with self.subTest(kind=kind, field=field):
                        result = copy.deepcopy(original)
                        result['ledgers'][asset]['trace'][index][field] = value
                        self.reject(result, phase)
                if kind == 'transfer':
                    self.assertIsNone(trace['custody_location'])
                    self.assertEqual(trace['custody_delta'], '0')
                    self.assertTrue(any(v.startswith('-') for v in trace['investor_deltas'].values()))
        self.assertEqual(seen, {(asset, kind) for asset in ('ASSET_A', 'ASSET_B') for kind in ('deposit', 'withdrawal', 'transfer')})

    def test_void_and_replace_net_effect_at_original_position(self):
        for mode in ('VOID', 'REPLACE'):
            for kind in ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER'):
                with self.subTest(mode=mode, kind=kind):
                    result, phase = self.fixture(mode + '_' + kind)
                    ledger = result['ledgers']['ASSET_A']
                    group = ledger['correction_groups'][0]
                    matches = [t for t in ledger['trace'] if t['event_id'] == group['target_record_id']]
                    self.assertEqual(len(matches), 1)
                    if mode == 'VOID':
                        self.assertEqual(set(matches[0]['investor_deltas'].values()), {'0'})
                        self.assertEqual(matches[0]['custody_delta'], '0')
                    matches[0]['investor_deltas'] = {'I001': '999'}
                    self.reject(result, phase)

    def test_group_cannot_attach_to_wrong_target_or_unamended_event(self):
        original, phase = self.fixture('REPLACE_DEPOSIT')
        group_id = original['ledgers']['ASSET_A']['correction_groups'][0]['id']
        for wrong in (group_id, 'fabricated-group'):
            with self.subTest(group=wrong):
                result = copy.deepcopy(original)
                row = next(t for t in result['ledgers']['ASSET_A']['trace'] if t['correction_group_id'] is None)
                row['correction_group_id'] = wrong
                self.reject(result, phase)

    def test_intermediate_error_cannot_be_cancelled_later_or_change_idle_investor(self):
        for mutation in ('compensated_next_row', 'idle_investor', 'final_ledger'):
            with self.subTest(mutation=mutation):
                result, phase = self.fixture()
                ledger = result['ledgers']['ASSET_A']
                if mutation == 'compensated_next_row':
                    # Following rows and final ledger remain exactly correct.
                    ledger['trace'][0]['balances_after']['I001'] = '0.00002216'
                elif mutation == 'idle_investor':
                    self.assertNotIn('I002', ledger['trace'][0]['investor_deltas'])
                    ledger['trace'][0]['balances_after']['I002'] = '999'
                else:
                    ledger['investor_balances']['I001'] = '999'
                self.reject(result, phase)

    def test_malformed_trace_values_fail_with_location(self):
        mutations = {
            'null_deltas': lambda t: t.update(investor_deltas=None),
            'boolean_delta': lambda t: t.update(custody_delta=True),
            'null_known_balance': lambda t: t['balances_after'].update(I001=None),
            'numeric_balance': lambda t: t['balances_after'].update(I001=1),
            'extra_precision': lambda t: t['balances_after'].update(I001='0.000022150'),
            'absent_balance': lambda t: t['balances_after'].pop('I002'),
            'list_row': None,
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                result, phase = self.fixture()
                if mutate is None:
                    result['ledgers']['ASSET_A']['trace'][0] = []
                else:
                    mutate(result['ledgers']['ASSET_A']['trace'][0])
                self.reject(result, phase)

    def test_missing_opening_stays_unknown_in_provisional_trace(self):
        case = build_case(self.world, 'CLEAN')
        rows = [row for row in case['rows'] if not (row['record']['kind'] == 'opening' and row['record']['asset'] == 'ASSET_A' and row['record']['scope'] == 'I001')]
        phase = copy.deepcopy(case['phases'][-1])
        phase['evidence_minimum'] = minimum_inventory(rows, config(self.world), 'CLEAN', phase)
        result = evaluate(config(self.world), rows, [phase], self.root / 'missing-opening.sqlite3')[0][0]
        self.assertEqual(result['ledgers']['ASSET_A']['data_state'], 'INCOMPLETE')
        self.assertIsNone(result['ledgers']['ASSET_A']['investor_balances']['I001'])
        self.assertTrue(all(t['balances_after']['I001'] is None for t in result['ledgers']['ASSET_A']['trace']))
        validate_evidence(result, phase)
        result['ledgers']['ASSET_A']['trace'][0]['balances_after']['I001'] = '0'
        result['run_id'] = identity({k: v for k, v in result.items() if k != 'run_id'})
        with self.assertRaisesRegex(ValueError, 'trace.*balance'):
            validate_evidence(result, phase)


if __name__ == '__main__':
    unittest.main()
