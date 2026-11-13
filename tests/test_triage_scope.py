"""Public-inventory scope regressions; no private plans or main evaluation run."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.triage.contracts import CONTRACT_SHA256, digest, load, save
from crypto_reconciliation_lab.triage.features import subset
from crypto_reconciliation_lab.triage.ranking import build_queue
from crypto_reconciliation_lab.triage.runner import freeze_model, evaluate_frozen, file_entry
from triage_scope_fixtures import scope_fixture
from triage_model_fixtures import labels as literal_labels


class ReachedTruthBoundary(RuntimeError):
    pass


class PublicScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='triage-scope-regression-')
        self.root = Path(self.temporary.name)
        self.features, self.splits = scope_fixture(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def write_features(self, features):
        features = deepcopy(features)
        features['inventory'] = {'units':len(features['units']),
            'episodes':len({u['episode_id'] for u in features['units']}),
            'open':sum(u['status']=='OPEN' for u in features['units']),
            'no_open_finding':sum(u['status']=='NO_OPEN_FINDING' for u in features['units'])}
        save(self.root / 'features.json', features)
        return features

    def freeze(self):
        return freeze_model(self.root / 'features.json', self.root / 'model.json',
                            self.root / 'data/splits.json', self.root / 'model-freeze.json')

    def write_queues(self, features, frozen, *, missing_split=None):
        model = load(self.root / 'model.json')
        queues = {split:build_queue(subset(features, split), model) for split in ('test','challenge')}
        if missing_split is not None:
            queues[missing_split] = build_queue({**subset(features, missing_split), 'units':[]}, model)
        for split, queue in queues.items():
            path = self.root / 'queues' / split; path.mkdir(parents=True, exist_ok=True)
            save(path / 'queue.json', queue)
        # Deliberately make attacker-controlled hashes consistent. Independent
        # public scope must still be checked rather than trusting these hashes.
        frozen = {**frozen, 'feature_file':file_entry(self.root / 'features.json'),
                  'prediction_hash':digest(queues)}
        save(self.root / 'holdout-freeze.json', frozen)

    def evaluate(self):
        return evaluate_frozen(self.root / 'data', self.root / 'features.json', self.root / 'model.json',
                               self.root / 'queues', self.root / 'holdout-freeze.json', self.root / 'result')

    def assert_no_publication_or_lock(self):
        self.assertFalse((self.root / 'result').exists())
        self.assertFalse((self.root / 'data/truth/final-evaluation-lock.json').exists())

    def test_complete_small_public_scope_reaches_only_the_truth_sentinel(self):
        frozen = self.freeze(); self.write_queues(self.features, frozen)
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels',
                   side_effect=ReachedTruthBoundary('no real truth read')) as sentinel:
            with self.assertRaises(ReachedTruthBoundary):
                self.evaluate()
            self.assertEqual(sentinel.call_count, 1)
        self.assert_no_publication_or_lock()

    def test_reduced_features_cannot_be_frozen_against_unchanged_public_roster(self):
        keep = [next(u for u in self.features['units'] if u['split']==split and u['status']=='OPEN')
                for split in ('test','challenge')]
        self.write_features({**self.features, 'units':keep})
        with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
            self.freeze()
        self.assertFalse((self.root / 'model-freeze.json').exists())
        self.assert_no_publication_or_lock()

    def test_self_consistent_reduced_features_queues_and_hashes_stop_before_truth(self):
        frozen = self.freeze()
        keep = [next(u for u in self.features['units'] if u['split']==split and u['status']=='OPEN')
                for split in ('test','challenge')]
        reduced = self.write_features({**self.features, 'units':keep})
        self.write_queues(reduced, frozen)
        rejected = False
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels',
                   side_effect=ReachedTruthBoundary('scope bug reached real truth boundary')) as sentinel:
            try:
                self.evaluate()
            except ValueError as error:
                self.assertIn('TRIAGE_SCOPE', str(error)); rejected = True
            except ReachedTruthBoundary:
                pass
            self.assertTrue(rejected, 'partial feature/queue scope was accepted despite unchanged public roster')
            self.assertEqual(sentinel.call_count, 0)
        self.assert_no_publication_or_lock()

    def test_dropped_closed_unit_is_not_hidden_by_correct_open_rankings(self):
        frozen = self.freeze()
        removed = next(u for u in self.features['units'] if u['status']=='NO_OPEN_FINDING')
        reduced = self.write_features({**self.features,'units':[u for u in self.features['units'] if u is not removed]})
        self.write_queues(reduced, frozen)
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels',
                   side_effect=ReachedTruthBoundary('closed unit was lost')) as sentinel:
            rejected = False
            try:
                self.evaluate()
            except ValueError as error:
                self.assertIn('TRIAGE_SCOPE', str(error)); rejected = True
            except ReachedTruthBoundary:
                pass
            self.assertTrue(rejected, 'NO_OPEN_FINDING inventory must be complete')
            self.assertEqual(sentinel.call_count, 0)
        self.assert_no_publication_or_lock()

    def test_same_count_wrong_asset_is_rejected_from_independent_public_assets(self):
        changed = deepcopy(self.features)
        unit = changed['units'][0]
        unit['asset'] = 'ASSET_OUTSIDE'; unit['unit_id'] = unit['episode_id']+'::ASSET_OUTSIDE'
        for ref in unit['finding_refs']:
            ref['finding']['asset'] = 'ASSET_OUTSIDE'
        self.write_features(changed)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
            self.freeze()
        self.assertFalse((self.root / 'model-freeze.json').exists())

    def test_public_hash_and_mode_links_are_checked_before_freeze(self):
        public = load(self.root / 'data/episodes.json'); public['mode'] = 'archive_smoke'
        save(self.root / 'data/episodes.json', public)
        # No manifest update: a changed public roster must fail its bundle link.
        with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
            self.freeze()
        self.assertFalse((self.root / 'model-freeze.json').exists())

    def test_empty_final_queue_rejected_before_truth_even_with_updated_prediction_hash(self):
        frozen = self.freeze(); self.write_queues(self.features, frozen, missing_split='challenge')
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels',
                   side_effect=ReachedTruthBoundary('empty final queue')) as sentinel:
            with self.assertRaises(ValueError):
                self.evaluate()
            self.assertEqual(sentinel.call_count, 0)
        self.assert_no_publication_or_lock()

    def complete_labels(self):
        labels = literal_labels(self.features['units'], [int(u['status']=='OPEN') for u in self.features['units']])
        labels.update(contract_sha256=CONTRACT_SHA256, splits_sha256=digest(self.splits))
        for label, unit in zip(labels['units'], self.features['units']):
            label['split'] = unit['split']
        return labels

    def test_extra_final_label_is_not_silently_filtered_before_metrics(self):
        frozen = self.freeze(); self.write_queues(self.features, frozen)
        labels = self.complete_labels()
        extra = deepcopy(labels['units'][0]); extra['episode_id']='not-public'; extra['unit_id']='not-public::'+extra['asset']
        labels['units'].append(extra)
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', return_value=labels) as sentinel:
            with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
                self.evaluate()
            self.assertEqual(sentinel.call_count, 1)
        self.assert_no_publication_or_lock()

    def test_general_explicit_subset_ranking_remains_supported(self):
        model = load(self.root / 'model.json')
        queue = build_queue({**self.features,'units':self.features['units'][:1]}, model)
        self.assertEqual(len(queue['units']),1)
        self.assertEqual(queue['rankings']['model'],[self.features['units'][0]['unit_id']])

    def test_full_final_labels_keep_closed_and_unknown_units(self):
        frozen = self.freeze(); self.write_queues(self.features, frozen)
        labels = self.complete_labels()
        closed = next(row for row in labels['units'] if row['label'] == 0)
        closed['label'] = None
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', return_value=labels) as sentinel:
            reports, saved = self.evaluate()
            self.assertEqual(sentinel.call_count, 1)
        self.assertEqual(len(saved['units']), 16)
        self.assertEqual(reports['test']['inventory_count'], 8)
        self.assertEqual(reports['challenge']['inventory_count'], 8)
        self.assertTrue(any(row['label'] is None for row in reports['test']['excluded']))
        self.assertFalse((self.root / 'data/truth/final-evaluation-lock.json').exists())

    def test_small_roster_cannot_claim_main_mode_with_consistent_public_hashes(self):
        data = self.root / 'data'
        for relative in ('episodes.json', 'truth/plan.json'):
            document = load(data / relative); document['mode'] = 'main'; save(data / relative, document)
        bundle = load(data / 'bundle.json'); bundle['mode'] = 'main'
        for relative in ('episodes.json', 'truth/plan.json'):
            bundle['files'][relative] = file_entry(data / relative)
        save(data / 'bundle.json', bundle)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
            self.freeze()
        self.assertFalse((self.root / 'model-freeze.json').exists())

    def test_missing_closed_final_label_is_rejected_before_split_filtering(self):
        frozen = self.freeze(); self.write_queues(self.features, frozen)
        labels = self.complete_labels()
        removed = next(row for row in labels['units'] if row['label'] == 0)
        labels['units'].remove(removed)
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', return_value=labels):
            with self.assertRaises(ValueError):
                self.evaluate()
        self.assert_no_publication_or_lock()
