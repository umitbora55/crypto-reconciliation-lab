"""S11-F1: controlled, repinned capture causality; not a trust-pin bypass.

The expected relationships and outcomes are literals. Fixture rendering uses the
installed renderer solely to retain its exact derived presentation contract.
Financial run bytes, every signed material and all other trust fields stay fixed.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from crypto_reconciliation_lab.provenance.demo import build_fixture
from crypto_reconciliation_lab.provenance.exporter import export_provenance
from crypto_reconciliation_lab.provenance.ui import render_page
from crypto_reconciliation_lab.provenance.verifier import verify_bundle


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def load(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_bytes(encoded(value))


def fingerprint(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def material_inventory(bundle):
    return {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
            for p in sorted((bundle/'materials').rglob('*')) if p.is_file()}


def reseal(bundle, expectations):
    """Explicit TEST-ONLY repin, with no authority or financial recalculation."""
    run, capture, report = [load(bundle/name) for name in
                            ('run.json', 'capture.json', 'report.json')]
    expected = load(expectations)
    expected['capture_digest'] = hashlib.sha256(encoded(capture)).hexdigest()
    report['capture_digest'] = expected['capture_digest']
    write(expectations, expected)
    write(bundle/'report.json', report)
    for name, raw in render_page(run, report, capture, material_inventory(bundle)).items():
        (bundle/name).write_bytes(raw)
    manifest = load(bundle/'manifest.json')
    manifest['files'] = {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
                         for p in sorted(bundle.rglob('*'))
                         if p.is_file() and p.name != 'manifest.json'}
    write(bundle/'manifest.json', manifest)


def promote_later_replay(tables):
    """The independent witness's exact first-position relationship mutation."""
    attempts = {row['id']: row for row in tables['delivery_attempts']}
    decisions = {row['id']: row for row in tables['auth_decisions']}
    assert attempts[1]['outcome'] == 'COMMITTED'
    assert attempts[31]['outcome'] == 'REPLAY'
    assert (attempts[1]['stream_id'], attempts[1]['sequence']) == ('lark-feed:financial', 1)
    attempts[1]['outcome'], attempts[31]['outcome'] = 'REPLAY', 'COMMITTED'
    link = next(row for row in tables['auth_delivery_links']
                if (row['stream_id'], row['sequence']) == ('lark-feed:financial', 1))
    assert link['decision_id'] == 1
    link['decision_id'] = 31
    for name in ('epoch', 'policy_hash', 'decision', 'current_key_status'):
        decisions[31][name] = decisions[1][name]


class ProvenanceCausalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.templates = {}
        for scenario in ('rotation', 'replay'):
            fixture = build_fixture(cls.root/(scenario+'-fixture'), scenario=scenario)
            bundle = cls.root/(scenario+'-bundle')
            export_provenance(fixture['database'], fixture['run_id'], fixture['material_dir'], bundle)
            cls.templates[scenario] = (bundle, fixture['expectations'])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        case = self.root/self._testMethodName
        case.mkdir()
        self.bundle = case/'bundle'
        self.expectations = case/'expectations.json'
        self.scenario = 'replay' if 'current_replay' in self._testMethodName else 'rotation'
        bundle, expectations = self.templates[self.scenario]
        shutil.copytree(bundle, self.bundle)
        shutil.copyfile(expectations, self.expectations)
        self.raw_run = (self.bundle/'run.json').read_bytes()
        self.materials = material_inventory(self.bundle)
        self.external = load(self.expectations)

    def mutate(self, change):
        capture = load(self.bundle/'capture.json')
        change(capture['tables'])
        write(self.bundle/'capture.json', capture)
        reseal(self.bundle, self.expectations)
        self.assertEqual((self.bundle/'run.json').read_bytes(), self.raw_run)
        self.assertEqual(material_inventory(self.bundle), self.materials)
        expected = load(self.expectations)
        self.assertEqual({k: v for k, v in expected.items() if k != 'capture_digest'},
                         {k: v for k, v in self.external.items() if k != 'capture_digest'})
        self.assertNotEqual(expected['capture_digest'], self.external['capture_digest'])

    def check_success(self, *, sequence=1, committed=1, original=1, replays=(31,)):
        result = verify_bundle(self.bundle, self.expectations)
        self.assertEqual((result['exit_code'], result['status']), (0, 'VERIFIED_FOR_CAPTURE'), result)
        chain = next(row for row in result['candidates']
                     if (row['stream_id'], row['sequence']) == ('lark-feed:financial', sequence))
        self.assertEqual(chain['committed_attempt_id'], committed)
        self.assertEqual(chain['original_decision_id'], original)
        self.assertEqual(chain['replay_attempt_ids'], list(replays))
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')
        self.assertEqual(result['financial_recomputation'], 'NOT_PERFORMED')
        return result

    def check_causality_failure(self):
        result = verify_bundle(self.bundle, self.expectations)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['reasons'][0]['code'], 'DELIVERY_CAUSALITY', result)
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')

    def test_rotation_keeps_original_commit_and_later_historical_replay_distinct(self):
        self.check_success()

    def test_current_replay_keeps_original_commit_and_later_current_replay_distinct(self):
        self.check_success()

    def test_later_replay_cannot_be_promoted_over_earlier_effect_reference(self):
        self.mutate(promote_later_replay)
        self.check_causality_failure()

    def test_missing_snapshot_cannot_hide_promoted_later_replay(self):
        self.mutate(promote_later_replay)
        capture = load(self.bundle/'capture.json')
        row = next(r for r in capture['tables']['auth_endorsements']
                   if r['source'] == 'LARK_EXCHANGE')
        (self.bundle/'materials/snapshots'/(row['snapshot_hash']+'.jsonl')).unlink()
        reseal(self.bundle, self.expectations)
        self.check_causality_failure()

    def test_current_replay_decision_cannot_precede_original_decision(self):
        def invert(t):
            swap = {1: 31, 31: 1}
            for row in t['auth_decisions']:
                row['id'] = swap.get(row['id'], row['id'])
            for table in ('auth_attempt_links', 'auth_delivery_links'):
                for row in t[table]:
                    row['decision_id'] = swap.get(row['decision_id'], row['decision_id'])
            t['auth_decisions'].sort(key=lambda row: row['id'])
        self.mutate(invert)
        self.check_causality_failure()

    def test_current_replay_any_prior_effect_reference_requires_original_commit(self):
        def earlier(t):
            promote_later_replay(t)
            t['delivery_attempts'][0]['outcome'] = 'BLOCKED'
        self.mutate(earlier)
        self.check_causality_failure()

    def test_earlier_gap_without_effect_reference_is_allowed(self):
        def gap(t):
            # Allocate an earlier attempt/decision at sequence 2 before that
            # effect existed. Other identities shift consistently, not clocks.
            for row in t['delivery_attempts']:
                row['id'] += 1
            for row in t['auth_decisions']:
                row['id'] += 1
            for row in t['auth_attempt_links']:
                row['attempt_id'] += 1
                row['decision_id'] += 1
            for row in t['auth_delivery_links']:
                row['decision_id'] += 1
            attempt = copy.deepcopy(next(r for r in t['delivery_attempts'] if r['id'] == 3))
            attempt.update(id=1, outcome='GAP', effect_stream_id=None, effect_sequence=None,
                           reason='noncontiguous delivery; no effect yet')
            decision = copy.deepcopy(next(r for r in t['auth_decisions'] if r['id'] == 3))
            decision['id'] = 1
            t['delivery_attempts'].insert(0, attempt)
            t['auth_decisions'].insert(0, decision)
            t['auth_attempt_links'].insert(0, {'attempt_id': 1, 'decision_id': 1})
        self.mutate(gap)
        self.check_success(sequence=2, committed=3, original=3, replays=(33,))

    def test_wall_clock_reversal_does_not_replace_persistent_identity_order(self):
        def reverse_clocks(t):
            for table in ('delivery_attempts', 'auth_decisions'):
                for row in t[table]:
                    row['observed_at'] = ('2026-11-14T00:00:00.000000Z' if row['id'] >= 31
                                          else '2026-11-15T00:00:00.000000Z')
        self.mutate(reverse_clocks)
        self.check_success()
