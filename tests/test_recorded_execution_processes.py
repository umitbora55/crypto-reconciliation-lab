"""Real SIGKILL, separate-connection contention and ordered writer races."""
from contextlib import closing
import json
from pathlib import Path
import signal
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.engine import reconcile
from crypto_reconciliation_lab.execution import read_execution
from crypto_reconciliation_lab.execution.demo import build_fixture, sign_snapshot, PLATFORM
from recorded_execution_process import Child, evidence_folder, normal, write


TABLES = ('runs', 'findings', 'evidence', 'correction_groups', 'correction_effects',
          'execution_contexts', 'recorded_executions')


def durable(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: [list(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in TABLES}


class RecordedExecutionProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = evidence_folder(self._testMethodName, self.root)

    def fixture(self, name='fixture', protected=False):
        return build_fixture(self.root/name, protected=protected)

    def request(self, fixture, request_id, **options):
        return {'action': 'recorded', 'db': str(fixture['database']),
                'balance_at': fixture['balance_at'], 'knowledge_at': fixture['knowledge_at'],
                'request_id': request_id, **options}

    def successful(self, folder, name, request):
        event, proof = normal(folder, name, request)
        self.assertEqual(proof['exit_code'], 0, proof)
        self.assertFalse(proof['forced_timeout_cleanup'])
        if request['action'] == 'recorded':
            self.assertEqual(event['result']['status'], 'RECORDED')
            self.assertEqual(event['ack']['exit_code'], 0, event['ack'])
            acknowledged = json.loads(event['ack']['stdout'])
            self.assertEqual(acknowledged['execution_id'], event['result']['execution_id'])
            self.assertEqual(acknowledged['replayed'], event['result']['replayed'])
        return event['result'], proof

    def kill_cases(self, point, committed):
        for existing in (False, True):
            with self.subTest(existing_financial_run=existing):
                suffix = 'existing' if existing else 'fresh'
                folder = self.evidence/suffix
                folder.mkdir()
                fixture = self.fixture(suffix)
                if existing:
                    with closing(Store(fixture['database'])) as store:
                        reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
                before = durable(fixture['database'])
                request = self.request(fixture, 'kill-'+suffix, barrier=point)
                child = Child(folder, 'interrupted', request)
                try:
                    child.send('GO')
                    reached = child.receive('BARRIER')
                    self.assertEqual(reached['point'], point)
                    self.assertEqual(reached['in_transaction'], not committed)
                    self.assertEqual(reached['counts']['runs'], 1)
                    self.assertEqual(reached['counts']['findings'], 6)
                    self.assertGreater(reached['counts']['evidence'], 0)
                    expected_contexts = 0 if point == 'execution_after_financial' else 1
                    self.assertEqual(reached['counts']['execution_contexts'], expected_contexts)
                    self.assertEqual(reached['counts']['recorded_executions'], expected_contexts)
                    proof = child.finish(kill=True)
                finally:
                    if child.process.poll() is None:
                        child.finish(kill=True)
                self.assertEqual(proof['exit_code'], -signal.SIGKILL, proof)
                self.assertTrue(proof['joined'])
                self.assertFalse(any(m['type'] == 'RESULT' for m in proof['messages']))
                self.assertEqual(proof['sender_result'], 'UNKNOWN')
                self.assertEqual(proof['stdout_tail'], '')
                after = durable(fixture['database'])
                if committed:
                    self.assertEqual(len(after['recorded_executions']), 1)
                    self.assertEqual(len(after['execution_contexts']), 1)
                    original_id = after['recorded_executions'][0][0]
                    saved = read_execution(fixture['database'], original_id)
                    self.assertEqual(saved['request_id'], request['request_id'])
                else:
                    self.assertEqual(after, before)
                result, _ = self.successful(folder, 'retry', self.request(fixture, request['request_id']))
                self.assertEqual(result['replayed'], committed)
                if committed:
                    self.assertEqual(result['execution_id'], original_id)
                final = durable(fixture['database'])
                self.assertEqual(len(final['runs']), 1)
                self.assertEqual(len(final['recorded_executions']), 1)
                self.assertEqual(len(final['execution_contexts']), 1)
                if existing:
                    for table in TABLES[:5]:
                        self.assertEqual(final[table], before[table], table)
                # BLOB context bytes remain exact in SQLite; the evidence JSON
                # records row counts and run TEXT separately, never lossy bytes.
                write(folder/'durability.json', {'point': point, 'existing_run': existing,
                      'before_counts': {k: len(v) for k, v in before.items()},
                      'after_kill_counts': {k: len(v) for k, v in after.items()},
                      'after_retry_counts': {k: len(v) for k, v in final.items()},
                      'retry_execution_id': result['execution_id'], 'retry_replayed': result['replayed'],
                      'passed': True})

    def test_sigkill_after_financial_persistence_rolls_back_fresh_and_existing_variants(self):
        self.kill_cases('execution_after_financial', False)

    def test_sigkill_after_context_before_commit_rolls_back_fresh_and_existing_variants(self):
        self.kill_cases('execution_after_context', False)

    def test_sigkill_after_commit_before_cli_ack_retries_durable_original(self):
        self.kill_cases('execution_after_commit', True)

    def contender(self, fixture, action):
        if action == 'policy':
            with closing(sqlite3.connect(fixture['database'])) as db:
                epoch, policy_hash = db.execute('SELECT epoch,policy_hash FROM auth_policy_activations ORDER BY epoch DESC LIMIT 1').fetchone()
            return {'action': 'policy', 'db': str(fixture['database']), 'policy': fixture['rotated_policy'],
                    'expected_epoch': epoch, 'expected_hash': policy_hash, 'busy_timeout_ms': 100}
        data = Path(fixture['snapshot_paths'][PLATFORM]).read_bytes().splitlines(keepends=True)[0]
        snapshot = self.evidence/'duplicate.jsonl'
        envelope = self.evidence/'duplicate-envelope.json'
        snapshot.write_bytes(data)
        envelope.write_bytes(sign_snapshot(data, source=PLATFORM, stream_id='test-platform:second-physical'))
        return {'action': 'admission', 'db': str(fixture['database']), 'snapshot': str(snapshot),
                'envelope': str(envelope), 'busy_timeout_ms': 100}

    def assert_cut(self, result, action, later):
        context = result['context']
        self.assertEqual(context['counts']['receipts'], 31 if later and action == 'admission' else 30)
        self.assertEqual(context['observed_policy_head']['epoch'], 2 if later and action == 'policy' else 1)
        self.assertEqual(context['acceptance_epochs'], [1])

    def before_cut(self, action):
        fixture = self.fixture(protected=True)
        contender = self.contender(fixture, action)
        accepted, proof = self.successful(self.evidence, 'writer-before-cut', contender)
        if action == 'admission':
            self.assertEqual(accepted['status'], 'COMPLETE')
            self.assertEqual(accepted['responses'][0]['outcome'], 'COMMITTED')
        result, evaluation = self.successful(self.evidence, 'execution', self.request(fixture, 'before-cut'))
        self.assertNotEqual(proof['pid'], evaluation['pid'])
        self.assert_cut(result, action, True)

    def after_cut(self, action):
        fixture = self.fixture(protected=True)
        request = self.request(fixture, 'first-cut', barrier='execution_after_begin')
        holder = Child(self.evidence, 'execution-holder', request)
        try:
            holder.send('GO')
            self.assertTrue(holder.receive('BARRIER')['in_transaction'])
            contender = self.contender(fixture, action)
            blocked = Child(self.evidence, 'writer-contender', {**contender, 'observe_begin': True})
            try:
                blocked.send('GO')
                trace = blocked.receive('SQL_BEGIN_ATTEMPT')
                self.assertEqual(trace['statement'], 'BEGIN IMMEDIATE')
                observed = blocked.receive('RESULT' if action == 'admission' else 'ERROR')
                blocked_proof = blocked.finish()
            finally:
                if blocked.process.poll() is None:
                    blocked.finish(kill=True)
            self.assertNotEqual(holder.process.pid, blocked.process.pid)
            if action == 'admission':
                self.assertEqual(observed['result']['status'], 'RETRYABLE_BUSY')
                self.assertEqual(observed['result']['responses'], [])
                self.assertEqual(blocked_proof['exit_code'], 0)
            else:
                self.assertEqual(observed['reason_code'], 'SQLITE_BUSY')
                self.assertEqual(blocked_proof['exit_code'], 2)
            holder.send('CONTINUE')
            first = holder.receive('RESULT')['result']
            self.assertEqual(holder.finish()['exit_code'], 0)
        finally:
            if holder.process.poll() is None:
                holder.finish(kill=True)
        self.assert_cut(first, action, False)
        # A bounded BUSY is not a committed writer. The separate post-cut
        # attempt must genuinely commit before the next execution sees it.
        committed, _ = self.successful(self.evidence, 'writer-after-cut', contender)
        if action == 'admission':
            self.assertEqual(committed['status'], 'COMPLETE')
        later, _ = self.successful(self.evidence, 'later-execution', self.request(fixture, 'second-cut'))
        self.assert_cut(later, action, True)
        self.assertEqual(read_execution(fixture['database'], first['execution_id'])['context'], first['context'])
        write(self.evidence/'cut-observation.json', {'action': action, 'busy_is_not_commit': True,
              'first_execution_id': first['execution_id'], 'second_execution_id': later['execution_id'],
              'first_counts': first['context']['counts'], 'second_counts': later['context']['counts'],
              'first_policy_head': first['context']['observed_policy_head'],
              'second_policy_head': later['context']['observed_policy_head'], 'passed': True})

    def test_separate_process_admission_before_cut_is_wholly_present(self):
        self.before_cut('admission')

    def test_separate_process_admission_after_cut_cannot_mix_with_first_context(self):
        self.after_cut('admission')

    def test_separate_process_policy_before_cut_is_wholly_present(self):
        self.before_cut('policy')

    def test_separate_process_policy_after_cut_cannot_mix_with_first_context(self):
        self.after_cut('policy')

    def test_same_request_in_two_processes_has_one_durable_execution(self):
        fixture = self.fixture()
        request = self.request(fixture, 'same-request', busy_timeout_ms=100)
        holder = Child(self.evidence, 'first-process', {**request, 'barrier': 'execution_after_begin'})
        try:
            holder.send('GO')
            holder.receive('BARRIER')
            other, proof = normal(self.evidence, 'second-process', request, expected='ERROR')
            self.assertNotEqual(holder.process.pid, proof['pid'])
            self.assertEqual((other['reason_code'], proof['exit_code']), ('EXECUTION_BUSY', 2))
            holder.send('CONTINUE')
            first = holder.receive('RESULT')['result']
            self.assertEqual(holder.finish()['exit_code'], 0)
        finally:
            if holder.process.poll() is None:
                holder.finish(kill=True)
        retry, _ = self.successful(self.evidence, 'second-process-retry', request)
        self.assertTrue(retry['replayed'])
        self.assertEqual(retry['execution_id'], first['execution_id'])
        after = durable(fixture['database'])
        self.assertEqual(len(after['recorded_executions']), 1)
        self.assertEqual(len(after['execution_contexts']), 1)
        self.assertEqual(len(after['runs']), 1)
