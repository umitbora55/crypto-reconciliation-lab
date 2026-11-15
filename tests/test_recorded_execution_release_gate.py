"""Fixed release evidence coverage; synthetic transcripts are never run claims."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import crypto_reconciliation_lab
from crypto_reconciliation_lab.execution.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('recorded_execution_release_gate', ROOT/'scripts/verify_release.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
ORIGIN = crypto_reconciliation_lab.__file__


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')


def load(path):
    return json.loads(path.read_text())


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def literal_financial():
    # These expectations are independent of engine, demo, and gate helpers.
    ledgers = {
        'ASSET_A': {'investor_balances': {'I1': '7', 'I2': '4'}, 'liability': '11', 'custody_rollforward': {'platform': '2', 'external': '9'}},
        'ASSET_B': {'investor_balances': {'I1': '0.3', 'I2': '0.2'}, 'liability': '0.5', 'custody_rollforward': {'platform': '0.05', 'external': '0.45'}},
    }
    findings = []
    for asset, comparison, scope, amount in (
            ('ASSET_A', 'A', 'I1', '7'), ('ASSET_A', 'A', 'I2', '4'), ('ASSET_A', 'B', 'customer_liability', '11'),
            ('ASSET_B', 'A', 'I1', '0.3'), ('ASSET_B', 'A', 'I2', '0.2'), ('ASSET_B', 'B', 'customer_liability', '0.5')):
        findings.append({'asset': asset, 'comparison': comparison, 'scope': scope, 'expected': amount,
                         'reported': amount, 'difference': '0', 'data_state': 'COMPLETE', 'reconciliation_state': 'MATCHED'})
    return {'rule_version': 'stage2-v2', 'ledgers': ledgers, 'findings': findings}


KILLS = {
    'test_sigkill_after_financial_persistence_rolls_back_fresh_and_existing_variants': 'execution_after_financial',
    'test_sigkill_after_context_before_commit_rolls_back_fresh_and_existing_variants': 'execution_after_context',
    'test_sigkill_after_commit_before_cli_ack_retries_durable_original': 'execution_after_commit',
}
RACES = {
    'test_separate_process_admission_before_cut_is_wholly_present': ('admission', 'before'),
    'test_separate_process_admission_after_cut_cannot_mix_with_first_context': ('admission', 'after'),
    'test_separate_process_policy_before_cut_is_wholly_present': ('policy', 'before'),
    'test_separate_process_policy_after_cut_cannot_mix_with_first_context': ('policy', 'after'),
}
SAME = 'test_same_request_in_two_processes_has_one_durable_execution'
EMPTY = {name: 0 for name in ('runs', 'findings', 'evidence', 'correction_groups', 'correction_effects', 'execution_contexts', 'recorded_executions')}
DURABLE = dict(EMPTY, runs=1, findings=6, evidence=60, execution_contexts=1, recorded_executions=1)


def literal_result(request='request', *, replayed=False, protected=False, receipts=30, epoch=None, second=False):
    cuts = {'balance_at': '2026-11-12T23:59:59.000000Z', 'knowledge_at': '2026-11-13T01:00:00.000000Z'}
    stable = {'format': 'recorded-execution-v1', 'db_scope': 'local-request-registry',
              'configuration_digest': 'd'*64, 'rule_version': 'stage2-v2',
              'profile': 'all-known-receipts-v1', **cuts}
    tables = {'records': [{'id': i} for i in range(30)], 'receipts': [{'id': i} for i in range(receipts)],
              'delivery_effects': [{} for _ in range(receipts)] if protected else [],
              'auth_decisions': [{} for _ in range(receipts)] if protected else []}
    context = {'schema_version': 6, 'scope': {'complete': True}, 'tables': tables,
               'request_id': request, 'request': stable,
               'counts': {k: len(v) for k, v in tables.items()},
               'selected_evidence': {str(i): {} for i in range(60)},
               'observed_policy_head': {'epoch': epoch} if epoch else None,
               'acceptance_epochs': [1] if protected else [],
               'claims': {'context_state': 'RECORDED', 'admission_mode': 'PROTECTED' if protected else 'LEGACY',
                          'legacy_signature_status': 'NOT_APPLICABLE' if protected else 'UNSIGNED',
                          'source_signature_verification': 'NOT_PERFORMED', 'run_actor_authorization': 'NOT_DEFINED'}}
    return {'status': 'RECORDED', 'request_id': request, 'replayed': replayed,
            'run_id': 'a'*64, 'execution_id': ('c' if second else 'b')*64,
            'request': stable, 'context': context, 'financial_result': {**literal_financial(), **cuts}}


def synthetic_process_evidence(root):
    """Hand-authored UNIT TEST ONLY evidence; no subprocess execution implied."""
    next_pid = 1000
    def child(directory, name, *, result=None, barrier=None, counts=None, exit_code=0,
              error=None, begin=False, killed=False, request_id='request', action='recorded'):
        nonlocal next_pid
        next_pid += 1
        pid = next_pid
        database = '/test-only/databases/' + directory.relative_to(root).as_posix() + '/source.sqlite3'
        request = {'action': action, 'db': database, 'fixture_role': 'SYNTHETIC_UNIT_TEST_TRANSCRIPT'}
        if action == 'recorded':
            request.update(request_id=result['request_id'] if result is not None else request_id,
                           balance_at='2026-11-12T23:59:59.000000Z', knowledge_at='2026-11-13T01:00:00.000000Z')
        elif action == 'admission':
            request.update(snapshot=database + '.jsonl', envelope=database + '.envelope.json', busy_timeout_ms=100)
        else:
            request.update(policy={'epoch': 2, 'fixture_role': 'SYNTHETIC_UNIT_TEST_POLICY'},
                           expected_epoch=1, expected_hash='e'*64, busy_timeout_ms=100)
        if barrier:
            request['barrier'] = barrier['point']
        if begin:
            request['observe_begin'] = True
        save(directory/(name+'-request.json'), request)
        settings = {'journal_mode': 'delete', 'synchronous': 2, 'busy_timeout': 250}
        messages = [{'type': 'READY', 'pid': pid, 'origin': ORIGIN, 'interpreter': '/test-only/python',
                     'isolated': False, 'sqlite': 'test-only', 'settings': settings, 'counts': counts or EMPTY}]
        if barrier:
            messages.append({'type': 'BARRIER', 'pid': pid, **barrier})
        if begin:
            messages.append({'type': 'SQL_BEGIN_ATTEMPT', 'pid': pid, 'statement': 'BEGIN IMMEDIATE'})
        if error:
            messages.append({'type': 'ERROR', 'pid': pid, 'reason_code': error})
        if result is not None:
            event = {'type': 'RESULT', 'pid': pid, 'result': result, 'counts': DURABLE}
            if result.get('status') == 'RECORDED':
                event['ack'] = {'exit_code': 0, 'argv': ['reconcile-recorded', '--db', database,
                               '--balance-at', request['balance_at'], '--knowledge-at', request['knowledge_at'],
                               '--request-id', request['request_id'], '--busy-timeout-ms', '250'], 'stdout': json.dumps(result)}
            messages.append(event)
        row = {'pid': pid, 'exit_code': exit_code, 'joined': True, 'forced_timeout_cleanup': False,
               'started_at': 'TEST_ONLY_NOT_AN_EXECUTION', 'cwd': '/test-only',
               'argv': ['/test-only/python', '-B', '--request', str(directory/(name+'-request.json'))],
               'messages': messages, 'signal': 'SIGKILL' if killed else None,
               'sender_result': 'UNKNOWN' if killed else 'RESPONSE', 'stdout_tail': '', 'stderr': ''}
        save(directory/(name+'-process.json'), row)
        (directory/(name+'-stdout-tail.txt')).write_text('')
        (directory/(name+'-stderr.txt')).write_text('')
    for name, point in KILLS.items():
        for variant in ('fresh', 'existing'):
            directory = root/(name+'-fixture')/variant
            before = dict(EMPTY, **({'runs': 1, 'findings': 6, 'evidence': 60} if variant == 'existing' else {}))
            committed = point == 'execution_after_commit'
            barrier_counts = dict(DURABLE, **({'execution_contexts': 0, 'recorded_executions': 0} if point == 'execution_after_financial' else {}))
            child(directory, 'interrupted', barrier={'point': point, 'in_transaction': not committed, 'counts': barrier_counts},
                  counts=before, exit_code=-9, killed=True)
            retry = literal_result(replayed=committed)
            child(directory, 'retry', result=retry)
            save(directory/'durability.json', {'point': point, 'existing_run': variant == 'existing',
                 'before_counts': before, 'after_kill_counts': DURABLE if committed else before,
                 'after_retry_counts': DURABLE, 'retry_replayed': committed, 'retry_execution_id': retry['execution_id']})
    for name, (action, timing) in RACES.items():
        directory = root/(name+'-fixture')
        written = {'status': 'COMPLETE'} if action == 'admission' else {
            'epoch': 2, 'payload': {'epoch': 2, 'fixture_role': 'SYNTHETIC_UNIT_TEST_POLICY'}}
        second = literal_result('second-cut', protected=True, receipts=31 if action == 'admission' else 30, epoch=1 if action == 'admission' else 2, second=True)
        if timing == 'before':
            child(directory, 'writer-before-cut', result=written, action=action)
            child(directory, 'execution', result=second)
        else:
            first = literal_result('first-cut', protected=True, epoch=1)
            child(directory, 'execution-holder', result=first, barrier={'point': 'execution_after_begin', 'in_transaction': True})
            if action == 'admission':
                child(directory, 'writer-contender', result={'status': 'RETRYABLE_BUSY', 'responses': [], 'rejection': {'durable': False}}, begin=True, action=action)
            else:
                child(directory, 'writer-contender', error='SQLITE_BUSY', exit_code=2, begin=True, action=action)
            child(directory, 'writer-after-cut', result=written, action=action)
            child(directory, 'later-execution', result=second)
            save(directory/'cut-observation.json', {'action': action, 'busy_is_not_commit': True,
                 'first_execution_id': first['execution_id'], 'second_execution_id': second['execution_id'],
                 'first_counts': first['context']['counts'], 'second_counts': second['context']['counts']})
    directory = root/(SAME+'-fixture')
    first = literal_result()
    child(directory, 'first-process', result=first, barrier={'point': 'execution_after_begin', 'in_transaction': True})
    child(directory, 'second-process', error='EXECUTION_BUSY', exit_code=2)
    child(directory, 'second-process-retry', result=literal_result(replayed=True))


class RecordedExecutionDemoGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.baseline = Path(cls.temp.name)/'baseline'
        run_demo(cls.baseline, profile='legacy')

    def setUp(self):
        self.temp_case = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_case.cleanup)
        self.root = Path(self.temp_case.name)/'demo'
        shutil.copytree(self.baseline, self.root)

    def check(self):
        return gate.validate_execution_demo(self.root, profile='legacy', package_origin=ORIGIN)

    def test_complete_nine_case_demo_requires_real_bound_cli_results(self):
        result = self.check()
        self.assertEqual((result['status'], result['case_count']), ('PASS', 9))
        self.assertEqual(result['cases']['legacy_conflict']['exit_code'], 2)
        self.assertEqual(result['cases']['legacy_export_existing']['exit_code'], 2)

    def test_missing_or_duplicate_demo_case_never_passes_rewritten_summary_inventory(self):
        original = load(self.root/'summary.json')
        for mode in ('missing', 'duplicate'):
            with self.subTest(mode=mode):
                summary = copy.deepcopy(original)
                if mode == 'missing':
                    summary['cases'].pop(); summary['case_inventory'].pop()
                else:
                    summary['cases'].append(copy.deepcopy(summary['cases'][0])); summary['case_inventory'].append(summary['case_inventory'][0])
                save(self.root/'summary.json', summary)
                with self.assertRaisesRegex(ValueError, 'missing, duplicate or unexpected cases'):
                    self.check()

    def test_wrong_negative_reason_rejected_with_coherent_stdout_hash_and_summary(self):
        folder = self.root/'commands/legacy_conflict'
        result = load(folder/'result.json'); result['reason_code'] = 'EXECUTION_OUTPUT'
        save(folder/'result.json', result); save(folder/'stdout.txt', result)
        command = load(folder/'command.json'); command['stdout'] = identity(folder/'stdout.txt'); save(folder/'command.json', command)
        summary = load(self.root/'summary.json')
        case = next(c for c in summary['cases'] if c['id'] == 'legacy_conflict')
        case['actual']['reason_code'] = case['expected']['reason_code'] = 'EXECUTION_OUTPUT'
        save(self.root/'summary.json', summary)
        with self.assertRaisesRegex(ValueError, 'actual exit/status/reason differs'):
            self.check()

    def test_changed_actual_cli_log_rejected_even_when_result_file_claims_success(self):
        (self.root/'commands/legacy_recorded/stdout.txt').write_text('{"status":"RECORDED"}\n')
        with self.assertRaisesRegex(ValueError, 'missing or changed CLI log'):
            self.check()


class RecordedExecutionProcessGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'synthetic-unit-transcripts'
        synthetic_process_evidence(self.root)

    def check(self):
        return gate.validate_execution_process_evidence(self.root, package_origin=ORIGIN, isolated=False)

    def test_complete_fixed_transcript_inventory_has_six_kills_four_races_and_one_request(self):
        result = self.check()
        self.assertEqual((result['status'], result['test_count'], result['process_count']), ('PASS', 8, 27))
        self.assertEqual(len(result['kill_variants']), 6)
        self.assertEqual(len(result['race_cases']), 4)
        self.assertEqual(result['same_request']['durable_executions'], 1)

    def test_missing_existing_run_kill_variant_is_not_complete_coverage(self):
        name = 'test_sigkill_after_commit_before_cli_ack_retries_durable_original-fixture'
        shutil.rmtree(self.root/name/'existing')
        with self.assertRaisesRegex(ValueError, 'missing or unsafe member'):
            self.check()

    def test_duplicate_test_evidence_is_rejected_instead_of_selecting_first(self):
        directory = self.root/(SAME+'-fixture')
        shutil.copytree(directory, self.root/(SAME+'-duplicate'))
        with self.assertRaisesRegex(ValueError, 'missing or repeated test evidence'):
            self.check()

    def test_busy_writer_cannot_claim_durable_commit(self):
        path = self.root/'test_separate_process_admission_after_cut_cannot_mix_with_first_context-fixture/writer-contender-process.json'
        row = load(path)
        next(m for m in row['messages'] if m['type'] == 'RESULT')['result']['rejection']['durable'] = True
        save(path, row)
        with self.assertRaisesRegex(ValueError, 'busy admission claimed a commit'):
            self.check()

    def test_same_pid_cannot_establish_separate_concurrent_writer_processes(self):
        directory = self.root/'test_separate_process_policy_after_cut_cannot_mix_with_first_context-fixture'
        parent = load(directory/'execution-holder-process.json')
        path = directory/'writer-contender-process.json'; row = load(path)
        row['pid'] = parent['pid']
        for message in row['messages']:
            message['pid'] = parent['pid']
        save(path, row)
        with self.assertRaisesRegex(ValueError, 'after-cut competing writer was not observed at the locked boundary'):
            self.check()

    def test_cli_ack_must_match_durable_retry_not_merely_zero_exit(self):
        path = self.root/'test_sigkill_after_commit_before_cli_ack_retries_durable_original-fixture/existing/retry-process.json'
        row = load(path); event = next(m for m in row['messages'] if m['type'] == 'RESULT')
        value = json.loads(event['ack']['stdout']); value['execution_id'] = 'f'*64
        event['ack']['stdout'] = json.dumps(value)
        save(path, row)
        with self.assertRaisesRegex(ValueError, 'first real CLI ACK differs'):
            self.check()
