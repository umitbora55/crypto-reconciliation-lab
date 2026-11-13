"""Publication, budget and freeze boundaries independent of main holdout labels."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.triage.budget import ExperimentBudget
from crypto_reconciliation_lab.triage.contracts import load, save, digest
from crypto_reconciliation_lab.triage.runner import freeze_model, evaluate_frozen, verify_twins, _retain
from crypto_reconciliation_lab.triage.ranking import build_queue
from triage_model_fixtures import row, document, literal_model
from triage_scope_fixtures import scope_fixture


class RunnerBoundaryTests(unittest.TestCase):
    def test_transient_adapter_copy_reservation_enforces_combined_limit_and_releases(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'data').write_bytes(b'12345')
            budget = ExperimentBudget([root], max_bytes=10)
            with self.assertRaisesRegex(ValueError, 'BUDGET_BYTES'):
                with budget.reserve_transient(6):
                    self.fail('oversized copy must fail before adapter executes')
            self.assertEqual(budget.reserved_bytes, 0)
            with budget.reserve_transient(5):
                self.assertEqual(budget.check()['current_bytes'], 10)
            self.assertEqual(budget.check()['current_bytes'], 5)
            self.assertEqual(budget.peak_reserved_bytes, 6)

    def test_deadline_includes_accounting_scan_itself(self):
        with tempfile.TemporaryDirectory() as name:
            with patch('crypto_reconciliation_lab.triage.budget.time.monotonic', side_effect=[0, 1, 11]):
                budget = ExperimentBudget([name], seconds=10)
                with self.assertRaisesRegex(ValueError, 'during file accounting'):
                    budget.check(force=True)

    def test_nested_roots_do_not_double_count_but_publication_destination_does(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            runtime = root / 'runtime'; runtime.mkdir()
            child = runtime / 'child'; child.mkdir()
            (child / 'data').write_bytes(b'12345')
            staging = root / 'staging'; staging.mkdir()
            (staging / 'data').write_bytes(b'123')
            budget = ExperimentBudget([runtime, child, staging], max_bytes=20)
            self.assertEqual(budget.check(force=True)['current_bytes'], 8)
            published = root / 'published'; staging.rename(published)
            budget.add_root(published)
            self.assertEqual(budget.check(force=True)['current_bytes'], 8)

    def test_changed_catalog_or_model_aborts_before_any_holdout_truth(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); data = root / 'data'
            scope_fixture(root)
            frozen = freeze_model(root / 'features.json', root / 'model.json', data / 'splits.json', root / 'freeze.json')
            save(data / 'truth/plan.json', {'fixture': 'changed catalog'})
            with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', side_effect=AssertionError('holdout accessed')):
                with self.assertRaisesRegex(ValueError, 'TRIAGE_FREEZE'):
                    evaluate_frozen(data, root / 'features.json', root / 'model.json', root / 'queues', root / 'freeze.json', root / 'result')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(frozen['status'], 'FROZEN')

    def test_twin_audit_uses_real_frozen_scores_and_detects_changed_observation(self):
        left, right = row(0), row(1)
        for unit in (left, right):
            unit['finding_refs'][0]['finding'].update(expected='0.30', reported=None)
        features, splits = document([left, right]); model = literal_model(digest(splits))
        result = verify_twins(features, model, splits)
        self.assertEqual(result['asset_pairs'], 1)
        self.assertEqual(result['pairs'][0]['score'], 0.5)
        features['units'][1]['features']['a_open_count'] = 1
        with self.assertRaisesRegex(ValueError, 'TWIN_LEAKAGE'):
            verify_twins(features, model, splits)

    def test_retention_hashes_owned_bytes_and_omissions_have_exact_producer(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); runtime = root / 'runtime'; staging = root / 'staging'
            runtime.mkdir(); staging.mkdir()
            (runtime / 'source.sqlite3').write_bytes(b'owned fixture database bytes')
            (runtime / 'payload.json').write_bytes(b'{"amount":"0.30","unknown":null}\n')
            budget = ExperimentBudget([runtime, staging])
            producer = {'argv':['python', '-m', 'crypto_reconciliation_lab', 'triage-experiment'],
                        'cwd':str(root), 'mode':'smoke', 'contract_sha256':'a'*64}
            manifest, omissions = _retain(runtime, staging, budget, producer)
            self.assertEqual(set(manifest), {'payload.json'})
            self.assertEqual(set(omissions), {'source.sqlite3'})
            self.assertEqual((staging / 'payload.json').read_bytes(), (runtime / 'payload.json').read_bytes())
            self.assertFalse((staging / 'source.sqlite3').exists())
            self.assertEqual(load(staging / 'omitted-files.json')['producer'], producer)
