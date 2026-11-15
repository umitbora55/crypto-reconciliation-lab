"""Original admission epochs exclude both CURRENT and historical replays."""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.execution import (
    ExecutionError, reconcile_recorded, read_execution, export_execution,
)
from crypto_reconciliation_lab.execution.demo import (
    build_fixture, sign_snapshot, snapshot, PLATFORM, CUSTODIAN,
)
from crypto_reconciliation_lab.source_auth.runtime import activate_policy, ingest_signed
from stage12_1_epoch_fixture import historical_records


PHASES = ('before-rotation', 'after-rotation', 'after-current-replay',
          'after-historical-replay', 'after-real-new-delivery')
EXPECTED = ([1], [1], [1], [1], [1, 2])


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def durable(database):
    with closing(sqlite3.connect(database)) as db:
        return tuple(db.iterdump())


def evidence(name, value):
    directory = os.environ.get('CRYPTO_STAGE12_1_TEST_EVIDENCE')
    if directory:
        target = Path(directory)/('f2-'+name+'.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise AssertionError('test evidence must not overwrite an earlier execution')
        target.write_bytes(encoded(value)+b'\n')


def rebind_historical(entry, change):
    """Controlled test mutation: repair byte identities, never semantic links."""
    entry = copy.deepcopy(entry)
    context = json.loads(bytes.fromhex(entry['context_hex']))
    change(context)
    raw = encoded(context)
    entry['context_hex'] = raw.hex()
    entry['row']['context_hash'] = hashlib.sha256(raw).hexdigest()
    bound = {'format': 'recorded-execution-v1', **{key: entry['row'][key] for key in (
        'request_id', 'request_fingerprint', 'run_id', 'run_payload_sha256', 'context_hash')}}
    entry['row']['execution_id'] = hashlib.sha256(encoded(bound)).hexdigest()
    return entry


class OriginalAcceptanceEpochTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.fixture = fixture = build_fixture(cls.root/'five-steps', protected=True)
        cls.results, cls.admissions, cls.original_rows = [], [], []
        with closing(Store(fixture['database'])) as store:
            def record(name):
                result = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], name)
                cls.results.append(result)
                # SQL join is an independent check, not the production derivation.
                cls.original_rows.append([tuple(row) for row in store.db.execute('''
                    SELECT l.stream_id,l.sequence,l.core_receipt_id,l.decision_id,d.epoch,a.id
                    FROM auth_delivery_links l
                    JOIN delivery_effects e ON e.stream_id=l.stream_id AND e.sequence=l.sequence
                         AND e.core_receipt_id=l.core_receipt_id
                    JOIN delivery_attempts a ON a.stream_id=e.stream_id AND a.sequence=e.sequence
                         AND a.outcome='COMMITTED' AND a.effect_stream_id=e.stream_id
                         AND a.effect_sequence=e.sequence
                    JOIN auth_attempt_links al ON al.attempt_id=a.id AND al.decision_id=l.decision_id
                    JOIN auth_decisions d ON d.id=l.decision_id AND d.stream_id=e.stream_id
                         AND d.sequence=e.sequence
                    ORDER BY l.stream_id,l.sequence''')])
                return result
            first = record(PHASES[0])
            head = first['context']['observed_policy_head']
            activate_policy(store, fixture['rotated_policy'], head['epoch'], head['policy_hash'],
                            observed_at='2026-11-15T08:10:00Z')
            record(PHASES[1])
            for source, phase, when in ((CUSTODIAN, PHASES[2], '2026-11-15T08:11:00Z'),
                                        (PLATFORM, PHASES[3], '2026-11-15T08:12:00Z')):
                cls.admissions.append(ingest_signed(store, fixture['snapshot_paths'][source].read_bytes(),
                    fixture['envelope_paths'][source].read_bytes(), observed_at=when))
                record(phase)
            data = snapshot([fixture['records_by_source'][PLATFORM][0]])
            envelope = sign_snapshot(data, source=PLATFORM, stream_id='test-platform:new-delivery', rotated=True)
            cls.admissions.append(ingest_signed(store, data, envelope, observed_at='2026-11-15T08:13:00Z'))
            record(PHASES[4])

    def setUp(self):
        self.case_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.case_temp.cleanup)
        self.case_root = Path(self.case_temp.name)

    def restored(self, phase, change=None):
        fixture = build_fixture(self.case_root/'old-database', protected=True)
        entry = historical_records()[phase]
        if change is not None:
            entry = rebind_historical(entry, change)
        row = entry['row']
        with closing(Store(fixture['database'])) as store:
            financial = reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
            self.assertEqual(financial['run_id'], row['run_id'])
            raw = bytes(store.db.execute('SELECT CAST(payload AS BLOB) FROM runs WHERE id=?', (row['run_id'],)).fetchone()[0])
            self.assertEqual(raw, bytes.fromhex(entry['run_hex']))
            store.db.execute('INSERT INTO execution_contexts VALUES (?,?,?)',
                (row['context_hash'], 'recorded-execution-v1', bytes.fromhex(entry['context_hex'])))
            store.db.execute('INSERT INTO recorded_executions VALUES (?,?,?,?,?,?,?)',
                tuple(bytes.fromhex(row[key]) if key == 'request_payload' else row[key] for key in (
                    'execution_id', 'request_id', 'request_fingerprint', 'request_payload',
                    'run_id', 'run_payload_sha256', 'context_hash')))
        return fixture, entry

    def rejected(self, operation):
        with self.assertRaises(ExecutionError) as error:
            operation()
        self.assertEqual(error.exception.reason_code, 'EXECUTION_INTEGRITY')

    def test_five_actual_admission_steps_have_literal_original_epoch_sets(self):
        evidence(self._testMethodName, {'interpreter': sys.executable,
            'package_origin': str(Path(sys.modules['crypto_reconciliation_lab'].__file__).resolve()),
            'phases': [{'phase': phase, 'literal_expected': expected,
                        'actual': result['context']['acceptance_epochs'],
                        'original_sql_join': original, 'counts': result['context']['counts'],
                        'observed_policy_head': result['context']['observed_policy_head'],
                        'run_id': result['run_id'], 'execution_id': result['execution_id'],
                        'context_hash': result['context_hash']}
                       for phase, result, original, expected in zip(PHASES, self.results, self.original_rows, EXPECTED)],
            'admissions': self.admissions})
        for phase, result, original, expected in zip(PHASES, self.results, self.original_rows, EXPECTED):
            with self.subTest(phase=phase):
                self.assertEqual(sorted({row[4] for row in original}), expected)
                self.assertEqual(result['context']['acceptance_epochs'], expected)

    def test_replay_attempts_and_current_policy_remain_visible_without_new_effects(self):
        self.assertEqual([r['context']['observed_policy_head']['epoch'] for r in self.results], [1, 2, 2, 2, 2])
        for table in ('receipts', 'delivery_effects', 'auth_delivery_links'):
            self.assertEqual([r['context']['counts'][table] for r in self.results], [30, 30, 30, 30, 31])
        self.assertEqual([r['context']['counts']['delivery_attempts'] for r in self.results], [30, 30, 34, 60, 61])
        self.assertEqual([r['context']['counts']['auth_decisions'] for r in self.results], [30, 30, 34, 60, 61])
        for admission, count, label in zip(self.admissions[:2], (4, 26), ('CURRENT', 'HISTORICAL_REPLAY')):
            self.assertEqual(admission['status'], 'COMPLETE')
            self.assertEqual(len(admission['responses']), count)
            self.assertEqual({(r['outcome'], r['authorization']['decision']) for r in admission['responses']}, {('REPLAY', label)})
        self.assertEqual(self.admissions[2]['responses'][0]['outcome'], 'COMMITTED')
        tables = self.results[3]['context']['tables']
        decisions = {row['id']: row for row in tables['auth_decisions']}
        links = {row['attempt_id']: row['decision_id'] for row in tables['auth_attempt_links']}
        details = [(r['id'], decisions[links[r['id']]]['decision'], decisions[links[r['id']]]['epoch'])
                   for r in tables['delivery_attempts'] if r['outcome'] == 'REPLAY']
        self.assertEqual(details, [(i, 'CURRENT', 2) for i in range(31, 35)]
                         + [(i, 'HISTORICAL_REPLAY', 2) for i in range(35, 61)])
        self.assertEqual({r['run_id'] for r in self.results}, {self.results[0]['run_id']})
        for result in self.results:
            self.assertEqual(result['financial_result'], self.results[0]['financial_result'])
            self.assertEqual(result['financial_result']['ledgers']['ASSET_A']['liability'], '11')

    def test_earliest_context_remains_exact_after_rotation_replays_and_new_delivery(self):
        first = self.results[0]
        before = durable(self.fixture['database'])
        self.assertEqual(read_execution(self.fixture['database'], first['execution_id']), first)
        with closing(Store(self.fixture['database'])) as store, \
                patch('crypto_reconciliation_lab.execution.capture.capture_inputs', side_effect=AssertionError('recapture')), \
                patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('recompute')):
            retried = reconcile_recorded(store, self.fixture['balance_at'], self.fixture['knowledge_at'], PHASES[0])
        self.assertEqual(retried, {**first, 'replayed': True})
        self.assertEqual(durable(self.fixture['database']), before)

    def test_corrected_current_replay_summary_exports_original_epoch_only(self):
        result = self.results[2]
        output = self.case_root/'export'
        export_execution(self.fixture['database'], result['execution_id'], output)
        self.assertEqual(json.loads((output/'summary.json').read_bytes())['acceptance_epochs'], [1])
        self.assertEqual(json.loads((output/'context.json').read_bytes())['acceptance_epochs'], [1])

    def test_legacy_unsigned_context_has_no_original_auth_epochs(self):
        fixture = build_fixture(self.case_root/'legacy', protected=False)
        with closing(Store(fixture['database'])) as store:
            result = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'unsigned')
        self.assertEqual(result['context']['acceptance_epochs'], [])
        self.assertEqual(result['context']['claims']['legacy_signature_status'], 'UNSIGNED')

    def test_correct_0100_context_keeps_raw_id_hash_bytes_read_export_and_retry(self):
        fixture, old = self.restored('before-rotation')
        row, raw = old['row'], bytes.fromhex(old['context_hex'])
        before = durable(fixture['database'])
        shown = read_execution(fixture['database'], row['execution_id'])
        self.assertEqual(shown['context'], json.loads(raw))
        for key in ('execution_id', 'run_id', 'context_hash', 'run_payload_sha256', 'request_fingerprint'):
            actual = shown[key] if key in shown else shown['context'][key]
            self.assertEqual(actual, row[key])
        output = self.case_root/'old-export'
        export_execution(fixture['database'], row['execution_id'], output)
        self.assertEqual((output/'context.json').read_bytes(), raw)
        self.assertEqual((output/'run.json').read_bytes(), bytes.fromhex(old['run_hex']))
        with closing(Store(fixture['database'])) as store:
            retried = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], row['request_id'])
        self.assertEqual(retried, {**shown, 'replayed': True})
        self.assertEqual(durable(fixture['database']), before)

    def test_correct_0100_two_original_epochs_are_accepted_without_live_enrichment(self):
        fixture, old = self.restored('after-real-new-delivery')
        before = durable(fixture['database'])
        result = read_execution(fixture['database'], old['row']['execution_id'])
        self.assertEqual(result['context']['acceptance_epochs'], [1, 2])
        self.assertEqual(encoded(result['context']), bytes.fromhex(old['context_hex']))
        self.assertEqual(durable(fixture['database']), before)

    def test_wrong_0100_current_replay_summary_is_refused_without_rewriting(self):
        fixture, old = self.restored('after-current-replay')
        before = durable(fixture['database'])
        self.rejected(lambda: read_execution(fixture['database'], old['row']['execution_id']))
        self.assertEqual(durable(fixture['database']), before)

    def test_wrong_0100_historical_replay_summary_is_refused_without_rewriting(self):
        fixture, old = self.restored('after-historical-replay')
        before = durable(fixture['database'])
        self.rejected(lambda: read_execution(fixture['database'], old['row']['execution_id']))
        self.assertEqual(durable(fixture['database']), before)

    def test_wrong_0100_summary_export_refuses_before_publishing(self):
        fixture, old = self.restored('after-current-replay')
        before = durable(fixture['database'])
        output = self.case_root/'must-not-exist'
        self.rejected(lambda: export_execution(fixture['database'], old['row']['execution_id'], output))
        self.assertFalse(output.exists())
        self.assertEqual(durable(fixture['database']), before)

    def test_wrong_0100_retry_refuses_before_new_execution_or_effect(self):
        fixture, old = self.restored('after-current-replay')
        before = durable(fixture['database'])
        with closing(Store(fixture['database'])) as store, \
                patch('crypto_reconciliation_lab.execution.capture.capture_inputs', side_effect=AssertionError('recapture')), \
                patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('recompute')):
            self.rejected(lambda: reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], old['row']['request_id']))
        self.assertEqual(durable(fixture['database']), before)

    def test_wrong_0100_cli_show_export_retry_are_integrity_errors_without_effects(self):
        fixture, old = self.restored('after-current-replay')
        before = durable(fixture['database'])
        output = self.case_root/'cli-must-not-exist'
        commands = [
            ['show-execution', '--execution-id', old['row']['execution_id']],
            ['export-execution', '--execution-id', old['row']['execution_id'], '--output', str(output)],
            ['reconcile-recorded', '--balance-at', fixture['balance_at'], '--knowledge-at', fixture['knowledge_at'],
             '--request-id', old['row']['request_id']],
        ]
        package = Path(sys.modules['crypto_reconciliation_lab'].__file__).resolve()
        isolated = 'site-packages' in package.parts
        cwd = self.case_root if isolated else package.parent.parent
        env = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME')}
        for arguments in commands:
            with self.subTest(command=arguments[0]):
                argv = [sys.executable, *(['-I'] if isolated else []), '-B', '-m', 'crypto_reconciliation_lab',
                        *arguments, '--db', str(fixture['database'])]
                started = time.time()
                child = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=20)
                evidence(self._testMethodName+'-'+arguments[0], {
                    'argv': argv, 'cwd': str(cwd), 'package_origin': str(package),
                    'interpreter': sys.executable, 'started_unix': started, 'elapsed_seconds': time.time()-started,
                    'exit_code': child.returncode, 'stdout': child.stdout.decode(), 'stderr': child.stderr.decode(),
                    'expected_exit_code': 2, 'expected_reason_code': 'EXECUTION_INTEGRITY',
                    'durable_unchanged': durable(fixture['database']) == before,
                    'export_exists': output.exists(), 'historical_execution_id': old['row']['execution_id'],
                    'historical_context_hash': old['row']['context_hash']})
                self.assertEqual(child.returncode, 2, child.stdout.decode()+child.stderr.decode())
                self.assertEqual(child.stderr, b'')
                payload = json.loads(child.stdout)
                self.assertEqual((payload['status'], payload['reason_code']), ('ERROR', 'EXECUTION_INTEGRITY'))
                self.assertEqual(durable(fixture['database']), before)
        self.assertFalse(output.exists())

    def test_replay_decision_cannot_replace_original_committed_decision_binding(self):
        def change(context):
            link = next(r for r in context['tables']['auth_delivery_links']
                        if r['stream_id'] == 'test-custodian:initial' and r['sequence'] == 1)
            link['decision_id'] = 31  # CURRENT replay; original COMMITTED attempt still binds decision27.
        fixture, old = self.restored('after-current-replay', change)
        before = durable(fixture['database'])
        self.rejected(lambda: read_execution(fixture['database'], old['row']['execution_id']))
        self.assertEqual(durable(fixture['database']), before)

    def test_original_decision_must_belong_to_its_effect_position(self):
        def change(context):
            tables = context['tables']
            for link in tables['auth_delivery_links']:
                if link['decision_id'] in (1, 2):
                    link['decision_id'] = 3-link['decision_id']
            for link in tables['auth_attempt_links']:
                if link['attempt_id'] in (1, 2):
                    link['decision_id'] = 3-link['decision_id']
        fixture, old = self.restored('before-rotation', change)
        before = durable(fixture['database'])
        self.rejected(lambda: read_execution(fixture['database'], old['row']['execution_id']))
        self.assertEqual(durable(fixture['database']), before)


if __name__ == '__main__':
    unittest.main()
