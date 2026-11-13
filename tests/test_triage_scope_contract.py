"""Supplemental public-type and identity gates; no real horizon evaluation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.triage.contracts import CONTRACT_SHA256, digest, load, save
from crypto_reconciliation_lab.triage.features import subset
from crypto_reconciliation_lab.triage.ranking import build_queue
from crypto_reconciliation_lab.triage.runner import freeze_model, evaluate_frozen, file_entry
from triage_model_fixtures import labels as literal_labels
from triage_scope_fixtures import scope_fixture


class PublicScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='triage-scope-contract-')
        self.root = Path(self.temporary.name)
        self.features, self.splits = scope_fixture(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def freeze(self):
        return freeze_model(self.root/'features.json', self.root/'model.json',
                            self.root/'data/splits.json', self.root/'freeze.json')

    def bind_public(self, public):
        save(self.root/'data/episodes.json', public)
        bundle = load(self.root/'data/bundle.json')
        bundle['files']['episodes.json'] = file_entry(self.root/'data/episodes.json')
        save(self.root/'data/bundle.json', bundle)

    def final_inputs(self):
        frozen = self.freeze()
        model = load(self.root/'model.json')
        queues = {split:build_queue(subset(self.features, split), model) for split in ('test','challenge')}
        for split, queue in queues.items():
            folder = self.root/'queues'/split; folder.mkdir(parents=True)
            save(folder/'queue.json', queue)
        save(self.root/'holdout-freeze.json', {**frozen, 'prediction_hash':digest(queues)})
        labels = literal_labels(self.features['units'], [0]*16)
        labels.update(contract_sha256=CONTRACT_SHA256, splits_sha256=digest(self.splits))
        for label, unit in zip(labels['units'], self.features['units']):
            label['split'] = unit['split']
        return labels

    def evaluate(self):
        return evaluate_frozen(self.root/'data', self.root/'features.json', self.root/'model.json',
                               self.root/'queues', self.root/'holdout-freeze.json', self.root/'result')

    def assert_no_final_output(self):
        self.assertFalse((self.root/'result').exists())
        self.assertFalse((self.root/'data/truth/final-evaluation-lock.json').exists())

    def test_nonobject_public_documents_fail_controlled_validation(self):
        for relative in ('episodes.json','splits.json','bundle.json','truth/plan.json'):
            path = self.root/'data'/relative
            original = path.read_bytes()
            try:
                for value in (None, [], 'invalid-public-object'):
                    with self.subTest(path=relative, value=value):
                        save(path, value)
                        with self.assertRaises(ValueError):
                            self.freeze()
                        self.assertFalse((self.root/'freeze.json').exists())
            finally:
                path.write_bytes(original)

    def test_public_wrong_world_duplicate_episode_and_wrong_cut_are_rejected(self):
        original = load(self.root/'data/episodes.json')
        for kind in ('world','duplicate','cut'):
            public = deepcopy(original)
            if kind == 'world':
                public['episodes'][0]['world_id'] = 'not-declared'
            elif kind == 'duplicate':
                public['episodes'][1] = deepcopy(public['episodes'][0])
            else:
                public['episodes'][0]['as_of'] = '2026-11-11T01:00:00Z'
            self.bind_public(public)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
                self.freeze()
            self.assertFalse((self.root/'freeze.json').exists())

    def test_feature_wrong_world_wrong_time_and_duplicate_are_rejected(self):
        for kind in ('world','time','duplicate'):
            features = deepcopy(self.features)
            if kind == 'world':
                features['units'][0]['world_id'] = 'not-declared'
            elif kind == 'time':
                features['units'][0]['balance_at'] = '2026-11-10T02:00:00Z'
            else:
                features['units'][1] = deepcopy(features['units'][0])
            save(self.root/'features.json', features)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.freeze()
            self.assertFalse((self.root/'freeze.json').exists())

    def test_nonobject_feature_document_is_controlled_at_freeze_and_final(self):
        self.final_inputs()
        (self.root/'freeze.json').unlink()
        save(self.root/'features.json', [])
        with self.assertRaises(ValueError):
            self.freeze()
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', side_effect=AssertionError('truth accessed')) as truth:
            with self.assertRaises(ValueError):
                self.evaluate()
            self.assertEqual(truth.call_count, 0)
        self.assert_no_final_output()

    def test_duplicate_final_label_rejected_before_metric_join(self):
        labels = self.final_inputs()
        labels['units'][1] = deepcopy(labels['units'][0])
        with patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', return_value=labels):
            with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
                self.evaluate()
        self.assert_no_final_output()

    def test_final_label_wrong_world_split_time_and_horizon_are_rejected(self):
        original = self.final_inputs()
        for key, value in (('world_id','not-declared'), ('split','train'),
                           ('as_of','2026-11-11T01:00:00Z'), ('horizon','2026-11-13T00:00:00Z')):
            labels = deepcopy(original); labels['units'][0][key] = value
            with self.subTest(key=key), patch('crypto_reconciliation_lab.triage.truth.evaluate_labels', return_value=labels):
                with self.assertRaisesRegex(ValueError, 'TRIAGE_SCOPE'):
                    self.evaluate()
            self.assert_no_final_output()

    def test_public_equivalent_offsets_preserve_common_scope(self):
        public = load(self.root/'data/episodes.json')
        public.update(balance_at='2026-11-10T04:00:00+03:00', as_of='2026-11-11T03:00:00+03:00',
                      horizon='2026-11-12T03:00:00+03:00')
        for episode in public['episodes']:
            episode.update(balance_at=public['balance_at'], as_of=public['as_of'])
        self.bind_public(public)
        self.assertEqual(self.freeze()['status'], 'FROZEN')
        self.assert_no_final_output()
