"""Real saved-payload information boundaries, evidence references and safe rank IO."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext, Inexact, Rounded
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.demo import fixtures, BALANCE_AT as OLD_BALANCE
from crypto_reconciliation_lab.review.adapter import read_selected_sources
from crypto_reconciliation_lab.triage.contracts import (AS_OF, BALANCE_AT, FEATURE_NAMES,
    digest, load, save, validate_features)
from crypto_reconciliation_lab.triage.features import build_features, extract_episode, derived_text
from crypto_reconciliation_lab.triage.ranking import build_queue, rank_files
from crypto_reconciliation_lab.triage.model import score_rows
from review_fixtures import create_selection
from test_review_output_paths import source_state, tree_state
from triage_model_fixtures import literal_model, reidentify


def public_fixture(root):
    """A tiny independent adaptation of the literal Stage 1 arithmetic example."""
    root = Path(root); root.mkdir()
    database = root / 'source.sqlite3'
    config, initial, _ = fixtures()
    future = []
    store = Store(database, config)
    try:
        for envelope in initial:
            record = deepcopy(envelope['record'])
            for key in ('balance_at', 'coverage_from', 'coverage_to'):
                if record.get(key) == '2026-11-10T23:59:59.000000Z':
                    record[key] = BALANCE_AT
            if record['kind'] == 'event':
                minute = {'A1':10, 'A2':20, 'A3':30, 'B1':20}[record['ref']]
                record['occurred_at'] = f'2026-11-10T00:{minute:02d}:00Z'
            if ((record['kind'] == 'event' and record['ref'] == 'A3') or
                (record['kind'] == 'report' and record['asset'] == 'ASSET_A' and record['stream'] == 'external_custody')):
                future.append(record)
            else:
                outcome = store.ingest(record, '2026-11-10T12:00:00Z')
                if outcome['status'] not in ('ACCEPTED', 'DUPLICATE'):
                    raise AssertionError(outcome)
        past = reconcile(store, BALANCE_AT, '2026-11-10T18:00:00Z')
        current = reconcile(store, BALANCE_AT, AS_OF)
    finally:
        store.close()
    episode = {'episode_id':'e0', 'world_id':'w0', 'split':'train', 'as_of':AS_OF,
               'current_run_id':current['run_id'], 'history_run_ids':[past['run_id']], 'selection_file':'selection.json'}
    create_selection(root, [('e0', database, [past['run_id'], current['run_id']])])
    save(root / 'episodes.json', {'episodes':[episode]})
    save(root / 'splits.json', {'format':'triage-split-v1', 'groups':[{'world_id':'w0','split':'train','episode_ids':['e0']}]})
    return database, episode, future


def pointer(value, path):
    for token in path.lstrip('/').split('/'):
        token = token.replace('~1','/').replace('~0','~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class FeatureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='triage-feature-test-')
        self.root = Path(self.temporary.name).resolve()
        self.public = self.root / 'public'
        self.database, self.episode, self.future = public_fixture(self.public)

    def tearDown(self):
        self.temporary.cleanup()

    def feature_document(self, name='features'):
        return build_features(self.public, self.root / name)

    def test_actual_future_receipts_reports_and_private_labels_do_not_change_t_features_or_scores(self):
        before = self.feature_document('before')
        model = literal_model(before['splits_sha256'])
        before_scores = score_rows(model, before)
        original_runs = source_state(self.database)['runs']
        store = Store(self.database)
        try:
            for record in self.future:
                self.assertEqual(store.ingest(record, '2026-11-11T02:00:00Z')['status'], 'ACCEPTED')
        finally:
            store.close()
        save(self.public / 'labels-and-truth-not-an-input.json', {'future_labels':[1,0], 'secret':'never passed to extractor'})
        after = self.feature_document('after')
        self.assertEqual(before['units'], after['units'])
        self.assertEqual(before_scores, score_rows(model, after))
        self.assertNotEqual(before['source_proofs'][0]['before']['files']['database']['sha256'],
                            after['source_proofs'][0]['before']['files']['database']['sha256'])
        self.assertEqual(original_runs, source_state(self.database)['runs'])
        self.assertTrue(all(proof['unchanged'] for proof in after['source_proofs']))

    def test_identity_alias_and_scenario_filename_changes_only_provenance_and_ties(self):
        before = self.feature_document('original')
        model = literal_model(before['splits_sha256'])
        baseline_scores = [item['score'] for item in score_rows(model, before)]
        selection = load(self.public / 'selection.json')
        selection['sources'][0]['alias'] = 'meaningful-scenario-name-must-not-be-a-feature'
        save(self.public / 'scenario-identity.json', selection)
        old_episode = deepcopy(self.episode)
        self.episode.update(episode_id='renamed-neutral', world_id='renamed-world', selection_file='scenario-identity.json')
        save(self.public / 'episodes.json', {'episodes':[self.episode]})
        save(self.public / 'splits.json', {'format':'triage-split-v1', 'groups':[{'world_id':'renamed-world','split':'train','episode_ids':['renamed-neutral']}]})
        after = self.feature_document('renamed')
        self.assertEqual([u['features'] for u in before['units']], [u['features'] for u in after['units']])
        # Split/model provenance changes naturally; coefficients/preprocessing do not.
        renamed_model = deepcopy(model); renamed_model['splits_sha256'] = after['splits_sha256']; reidentify(renamed_model)
        self.assertEqual(baseline_scores, [item['score'] for item in score_rows(renamed_model, after)])
        self.assertNotEqual(before['units'][0]['finding_refs'][0]['source_alias'], after['units'][0]['finding_refs'][0]['source_alias'])
        self.assertNotEqual(before['units'][0]['unit_id'], after['units'][0]['unit_id'])

    def test_future_incompatible_and_different_episode_history_are_rejected(self):
        saved = list(read_selected_sources(self.public / 'selection.json').runs)
        for kind in ('future', 'configuration', 'balance', 'alias'):
            modified = deepcopy(saved[0].payload)
            if kind == 'future': modified['knowledge_at'] = '2026-11-12T00:00:00Z'
            if kind == 'configuration': modified['configuration']['platform'] = 'DIFFERENT'
            if kind == 'balance': modified['balance_at'] = '2026-11-10T02:00:00Z'
            replacement = replace(saved[0], payload=modified, source_alias='other-episode' if kind == 'alias' else saved[0].source_alias)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                extract_episode([replacement,saved[1]], self.episode)

    def test_actual_provenance_points_to_all_contributing_findings_and_saved_evidence(self):
        document = self.feature_document()
        sources = {run.run_id:run for run in read_selected_sources(self.public / 'selection.json').runs}
        for unit in document['units']:
            for proof in unit['feature_provenance'].values():
                self.assertTrue(proof['sources'])
                for ref in proof['sources']:
                    payload = sources[ref['run_id']].payload
                    finding = pointer(payload, ref['pointer'])
                    self.assertEqual(finding['asset'], unit['asset'])
                    evidence_ids = pointer(payload, ref['evidence_pointer'])
                    self.assertTrue(set(evidence_ids) <= payload['evidence'].keys())
            for ref in unit['finding_refs']:
                self.assertEqual(ref['finding'], pointer(sources[ref['run_id']].payload, ref['pointer']))
                raw = (self.root / 'features' / ref['payload_file']).read_bytes()
                self.assertEqual(raw, sources[ref['run_id']].payload_text.encode())
                self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['payload_sha256'])
        a = next(u for u in document['units'] if u['asset']=='ASSET_A')
        self.assertEqual(len(a['feature_provenance']['a_open_count']['sources']),2)
        self.assertEqual(len(a['feature_provenance']['b_open_count']['sources']),1)
        self.assertEqual(len(a['feature_provenance']['observed_age_hours']['sources']),6)

    def test_literal_values_keep_null_amounts_and_independent_a_b_asset_states(self):
        document = self.feature_document()
        a,b = document['units']
        self.assertEqual((a['asset'],a['status'],b['asset'],b['status']), ('ASSET_A','OPEN','ASSET_B','NO_OPEN_FINDING'))
        self.assertEqual((a['features']['a_open_count'],a['features']['b_open_count']), (2,1))
        self.assertEqual(a['features']['a_relative_difference_max'], '0.200000000000000000')
        self.assertIsNone(a['features']['b_relative_difference'])
        self.assertEqual(a['features']['b_ratio_undefined_count'],1)
        self.assertEqual(a['features']['observed_age_hours'],'6.000000000000000000')
        self.assertEqual(a['features']['missing_report_count'],1)
        self.assertEqual(b['features']['a_relative_difference_max'],'0.000000000000000000')
        self.assertTrue(all(f['finding']['data_state']=='COMPLETE' for f in b['finding_refs']))
        custody = next(ref['finding'] for ref in a['finding_refs'] if ref['finding']['comparison']=='B')
        self.assertIsNone(custody['reported'])
        self.assertIsNone(custody['difference'])
        self.assertIsInstance(custody['expected'],str)
        queue = build_queue(document,literal_model(document['splits_sha256']))
        closed = next(unit for unit in queue['units'] if unit['status']=='NO_OPEN_FINDING')
        self.assertEqual(closed['ranks'],{'fifo':None,'rules':None,'model':None})
        self.assertIsNone(closed['model_score'])
        self.assertEqual(queue['inventory']['total'],2)

    def test_derived_ratio_rounding_is_explicit_and_independent_of_financial_traps(self):
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True; context.traps[Rounded] = True
            self.assertEqual(derived_text(Decimal(1),Decimal(3)), '0.333333333333333333')

    def test_rank_source_sidecars_existing_targets_and_input_files_are_protected(self):
        document = self.feature_document()
        feature_path = self.root / 'features/features.json'
        model_path = self.root / 'model.json'; save(model_path,literal_model(document['splits_sha256']))
        before_source = source_state(self.database)
        for suffix in ('-wal','-shm','-journal'):
            for nested in (False,True):
                target = Path(str(self.database)+suffix)
                if nested: target /= 'rank'
                before_tree = tree_state(self.root)
                with self.subTest(suffix=suffix,nested=nested), self.assertRaisesRegex(ValueError,'OUTPUT_SOURCE_CONFLICT'):
                    rank_files(feature_path,model_path,target)
                self.assertEqual(tree_state(self.root),before_tree)
                self.assertEqual(source_state(self.database),before_source)
        for kind in ('file','directory','symlink'):
            target = self.root / ('existing-'+kind)
            if kind=='file': target.write_text('keep')
            elif kind=='directory': target.mkdir()
            else: target.symlink_to(self.root/'absent')
            before_tree=tree_state(self.root)
            with self.subTest(kind=kind), self.assertRaisesRegex(FileExistsError,'OUTPUT_EXISTS'):
                rank_files(self.root/'invalid-input',model_path,target)
            self.assertEqual(tree_state(self.root),before_tree)
        with self.assertRaisesRegex(ValueError,'OUTPUT_SOURCE_CONFLICT'):
            rank_files(feature_path,model_path,feature_path/'rank')
        self.assertEqual(source_state(self.database),before_source)

    def test_rank_uses_no_financial_entrypoints_and_same_inputs_are_byte_deterministic(self):
        document = self.feature_document()
        feature_path = self.root / 'features/features.json'
        model_path = self.root / 'model.json'; save(model_path,literal_model(document['splits_sha256']))
        before=source_state(self.database)
        with patch('crypto_reconciliation_lab.store.Store',side_effect=AssertionError('live Store forbidden')), \
             patch('crypto_reconciliation_lab.engine.reconcile',side_effect=AssertionError('live engine forbidden')), \
             patch('crypto_reconciliation_lab.migrations.migrate_database',side_effect=AssertionError('migration forbidden')):
            rank_files(feature_path,model_path,self.root/'rank-a')
            rank_files(feature_path,model_path,self.root/'rank-b')
        self.assertEqual(source_state(self.database),before)
        for name in ('queue.json','queue.md'):
            self.assertEqual((self.root/'rank-a'/name).read_bytes(),(self.root/'rank-b'/name).read_bytes())


if __name__=='__main__':
    unittest.main()
