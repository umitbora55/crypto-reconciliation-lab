"""S5-F2: reject internally contradictory saved-feature evidence before rank IO."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from crypto_reconciliation_lab.triage.contracts import AS_OF, digest, load, save, validate_features
from crypto_reconciliation_lab.triage.features import build_features
from crypto_reconciliation_lab.triage.model import score_rows
from crypto_reconciliation_lab.triage.ranking import rank_files
from test_triage_features import public_fixture
from triage_model_fixtures import literal_model


class ProvenanceConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='stage51-provenance-')
        self.root = Path(self.temporary.name)
        self.database, self.episode, _ = public_fixture(self.root / 'public')
        self.features = build_features(self.root / 'public', self.root / 'features')
        self.model = literal_model(self.features['splits_sha256'])
        save(self.root / 'model.json', self.model)
        self.before_db = hashlib.sha256(self.database.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.before_db)
        self.assertTrue(all(not os.path.lexists(str(self.database) + s) for s in ('-wal', '-shm', '-journal')))
        self.temporary.cleanup()

    def proof(self, document):
        return document['units'][0]['feature_provenance']['a_open_count']

    def test_inner_future_source_with_unchanged_t_summary_is_rejected(self):
        invalid = deepcopy(self.features)
        self.proof(invalid)['sources'][0]['knowledge_at'] = '2026-11-12T00:00:00Z'
        self.assertEqual(self.proof(invalid)['latest_knowledge_at'], AS_OF)
        with self.assertRaises(ValueError):
            validate_features(invalid)

    def test_summary_must_equal_actual_source_maximum_even_when_both_are_before_t(self):
        invalid = deepcopy(self.features)
        self.proof(invalid)['latest_knowledge_at'] = '2026-11-10T18:00:00Z'
        with self.assertRaises(ValueError):
            validate_features(invalid)

    def test_every_source_is_typed_and_has_required_time_identity_and_pointers(self):
        changes = [(field, None) for field in ('run_id', 'pointer', 'evidence_pointer', 'knowledge_at')]
        changes += [('knowledge_at', False), ('knowledge_at', 42), ('knowledge_at', {}),
                    ('knowledge_at', '2026-11-11T00:00:00'), ('pointer', 0)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                invalid = deepcopy(self.features)
                self.proof(invalid)['sources'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_features(invalid)
        for field in ('run_id', 'pointer', 'evidence_pointer', 'knowledge_at'):
            with self.subTest(missing=field):
                invalid = deepcopy(self.features)
                self.proof(invalid)['sources'][0].pop(field)
                with self.assertRaises(ValueError):
                    validate_features(invalid)
        invalid = deepcopy(self.features)
        self.proof(invalid)['sources'][0] = 'not a source object'
        with self.assertRaises(ValueError):
            validate_features(invalid)

    def test_finding_and_evidence_pointers_must_name_the_same_finding(self):
        invalid = deepcopy(self.features)
        self.proof(invalid)['sources'][0]['evidence_pointer'] = '/findings/99999/evidence_ids'
        with self.assertRaises(ValueError):
            validate_features(invalid)

    def test_current_refs_must_agree_with_known_sources_scope_and_snapshot_metadata(self):
        changes = [('pointer', '/findings/99999'), ('payload_sha256', '0' * 64),
                   ('payload_file', 'snapshots/elsewhere.json'), ('run_id', 'another-run'),
                   ('source_alias', 'another-alias')]
        for key, value in changes:
            with self.subTest(field=key):
                invalid = deepcopy(self.features)
                invalid['units'][0]['finding_refs'][0][key] = value
                with self.assertRaises(ValueError):
                    validate_features(invalid)
        for key, value in [('asset', 'NOT_THIS_ASSET'), ('knowledge_at', '2026-11-12T00:00:00Z'),
                           ('balance_at', '2026-11-10T02:00:00Z')]:
            with self.subTest(finding_field=key):
                invalid = deepcopy(self.features)
                invalid['units'][0]['finding_refs'][0]['finding'][key] = value
                with self.assertRaises(ValueError):
                    validate_features(invalid)

    def test_optional_snapshot_metadata_is_checked_when_present(self):
        for field, value in [('episode_id', 'wrong-episode'), ('sha256', 'a' * 64),
                             ('knowledge_at', '2026-11-12T00:00:00Z')]:
            with self.subTest(field=field):
                invalid = deepcopy(self.features)
                current_run = invalid['units'][0]['finding_refs'][0]['run_id']
                snapshot = next(s for s in invalid['snapshots'] if s['run_id'] == current_run)
                snapshot[field] = value
                with self.assertRaises(ValueError):
                    validate_features(invalid)
        invalid = deepcopy(self.features); invalid['snapshots'] = None
        with self.assertRaises(ValueError):
            validate_features(invalid)

    def test_invalid_rank_has_no_published_output_and_valid_rank_still_succeeds(self):
        invalid = deepcopy(self.features)
        self.proof(invalid)['sources'][0]['knowledge_at'] = '2026-11-12T00:00:00Z'
        save(self.root / 'invalid.json', invalid)
        with self.assertRaises(ValueError):
            rank_files(self.root / 'invalid.json', self.root / 'model.json', self.root / 'invalid-rank')
        self.assertFalse((self.root / 'invalid-rank').exists())
        rank_files(self.root / 'features/features.json', self.root / 'model.json', self.root / 'valid-rank')
        self.assertTrue((self.root / 'valid-rank/queue.json').exists())

    def cli_rank(self, source, target):
        environment = dict(os.environ); environment.pop('PYTHONPATH', None)
        # Match the already tested package origin without importing an unrelated checkout.
        project = Path(__import__('crypto_reconciliation_lab').__file__).resolve().parents[1]
        return subprocess.run([sys.executable, '-B', '-s', '-m', 'crypto_reconciliation_lab',
                               'triage-rank', '--features', str(source), '--model', str(self.root / 'model.json'),
                               '--output', str(target)], cwd=project, env=environment, text=True, capture_output=True)

    def test_real_cli_rejects_future_source_without_complete_or_scored_publication(self):
        invalid = deepcopy(self.features)
        self.proof(invalid)['sources'][0]['knowledge_at'] = '2026-11-12T00:00:00Z'
        save(self.root / 'invalid-cli.json', invalid)
        result = self.cli_rank(self.root / 'invalid-cli.json', self.root / 'invalid-cli-rank')
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertNotIn('COMPLETE', result.stdout)
        self.assertFalse((self.root / 'invalid-cli-rank').exists())

    def test_real_cli_accepts_valid_history_and_t_with_exact_financial_refs(self):
        result = self.cli_rank(self.root / 'features/features.json', self.root / 'valid-cli-rank')
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        queue = load(self.root / 'valid-cli-rank/queue.json')
        self.assertEqual(queue['units'][0]['score_status'], 'SCORED')
        self.assertEqual([u['finding_refs'] for u in queue['units']],
                         [u['finding_refs'] for u in self.features['units']])

    def test_real_history_and_equivalent_timezone_text_are_valid(self):
        actual = validate_features(self.features)
        current = {r['run_id'] for r in actual['units'][0]['finding_refs']}
        history = {s['run_id'] for p in actual['units'][0]['feature_provenance'].values() for s in p['sources']}
        self.assertTrue(history - current)
        equivalent = deepcopy(self.features)
        self.proof(equivalent)['sources'][0]['knowledge_at'] = '2026-11-11T03:00:00+03:00'
        self.proof(equivalent)['latest_knowledge_at'] = '2026-11-10T19:00:00-05:00'
        self.assertEqual(score_rows(self.model, equivalent), score_rows(self.model, self.features))
        without_snapshots = deepcopy(self.features); without_snapshots.pop('snapshots')
        self.assertEqual(score_rows(self.model, without_snapshots), score_rows(self.model, self.features))

    def test_same_run_hash_is_legal_in_two_different_episode_scopes(self):
        twins = deepcopy(self.features)
        for original in self.features['units']:
            twin = deepcopy(original)
            twin.update(episode_id='e1', unit_id='e1::' + twin['asset'])
            for ref in twin['finding_refs']:
                ref['source_alias'] = 'e1'
                ref['payload_file'] = 'snapshots/twin/' + ref['run_id'] + '.json'
            twins['units'].append(twin)
        for original in self.features['snapshots']:
            twin = deepcopy(original)
            twin.update(episode_id='e1', source_alias='e1', payload_file='snapshots/twin/' + twin['run_id'] + '.json')
            twins['snapshots'].append(twin)
        splits = {'format':'triage-split-v1','groups':[{'world_id':'w0','split':'train','episode_ids':['e0','e1']}]}
        twins['splits_sha256'] = digest(splits)
        twins['inventory'] = {'units':4,'episodes':2,'open':2,'no_open_finding':2}
        validate_features(twins, splits)
        scores = score_rows(literal_model(digest(splits)), twins)
        self.assertEqual([s['score'] for s in scores[:2]], [s['score'] for s in scores[2:]])
